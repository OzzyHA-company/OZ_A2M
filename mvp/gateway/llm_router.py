"""
OZ_A2M LLM Gateway Router
멀티 프로바이더: Gemini (primary) → Groq (fast) → Claude (premium) → Kimi (fallback)
"""

import json
import os
import random
from datetime import datetime
from typing import Dict, List, Optional

import httpx
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = structlog.get_logger()

# ── API 설정 ────────────────────────────────────────────────────
# Gemini (primary - 다수 키 보유)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY_PAID_1') or os.getenv('GEMINI_API_KEY') or ''
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Groq (fast fallback - 4개 키 로테이션)
GROQ_KEYS = [k for k in [
    os.getenv('GROQ_API_KEY'),
    os.getenv('GROQ_API_KEY_1'),
    os.getenv('GROQ_API_KEY_2'),
    os.getenv('GROQ_API_KEY_3'),
    os.getenv('GROQ_API_KEY_4'),
] if k]
GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant')
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Kimi (3rd fallback)
KIMI_API_KEY = os.getenv('KIMI_API_KEY', '')
KIMI_BASE_URL = os.getenv('KIMI_BASE_URL', 'https://api.moonshot.ai/v1')
KIMI_MODEL = 'moonshot-v1-8k'

# Claude (premium fallback)
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
LLM_MODEL = os.getenv('LLM_MODEL', 'claude-3-5-sonnet-20241022')
MAX_TOKENS = int(os.getenv('LLM_MAX_TOKENS', '4096'))

router = APIRouter(prefix="/llm", tags=["LLM"])


# ── Pydantic Models ──────────────────────────────────────────────
class MarketDataRequest(BaseModel):
    symbol: str
    timeframe: str = "1h"
    price_data: List[Dict] = Field(default_factory=list)
    indicators: Dict = Field(default_factory=dict)
    news_context: Optional[str] = None


class StrategyRequest(BaseModel):
    objective: str
    constraints: Dict = Field(default_factory=dict)
    risk_profile: str = "moderate"


class ChatRequest(BaseModel):
    message: str
    context: Optional[str] = None
    department: Optional[str] = None


class LLMResponse(BaseModel):
    success: bool
    content: str
    model: str
    tokens_used: int
    timestamp: str
    provider: str = "unknown"


# ── Provider Callers ─────────────────────────────────────────────
async def call_gemini(prompt: str) -> Dict:
    """Gemini API 호출 (gemini-2.5-flash)"""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set")

    url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": MAX_TOKENS, "temperature": 0.7}
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        total_tokens = data.get("usageMetadata", {}).get("totalTokenCount", 0)
        return {
            "success": True,
            "content": text,
            "model": GEMINI_MODEL,
            "tokens_used": total_tokens,
            "timestamp": datetime.utcnow().isoformat(),
            "provider": "gemini"
        }


async def call_groq(prompt: str) -> Dict:
    """Groq API 호출 (llama-3.1-8b-instant) - 키 로테이션"""
    if not GROQ_KEYS:
        raise ValueError("GROQ_API_KEY not set")

    api_key = random.choice(GROQ_KEYS)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": min(MAX_TOKENS, 8192),
        "temperature": 0.7
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(GROQ_API_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return {
            "success": True,
            "content": text,
            "model": GROQ_MODEL,
            "tokens_used": usage.get("total_tokens", 0),
            "timestamp": datetime.utcnow().isoformat(),
            "provider": "groq"
        }


async def call_kimi(prompt: str) -> Dict:
    """Kimi API 호출 (moonshot-v1-8k)"""
    if not KIMI_API_KEY:
        raise ValueError("KIMI_API_KEY not set")

    headers = {"Authorization": f"Bearer {KIMI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": KIMI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": min(MAX_TOKENS, 8192),
        "temperature": 0.7
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{KIMI_BASE_URL}/chat/completions", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return {
            "success": True,
            "content": text,
            "model": KIMI_MODEL,
            "tokens_used": usage.get("total_tokens", 0),
            "timestamp": datetime.utcnow().isoformat(),
            "provider": "kimi"
        }


async def call_claude(prompt: str, system: Optional[str] = None) -> Dict:
    """Claude API 호출 (premium)"""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": LLM_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}]
    }
    if system:
        payload["system"] = system

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(ANTHROPIC_API_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return {
            "success": True,
            "content": data["content"][0]["text"],
            "model": data["model"],
            "tokens_used": data["usage"]["input_tokens"] + data["usage"]["output_tokens"],
            "timestamp": datetime.utcnow().isoformat(),
            "provider": "claude"
        }


async def call_llm_with_fallback(prompt: str, system: Optional[str] = None) -> Dict:
    """
    멀티 프로바이더 폴백 체인:
    Gemini (paid) → Groq (fast/free) → Kimi → Claude
    """
    providers = []
    if GEMINI_API_KEY:
        providers.append(("gemini", lambda: call_gemini(prompt)))
    if GROQ_KEYS:
        providers.append(("groq", lambda: call_groq(prompt)))
    if KIMI_API_KEY:
        providers.append(("kimi", lambda: call_kimi(prompt)))
    if ANTHROPIC_API_KEY:
        providers.append(("claude", lambda: call_claude(prompt, system)))

    if not providers:
        raise HTTPException(status_code=500, detail="No LLM providers configured")

    last_error = None
    for name, caller in providers:
        try:
            result = await caller()
            logger.info(f"LLM call succeeded via {name}")
            return result
        except Exception as e:
            logger.warning(f"LLM provider {name} failed: {e}")
            last_error = e
            continue

    raise HTTPException(status_code=500, detail=f"All LLM providers failed: {last_error}")


# ── Prompt Formatters ────────────────────────────────────────────
def format_market_prompt(data: MarketDataRequest) -> str:
    prompt = f"""You are an expert quantitative analyst for OZ_A2M trading system.

Analyze the following market data for {data.symbol} on {data.timeframe} timeframe:

Price Data (last 10 candles):
{json.dumps(data.price_data[-10:], indent=2)}

Technical Indicators:
{json.dumps(data.indicators, indent=2)}
"""
    if data.news_context:
        prompt += f"\nMarket Context:\n{data.news_context}\n"

    prompt += """
Provide analysis in JSON format:
- "trend": "bullish" | "bearish" | "neutral"
- "confidence": 0-100
- "key_levels": {"support": [...], "resistance": [...]}
- "recommendation": specific trading recommendation
- "risk_factors": list of key risks
- "time_horizon": "short" | "medium" | "long"

Be concise and data-driven."""
    return prompt


def format_strategy_prompt(req: StrategyRequest) -> str:
    return f"""You are the R&D lead for OZ_A2M automated trading system.

Design a trading strategy:
- Objective: {req.objective}
- Risk Profile: {req.risk_profile}
- Constraints: {json.dumps(req.constraints, indent=2)}

Provide JSON response with: name, description, entry_conditions, exit_conditions,
risk_management, timeframes, indicators, expected_performance."""


def format_chat_prompt(req: ChatRequest) -> str:
    context = f"Department: {req.department}\n" if req.department else ""
    if req.context:
        context += f"Context: {req.context}\n"
    return f"""You are the AI coordinator for OZ_A2M trading system.
{context}User message: {req.message}

Be concise and professional. Emphasize risk management for trading decisions."""


# ── Routes ───────────────────────────────────────────────────────
@router.post("/analyze-market", response_model=LLMResponse)
async def analyze_market(data: MarketDataRequest):
    """시장 데이터 분석 (Gemini → Groq → Kimi → Claude)"""
    logger.info(f"Market analysis: {data.symbol}")
    result = await call_llm_with_fallback(format_market_prompt(data))
    return LLMResponse(**result)


@router.post("/generate-strategy", response_model=LLMResponse)
async def generate_strategy(req: StrategyRequest):
    """트레이딩 전략 생성"""
    logger.info(f"Strategy generation: {req.objective}")
    result = await call_llm_with_fallback(format_strategy_prompt(req))
    return LLMResponse(**result)


@router.post("/chat", response_model=LLMResponse)
async def chat(req: ChatRequest):
    """자연어 대화"""
    logger.info(f"Chat: dept={req.department}")
    system = """You are the AI coordinator for OZ_A2M, a 7-department automated trading system.
Departments: 1=Control Tower, 2=Verification, 3=Security, 4=DevOps, 5=PnL, 6=R&D, 7=Operations.
Always prioritize security and risk management."""
    result = await call_llm_with_fallback(format_chat_prompt(req), system=system)
    return LLMResponse(**result)


@router.get("/status")
async def llm_status():
    """LLM Gateway 프로바이더 상태"""
    available = []
    if GEMINI_API_KEY:
        available.append(f"gemini:{GEMINI_MODEL}")
    if GROQ_KEYS:
        available.append(f"groq:{GROQ_MODEL}(x{len(GROQ_KEYS)}키)")
    if KIMI_API_KEY:
        available.append(f"kimi:{KIMI_MODEL}")
    if ANTHROPIC_API_KEY:
        available.append(f"claude:{LLM_MODEL}")

    return {
        "status": "active" if available else "not_configured",
        "providers": available,
        "primary": available[0] if available else None,
        "fallback_chain": available,
        "max_tokens": MAX_TOKENS,
        "timestamp": datetime.utcnow().isoformat()
    }

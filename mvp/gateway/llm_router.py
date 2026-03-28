"""
OZ_A2M LLM Gateway Router
Claude API 연동 및 LLM 기반 분석 기능
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import httpx
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = structlog.get_logger()

# 설정
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
LLM_MODEL = os.getenv('LLM_MODEL', 'claude-3-5-sonnet-20241022')
MAX_TOKENS = int(os.getenv('LLM_MAX_TOKENS', '4096'))

router = APIRouter(prefix="/llm", tags=["LLM"])


class MarketDataRequest(BaseModel):
    """시장 데이터 분석 요청"""
    symbol: str
    timeframe: str = "1h"
    price_data: List[Dict] = Field(default_factory=list)
    indicators: Dict = Field(default_factory=dict)
    news_context: Optional[str] = None


class StrategyRequest(BaseModel):
    """전략 생성 요청"""
    objective: str
    constraints: Dict = Field(default_factory=dict)
    risk_profile: str = "moderate"  # conservative, moderate, aggressive


class ChatRequest(BaseModel):
    """자연어 대화 요청"""
    message: str
    context: Optional[str] = None
    department: Optional[str] = None


class LLMResponse(BaseModel):
    """LLM 응답"""
    success: bool
    content: str
    model: str
    tokens_used: int
    timestamp: str


def format_market_prompt(data: MarketDataRequest) -> str:
    """시장 데이터 분석용 프롬프트 생성"""
    prompt = f"""You are an expert quantitative analyst for OZ_A2M trading system.

Analyze the following market data for {data.symbol} on {data.timeframe} timeframe:

Price Data (last 10 candles):
{json.dumps(data.price_data[-10:], indent=2)}

Technical Indicators:
{json.dumps(data.indicators, indent=2)}

"""
    if data.news_context:
        prompt += f"""
Market Context/News:
{data.news_context}
"""

    prompt += """
Provide analysis in JSON format with these keys:
- "trend": "bullish" | "bearish" | "neutral"
- "confidence": 0-100 score
- "key_levels": {"support": [...], "resistance": [...]}
- "recommendation": specific trading recommendation
- "risk_factors": list of key risks to watch
- "time_horizon": "short" | "medium" | "long"

Be concise and data-driven."""

    return prompt


def format_strategy_prompt(req: StrategyRequest) -> str:
    """전략 생성용 프롬프트 생성"""
    return f"""You are the R&D team lead for OZ_A2M automated trading system.

Design a trading strategy with the following requirements:
- Objective: {req.objective}
- Risk Profile: {req.risk_profile}
- Constraints: {json.dumps(req.constraints, indent=2)}

Provide the strategy in JSON format:
- "name": strategy name
- "description": brief description
- "entry_conditions": list of specific entry rules
- "exit_conditions": list of specific exit rules (profit/loss)
- "risk_management": {"position_size", "max_drawdown", "stop_loss_rules"}
- "timeframes": recommended timeframes
- "indicators": required technical indicators
- "expected_performance": estimated win rate and risk/reward

Be specific and quantitative."""


def format_chat_prompt(req: ChatRequest) -> str:
    """일반 대화용 프롬프트 생성"""
    context = f"Department: {req.department}\n" if req.department else ""
    if req.context:
        context += f"Context: {req.context}\n"

    return f"""You are the AI assistant for OZ_A2M (AI Agent to Market) trading system.
{context}

User message: {req.message}

Respond as a helpful trading system assistant. Be concise and professional.
If the question involves trading decisions, emphasize risk management and
always suggest consulting the verification department for signal validation."""


async def call_claude_api(prompt: str, system: Optional[str] = None) -> Dict:
    """Claude API 호출"""
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not set")
        raise HTTPException(status_code=500, detail="LLM API key not configured")

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    messages = [{"role": "user", "content": prompt}]

    payload = {
        "model": LLM_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": messages
    }

    if system:
        payload["system"] = system

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                ANTHROPIC_API_URL,
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()

            return {
                "success": True,
                "content": data["content"][0]["text"],
                "model": data["model"],
                "tokens_used": data["usage"]["input_tokens"] + data["usage"]["output_tokens"],
                "timestamp": datetime.utcnow().isoformat()
            }

    except httpx.HTTPStatusError as e:
        logger.error(f"Claude API error: {e.response.status_code}", error=str(e))
        raise HTTPException(status_code=e.response.status_code, detail="LLM API error")
    except Exception as e:
        logger.error(f"Unexpected error calling Claude API: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


@router.post("/analyze-market", response_model=LLMResponse)
async def analyze_market(data: MarketDataRequest):
    """시장 데이터 LLM 분석"""
    logger.info(f"Market analysis requested for {data.symbol}")
    prompt = format_market_prompt(data)
    result = await call_claude_api(prompt)
    return LLMResponse(**result)


@router.post("/generate-strategy", response_model=LLMResponse)
async def generate_strategy(req: StrategyRequest):
    """트레이딩 전략 생성"""
    logger.info(f"Strategy generation requested: {req.objective}")
    prompt = format_strategy_prompt(req)
    result = await call_claude_api(prompt)
    return LLMResponse(**result)


@router.post("/chat", response_model=LLMResponse)
async def chat(req: ChatRequest):
    """자연어 대화"""
    logger.info(f"Chat message from department: {req.department}")
    prompt = format_chat_prompt(req)

    system_prompt = """You are the AI coordinator for OZ_A2M, a 7-department automated trading system.

The system architecture:
- Dept 1: Control Tower (data collection, situation board)
- Dept 2: Verification (signal analysis, noise filtering)
- Dept 3: Security (threat monitoring, audit logging)
- Dept 4: DevOps (health checks, auto-recovery)
- Dept 5: PnL Analysis (daily performance reports)
- Dept 6: R&D (backtesting, strategy generation)
- Dept 7: Operations (trade execution, scalping bots)

Always prioritize security and risk management."""

    result = await call_claude_api(prompt, system=system_prompt)
    return LLMResponse(**result)


@router.get("/status")
async def llm_status():
    """LLM Gateway 상태"""
    return {
        "status": "active" if ANTHROPIC_API_KEY else "not_configured",
        "model": LLM_MODEL,
        "max_tokens": MAX_TOKENS,
        "timestamp": datetime.utcnow().isoformat()
    }

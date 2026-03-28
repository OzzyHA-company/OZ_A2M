"""
LLM Gateway - AI 모델 라우팅 및 관리
Phase 7 핵심 컴포넌트
"""

import asyncio
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from enum import Enum

import httpx
from cachetools import TTLCache
from pydantic import BaseModel, Field

from occore.logger import get_logger

logger = get_logger(__name__)


class LLMState(str, Enum):
    """LLM 상태 정의 (간소화된 2상태)"""
    OK = "ok"
    ERROR = "error"


class LLMProvider(BaseModel):
    """LLM 제공자 설정"""
    name: str
    url: str
    model: str
    state: LLMState = LLMState.OK
    priority: int = 1  # 낮을수록 높은 우선순위
    last_error: Optional[datetime] = None
    error_count: int = 0
    max_errors: int = 3
    timeout: float = 30.0


class LLMRequest(BaseModel):
    """LLM 요청 모델"""
    task: str = Field(..., description="작업 유형: analysis, complex, quick, cost_sensitive")
    prompt: str
    stream: bool = False
    temperature: float = 0.7
    max_tokens: Optional[int] = None


class LLMResponse(BaseModel):
    """LLM 응답 모델"""
    provider: str
    model: str
    content: str
    latency_ms: float
    cached: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class LLMGateway:
    """
    LLM Gateway - 스마트 라우팅 및 폴�택

    기능:
    - 작업 유형별 라우팅
    - 자동 폴�택
    - 응답 캐싱
    - 상태 모니터링
    """

    # 작업별 선호 제공자
    TASK_ROUTING = {
        "analysis": ["gemini", "ollama"],
        "complex": ["gemini", "ollama"],
        "quick": ["ollama"],
        "cost_sensitive": ["ollama", "gemini"],
        "trading_signal": ["ollama"],  # 빠른 응답 필요
        "market_analysis": ["gemini"],  # 고품질 분석
    }

    def __init__(self):
        self.providers: Dict[str, LLMProvider] = {}
        self.cache: TTLCache = TTLCache(maxsize=1000, ttl=300)  # 5분 캐시
        self._setup_default_providers()
        logger.info("LLM Gateway initialized")

    def _setup_default_providers(self):
        """기본 제공자 설정"""
        # Ollama (로컬)
        self.register_provider(LLMProvider(
            name="ollama",
            url="http://localhost:11434/api/generate",
            model="llama3.2",
            priority=1,  # 기본값
        ))

        # Gemini API
        self.register_provider(LLMProvider(
            name="gemini",
            url="https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent",
            model="gemini-pro",
            priority=2,
        ))

    def register_provider(self, provider: LLMProvider):
        """제공자 등록"""
        self.providers[provider.name] = provider
        logger.info(f"Registered LLM provider: {provider.name}")

    def get_provider(self, name: str) -> Optional[LLMProvider]:
        """제공자 조회"""
        return self.providers.get(name)

    def select_provider(self, task: str) -> Optional[LLMProvider]:
        """
        작업 유형에 맞는 제공자 선택

        우선순위:
        1. 작업 유형별 선호 순서
        2. 상태 OK인 제공자
        3. 우선순위 값
        """
        preferred = self.TASK_ROUTING.get(task, ["ollama", "gemini"])

        for provider_name in preferred:
            provider = self.providers.get(provider_name)
            if provider and provider.state == LLMState.OK:
                return provider

        # 모든 선호 제공자가 다운인 경우, 사용 가능한 제공자 반환
        available = [p for p in self.providers.values() if p.state == LLMState.OK]
        if available:
            return min(available, key=lambda p: p.priority)

        return None

    def _generate_cache_key(self, task: str, prompt: str) -> str:
        """캐시 키 생성"""
        import hashlib
        content = f"{task}:{prompt}"
        return hashlib.md5(content.encode()).hexdigest()

    async def generate(
        self,
        request: LLMRequest,
        force_provider: Optional[str] = None
    ) -> LLMResponse:
        """
        LLM 생성 요청 처리

        Args:
            request: LLM 요청
            force_provider: 강제로 사용할 제공자 (선택)

        Returns:
            LLM 응답
        """
        start_time = asyncio.get_event_loop().time()

        # 캐시 확인
        cache_key = self._generate_cache_key(request.task, request.prompt)
        if cache_key in self.cache:
            cached = self.cache[cache_key]
            latency = (asyncio.get_event_loop().time() - start_time) * 1000
            return LLMResponse(
                provider=cached["provider"],
                model=cached["model"],
                content=cached["content"],
                latency_ms=latency,
                cached=True
            )

        # 제공자 선택
        if force_provider:
            provider = self.providers.get(force_provider)
            if not provider:
                raise ValueError(f"Unknown provider: {force_provider}")
        else:
            provider = self.select_provider(request.task)
            if not provider:
                raise RuntimeError("No available LLM providers")

        # 요청 실행
        try:
            if provider.name == "ollama":
                response = await self._call_ollama(provider, request)
            elif provider.name == "gemini":
                response = await self._call_gemini(provider, request)
            else:
                raise ValueError(f"Unsupported provider: {provider.name}")

            # 성공 시 에러 카운트 리셋
            provider.error_count = 0

            # 캐시 저장
            self.cache[cache_key] = {
                "provider": provider.name,
                "model": provider.model,
                "content": response
            }

            latency = (asyncio.get_event_loop().time() - start_time) * 1000

            return LLMResponse(
                provider=provider.name,
                model=provider.model,
                content=response,
                latency_ms=latency
            )

        except Exception as e:
            provider.error_count += 1
            provider.last_error = datetime.utcnow()

            if provider.error_count >= provider.max_errors:
                provider.state = LLMState.ERROR
                logger.error(f"Provider {provider.name} marked as ERROR after {provider.error_count} failures")

            logger.error(f"LLM request failed for {provider.name}: {e}")

            # 폴�택
            fallback = self._get_fallback_provider(provider.name)
            if fallback:
                logger.info(f"Falling back to {fallback.name}")
                return await self.generate(request, force_provider=fallback.name)

            raise

    def _get_fallback_provider(self, exclude_name: str) -> Optional[LLMProvider]:
        """폴�택 제공자 선택"""
        available = [
            p for p in self.providers.values()
            if p.name != exclude_name and p.state == LLMState.OK
        ]
        if available:
            return min(available, key=lambda p: p.priority)
        return None

    async def _call_ollama(self, provider: LLMProvider, request: LLMRequest) -> str:
        """Ollama API 호출"""
        async with httpx.AsyncClient(timeout=provider.timeout) as client:
            payload = {
                "model": provider.model,
                "prompt": request.prompt,
                "stream": False,
                "options": {
                    "temperature": request.temperature,
                }
            }
            if request.max_tokens:
                payload["options"]["num_predict"] = request.max_tokens

            response = await client.post(provider.url, json=payload)
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")

    async def _call_gemini(self, provider: LLMProvider, request: LLMRequest) -> str:
        """Gemini API 호출"""
        import os
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")

        async with httpx.AsyncClient(timeout=provider.timeout) as client:
            url = f"{provider.url}?key={api_key}"
            payload = {
                "contents": [{
                    "parts": [{"text": request.prompt}]
                }],
                "generationConfig": {
                    "temperature": request.temperature,
                }
            }
            if request.max_tokens:
                payload["generationConfig"]["maxOutputTokens"] = request.max_tokens

            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            # Gemini 응답 파싱
            candidates = data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    return parts[0].get("text", "")

            return ""

    def get_health(self) -> Dict[str, Any]:
        """전체 상태 반환"""
        return {
            name: {
                "state": p.state.value,
                "priority": p.priority,
                "error_count": p.error_count,
                "last_error": p.last_error.isoformat() if p.last_error else None
            }
            for name, p in self.providers.items()
        }

    async def recover_provider(self, name: str):
        """제공자 복구 시도"""
        provider = self.providers.get(name)
        if not provider:
            return False

        try:
            # 간단한 헬스 체크
            test_request = LLMRequest(task="quick", prompt="test", max_tokens=10)
            if provider.name == "ollama":
                await self._call_ollama(provider, test_request)
            elif provider.name == "gemini":
                await self._call_gemini(provider, test_request)

            provider.state = LLMState.OK
            provider.error_count = 0
            provider.last_error = None
            logger.info(f"Provider {name} recovered")
            return True

        except Exception as e:
            logger.warning(f"Provider {name} recovery failed: {e}")
            return False


# 싱글톤 인스턴스
_llm_gateway: Optional[LLMGateway] = None


def get_llm_gateway() -> LLMGateway:
    """LLM Gateway 싱글톤 반환"""
    global _llm_gateway
    if _llm_gateway is None:
        _llm_gateway = LLMGateway()
    return _llm_gateway


async def generate_text(
    prompt: str,
    task: str = "quick",
    stream: bool = False
) -> str:
    """간편 텍스트 생성 함수"""
    gateway = get_llm_gateway()
    request = LLMRequest(task=task, prompt=prompt, stream=stream)
    response = await gateway.generate(request)
    return response.content
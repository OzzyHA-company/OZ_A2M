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

from lib.core.logger import get_logger

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


class LLMRole(str, Enum):
    """LLM 역할 유형"""
    MARKET_ANALYSIS = "market_analysis"      # 시장 분석 → [Gemini, Ollama]
    COMPLEX_REASONING = "complex_reasoning"  # 복잡 추론 → [Claude, OpenAI] (키 필요)
    QUICK_RESPONSE = "quick_response"        # 빠른 응답 → [Ollama]
    COST_SENSITIVE = "cost_sensitive"        # 비용 민감 → [Ollama, Gemini]
    TRADING_SIGNAL = "trading_signal"        # 매매 신호 → [Ollama]
    CODE_GENERATION = "code_generation"      # 코드 생성 → [Claude, Gemini]
    SUMMARIZATION = "summarization"          # 요약 → [Ollama, Gemini]


class CacheMetrics:
    """캐시 메트릭스"""
    def __init__(self):
        self.hits: int = 0
        self.misses: int = 0
        self.total_requests: int = 0

    @property
    def hit_rate(self) -> float:
        """캐시 히트율"""
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests

    def record_hit(self):
        """히트 기록"""
        self.hits += 1
        self.total_requests += 1

    def record_miss(self):
        """미스 기록"""
        self.misses += 1
        self.total_requests += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "total_requests": self.total_requests,
            "hit_rate": self.hit_rate,
        }


class LLMGateway:
    """
    LLM Gateway - 스마트 라우팅 및 폴�택

    기능:
    - 역할 기반 라우팅
    - 자동 폴�택
    - 응답 캐싱 (히트율 메트릭스)
    - 상태 모니터링
    """

    # 역할별 선호 제공자 (우선순위 순)
    ROLE_ROUTING: Dict[LLMRole, List[str]] = {
        LLMRole.MARKET_ANALYSIS: ["gemini", "ollama"],
        LLMRole.COMPLEX_REASONING: ["claude", "openai", "gemini", "ollama"],
        LLMRole.QUICK_RESPONSE: ["ollama", "gemini"],
        LLMRole.COST_SENSITIVE: ["ollama", "gemini"],
        LLMRole.TRADING_SIGNAL: ["ollama"],  # 빠른 응답 필요
        LLMRole.CODE_GENERATION: ["claude", "gemini", "ollama"],
        LLMRole.SUMMARIZATION: ["ollama", "gemini"],
    }

    # 레거시 작업별 라우팅 (하위 호환)
    TASK_ROUTING = {
        "analysis": ["gemini", "ollama"],
        "complex": ["gemini", "ollama"],
        "quick": ["ollama"],
        "cost_sensitive": ["ollama", "gemini"],
        "trading_signal": ["ollama"],
        "market_analysis": ["gemini"],
    }

    def __init__(self):
        self.providers: Dict[str, LLMProvider] = {}
        self.cache: TTLCache = TTLCache(maxsize=1000, ttl=300)  # 5분 캐시
        self.cache_metrics = CacheMetrics()
        self._setup_default_providers()
        self._setup_optional_providers()
        logger.info("LLM Gateway initialized")
        logger.info(f"Cache metrics enabled: hit_rate tracking active")

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

    def _setup_optional_providers(self):
        """
        선택적 제공자 설정 (API 키 필요)

        ⚠️ 사용자 승인 필요: 실제 API 키 입력 시 활성화
        """
        import os

        # OpenAI (API 키 필요)
        if os.getenv("OPENAI_API_KEY"):
            try:
                self.register_provider(LLMProvider(
                    name="openai",
                    url="https://api.openai.com/v1/chat/completions",
                    model="gpt-4",
                    priority=2,
                ))
                logger.info("OpenAI provider registered (API key found)")
            except Exception as e:
                logger.warning(f"Failed to register OpenAI provider: {e}")
        else:
            logger.info("OpenAI provider not registered (API key not set)")

        # Claude (API 키 필요)
        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                self.register_provider(LLMProvider(
                    name="claude",
                    url="https://api.anthropic.com/v1/messages",
                    model="claude-3-sonnet-20240229",
                    priority=1,  # 높은 우선순위
                ))
                logger.info("Claude provider registered (API key found)")
            except Exception as e:
                logger.warning(f"Failed to register Claude provider: {e}")
        else:
            logger.info("Claude provider not registered (API key not set)")

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

    def select_provider_by_role(self, role: LLMRole) -> Optional[LLMProvider]:
        """
        역할 기반 제공자 선택

        Args:
            role: LLM 역할 유형

        Returns:
            선택된 제공자 또는 None
        """
        preferred = self.ROLE_ROUTING.get(role, ["ollama", "gemini"])

        for provider_name in preferred:
            provider = self.providers.get(provider_name)
            if provider and provider.state == LLMState.OK:
                logger.debug(f"Selected provider {provider_name} for role {role.value}")
                return provider

        # 모든 선호 제공자가 다운인 경우, 사용 가능한 제공자 반환
        available = [p for p in self.providers.values() if p.state == LLMState.OK]
        if available:
            fallback = min(available, key=lambda p: p.priority)
            logger.warning(
                f"No preferred provider for role {role.value}, "
                f"falling back to {fallback.name}"
            )
            return fallback

        logger.error(f"No available providers for role {role.value}")
        return None

    def get_cache_metrics(self) -> Dict[str, Any]:
        """캐시 메트릭스 조회"""
        return self.cache_metrics.to_dict()

    def reset_cache_metrics(self):
        """캐시 메트릭스 리셋"""
        self.cache_metrics = CacheMetrics()
        logger.info("Cache metrics reset")

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
            self.cache_metrics.record_hit()  # 캐시 히트 기록
            logger.debug(f"Cache hit for {request.task} (hit_rate: {self.cache_metrics.hit_rate:.2%})")
            return LLMResponse(
                provider=cached["provider"],
                model=cached["model"],
                content=cached["content"],
                latency_ms=latency,
                cached=True
            )

        self.cache_metrics.record_miss()  # 캐시 미스 기록

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
            elif provider.name == "openai":
                response = await self._call_openai(provider, request)
            elif provider.name == "claude":
                response = await self._call_claude(provider, request)
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

    async def _call_openai(self, provider: LLMProvider, request: LLMRequest) -> str:
        """OpenAI API 호출"""
        import os
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")

        async with httpx.AsyncClient(timeout=provider.timeout) as client:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": provider.model,
                "messages": [{"role": "user", "content": request.prompt}],
                "temperature": request.temperature,
            }
            if request.max_tokens:
                payload["max_tokens"] = request.max_tokens

            response = await client.post(
                provider.url,
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()

            # OpenAI 응답 파싱
            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                return message.get("content", "")

            return ""

    async def _call_claude(self, provider: LLMProvider, request: LLMRequest) -> str:
        """Claude API 호출"""
        import os
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")

        async with httpx.AsyncClient(timeout=provider.timeout) as client:
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            payload = {
                "model": provider.model,
                "messages": [{"role": "user", "content": request.prompt}],
                "max_tokens": request.max_tokens or 1024,
                "temperature": request.temperature,
            }

            response = await client.post(
                provider.url,
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()

            # Claude 응답 파싱
            content = data.get("content", [])
            if content:
                return content[0].get("text", "")

            return ""

    def get_health(self) -> Dict[str, Any]:
        """전체 상태 반환 (캐시 메트릭스 포함)"""
        return {
            "providers": {
                name: {
                    "state": p.state.value,
                    "priority": p.priority,
                    "error_count": p.error_count,
                    "last_error": p.last_error.isoformat() if p.last_error else None
                }
                for name, p in self.providers.items()
            },
            "cache": self.get_cache_metrics(),
            "routing": {
                "available_roles": [r.value for r in LLMRole],
                "role_routing": {
                    r.value: providers
                    for r, providers in self.ROLE_ROUTING.items()
                },
            },
        }

    async def recover_provider(self, name: str) -> bool:
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
            elif provider.name == "openai":
                await self._call_openai(provider, test_request)
            elif provider.name == "claude":
                await self._call_claude(provider, test_request)

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
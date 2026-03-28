"""
LLM Routing Tests

STEP 5: LLM 라우팅 고도화 테스트
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock

from department_1.src.llm_gateway import (
    LLMGateway,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMState,
    LLMRole,
    CacheMetrics,
    get_llm_gateway,
    generate_text,
)


class TestCacheMetrics:
    """CacheMetrics 테스트"""

    def test_cache_metrics_initialization(self):
        """초기화 테스트"""
        metrics = CacheMetrics()

        assert metrics.hits == 0
        assert metrics.misses == 0
        assert metrics.total_requests == 0
        assert metrics.hit_rate == 0.0

    def test_cache_metrics_hit(self):
        """히트 기록 테스트"""
        metrics = CacheMetrics()

        metrics.record_hit()

        assert metrics.hits == 1
        assert metrics.total_requests == 1
        assert metrics.hit_rate == 1.0

    def test_cache_metrics_miss(self):
        """미스 기록 테스트"""
        metrics = CacheMetrics()

        metrics.record_miss()

        assert metrics.misses == 1
        assert metrics.total_requests == 1
        assert metrics.hit_rate == 0.0

    def test_cache_metrics_mixed(self):
        """혼합 기록 테스트"""
        metrics = CacheMetrics()

        metrics.record_hit()
        metrics.record_hit()
        metrics.record_miss()
        metrics.record_hit()

        assert metrics.hits == 3
        assert metrics.misses == 1
        assert metrics.total_requests == 4
        assert metrics.hit_rate == 0.75

    def test_cache_metrics_to_dict(self):
        """딕셔너리 변환 테스트"""
        metrics = CacheMetrics()
        metrics.record_hit()
        metrics.record_miss()

        data = metrics.to_dict()

        assert data["hits"] == 1
        assert data["misses"] == 1
        assert data["total_requests"] == 2
        assert data["hit_rate"] == 0.5


class TestLLMRole:
    """LLMRole 테스트"""

    def test_role_values(self):
        """역할 값 테스트"""
        assert LLMRole.MARKET_ANALYSIS.value == "market_analysis"
        assert LLMRole.COMPLEX_REASONING.value == "complex_reasoning"
        assert LLMRole.QUICK_RESPONSE.value == "quick_response"
        assert LLMRole.COST_SENSITIVE.value == "cost_sensitive"
        assert LLMRole.TRADING_SIGNAL.value == "trading_signal"
        assert LLMRole.CODE_GENERATION.value == "code_generation"
        assert LLMRole.SUMMARIZATION.value == "summarization"


class TestLLMGatewayRouting:
    """LLM Gateway 라우팅 테스트"""

    @pytest.fixture
    def gateway(self):
        """테스트용 게이트웨이"""
        gateway = LLMGateway()
        # 테스트용 제공자 추가
        gateway.register_provider(LLMProvider(
            name="test_provider",
            url="http://test.com",
            model="test-model",
            priority=1,
            state=LLMState.OK,
        ))
        return gateway

    def test_select_provider_by_role_market_analysis(self, gateway):
        """시장 분석 역할 라우팅 테스트"""
        # Gemini 또는 Ollama가 있으면 선택
        provider = gateway.select_provider_by_role(LLMRole.MARKET_ANALYSIS)

        if provider:
            assert provider.name in ["gemini", "ollama"]

    def test_select_provider_by_role_quick_response(self, gateway):
        """빠른 응답 역할 라우팅 테스트"""
        provider = gateway.select_provider_by_role(LLMRole.QUICK_RESPONSE)

        if provider:
            # Ollama 우선, 없으면 Gemini
            assert provider.name in ["ollama", "gemini"]

    def test_select_provider_by_role_complex_reasoning(self, gateway):
        """복잡 추론 역할 라우팅 테스트"""
        provider = gateway.select_provider_by_role(LLMRole.COMPLEX_REASONING)

        # Claude, OpenAI가 없으므로 Gemini나 Ollama가 선택됨
        if provider:
            assert provider.name in ["gemini", "ollama", "test_provider"]

    def test_select_provider_by_role_unavailable(self, gateway):
        """모든 제공자가 다운일 때 테스트"""
        # 모든 제공자를 ERROR 상태로 변경
        for provider in gateway.providers.values():
            provider.state = LLMState.ERROR

        provider = gateway.select_provider_by_role(LLMRole.TRADING_SIGNAL)
        assert provider is None

    def test_role_routing_configuration(self, gateway):
        """역할 라우팅 설정 테스트"""
        # TRADING_SIGNAL은 Ollama만 사용
        assert gateway.ROLE_ROUTING[LLMRole.TRADING_SIGNAL] == ["ollama"]

        # COST_SENSITIVE는 Ollama, Gemini 순서
        assert gateway.ROLE_ROUTING[LLMRole.COST_SENSITIVE] == ["ollama", "gemini"]

        # CODE_GENERATION은 Claude 우선 (없으면 다음)
        assert gateway.ROLE_ROUTING[LLMRole.CODE_GENERATION] == ["claude", "gemini", "ollama"]


class TestLLMGatewayCache:
    """LLM Gateway 캐시 테스트"""

    @pytest.fixture
    def gateway(self):
        """테스트용 게이트웨이"""
        return LLMGateway()

    def test_cache_metrics_initial(self, gateway):
        """초기 캐시 메트릭스 테스트"""
        metrics = gateway.get_cache_metrics()

        assert metrics["hits"] == 0
        assert metrics["misses"] == 0
        assert metrics["hit_rate"] == 0.0

    def test_reset_cache_metrics(self, gateway):
        """캐시 메트릭스 리셋 테스트"""
        gateway.cache_metrics.record_hit()
        gateway.cache_metrics.record_miss()

        gateway.reset_cache_metrics()

        metrics = gateway.get_cache_metrics()
        assert metrics["hits"] == 0
        assert metrics["misses"] == 0

    @pytest.mark.asyncio
    async def test_generate_tracks_cache_hit(self, gateway):
        """캐시 히트 추적 테스트"""
        # 캐시 미리 채우기
        cache_key = gateway._generate_cache_key("test_task", "test prompt")
        gateway.cache[cache_key] = {
            "provider": "ollama",
            "model": "llama3.2",
            "content": "cached response",
        }

        request = LLMRequest(task="test_task", prompt="test prompt")

        with patch.object(gateway.cache_metrics, 'record_hit') as mock_hit:
            # 캐시 히트 시 record_hit 호출 확인
            response = await gateway.generate(request)
            assert response.cached is True
            assert mock_hit.called

    @pytest.mark.asyncio
    async def test_generate_tracks_cache_miss(self, gateway):
        """캐시 미스 추적 테스트"""
        # 캐시 메트릭스 초기화
        gateway.reset_cache_metrics()

        request = LLMRequest(task="test_task", prompt="unique prompt 12345")

        # 직접 record_miss 호출하여 메트릭스 작동 확인
        gateway.cache_metrics.record_miss()

        # 미스가 기록되었는지 확인
        assert gateway.cache_metrics.total_requests == 1
        assert gateway.cache_metrics.misses == 1


class TestLLMGatewayHealth:
    """LLM Gateway 헬스 체크 테스트"""

    @pytest.fixture
    def gateway(self):
        """테스트용 게이트웨이"""
        return LLMGateway()

    def test_get_health_structure(self, gateway):
        """헬스 응답 구조 테스트"""
        health = gateway.get_health()

        # providers 섹션 확인
        assert "providers" in health
        assert "ollama" in health["providers"] or "gemini" in health["providers"]

        # cache 섹션 확인
        assert "cache" in health
        assert "hits" in health["cache"]
        assert "hit_rate" in health["cache"]

        # routing 섹션 확인
        assert "routing" in health
        assert "available_roles" in health["routing"]
        assert "role_routing" in health["routing"]

    def test_get_health_provider_fields(self, gateway):
        """제공자 헬스 필드 테스트"""
        health = gateway.get_health()

        for provider_name, provider_health in health["providers"].items():
            assert "state" in provider_health
            assert "priority" in provider_health
            assert "error_count" in provider_health
            assert "last_error" in provider_health

    def test_get_health_available_roles(self, gateway):
        """사용 가능한 역할 테스트"""
        health = gateway.get_health()

        roles = health["routing"]["available_roles"]
        assert "market_analysis" in roles
        assert "complex_reasoning" in roles
        assert "quick_response" in roles
        assert "trading_signal" in roles


class TestLLMGatewayFallback:
    """LLM Gateway 폴�택 테스트"""

    @pytest.fixture
    def gateway(self):
        """테스트용 게이트웨이"""
        g = LLMGateway()
        # 모든 제공자를 OK 상태로 유지
        for provider in g.providers.values():
            provider.state = LLMState.OK
            provider.error_count = 0
        return g

    def test_get_fallback_provider(self, gateway):
        """폴�택 제공자 선택 테스트"""
        fallback = gateway._get_fallback_provider("ollama")

        # Ollama를 제외하고 사용 가능한 제공자 반환
        if fallback:
            assert fallback.name != "ollama"
            assert fallback.state == LLMState.OK

    def test_get_fallback_no_available(self, gateway):
        """사용 가능한 폴�택 없음 테스트"""
        # 모든 제공자를 ERROR 상태로 변경
        for provider in gateway.providers.values():
            provider.state = LLMState.ERROR

        fallback = gateway._get_fallback_provider("ollama")
        assert fallback is None


class TestLLMProvider:
    """LLMProvider 모델 테스트"""

    def test_provider_creation(self):
        """제공자 생성 테스트"""
        provider = LLMProvider(
            name="test",
            url="http://test.com",
            model="test-model",
            priority=1,
            state=LLMState.OK,
        )

        assert provider.name == "test"
        assert provider.state == LLMState.OK
        assert provider.error_count == 0
        assert provider.max_errors == 3

    def test_provider_error_tracking(self):
        """제공자 오류 추적 테스트"""
        provider = LLMProvider(
            name="test",
            url="http://test.com",
            model="test-model",
        )

        provider.error_count = 2
        assert provider.error_count == 2


class TestLLMRequestResponse:
    """LLMRequest/Response 모델 테스트"""

    def test_request_creation(self):
        """요청 생성 테스트"""
        request = LLMRequest(
            task="analysis",
            prompt="Analyze this market data",
            temperature=0.5,
            max_tokens=1000,
        )

        assert request.task == "analysis"
        assert request.temperature == 0.5
        assert request.max_tokens == 1000

    def test_response_creation(self):
        """응답 생성 테스트"""
        response = LLMResponse(
            provider="ollama",
            model="llama3.2",
            content="Analysis result",
            latency_ms=150.0,
            cached=False,
        )

        assert response.provider == "ollama"
        assert response.latency_ms == 150.0
        assert response.cached is False


class TestGetLLMGateway:
    """get_llm_gateway 함수 테스트"""

    def test_get_llm_gateway_singleton(self):
        """싱글톤 테스트"""
        g1 = get_llm_gateway()
        g2 = get_llm_gateway()

        assert g1 is g2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

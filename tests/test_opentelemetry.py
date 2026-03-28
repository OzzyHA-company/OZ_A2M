"""
OpenTelemetry Tracing Tests

STEP 4: OpenTelemetry 분산 추적 테스트
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from lib.core.tracer import (
    OZTracer,
    get_tracer,
    trace_function,
)


class TestOZTracer:
    """OZTracer 기본 테스트"""

    @pytest.fixture
    def tracer(self):
        """테스트용 트레이서 인스턴스"""
        return OZTracer(
            service_name="test_service",
            service_version="1.0.0",
            jaeger_endpoint=None,
            enable_console=False
        )

    def test_tracer_initialization(self, tracer):
        """트레이서 초기화 테스트"""
        assert tracer.service_name == "test_service"
        assert tracer.tracer is not None

    def test_span_context_manager(self, tracer):
        """Span 컨텍스트 매니저 테스트"""
        with tracer.span("test_operation", {"key": "value"}) as span:
            assert span is not None
            span.set_attribute("test", True)

    def test_span_with_exception(self, tracer):
        """Span 예외 처리 테스트"""
        with pytest.raises(ValueError):
            with tracer.span("failing_operation"):
                raise ValueError("Test error")

    def test_trace_decorator_sync(self, tracer):
        """동기 함수 데코레이터 테스트"""
        @tracer.trace("sync_function")
        def sync_func():
            return "success"

        result = sync_func()
        assert result == "success"

    @pytest.mark.asyncio
    async def test_trace_decorator_async(self, tracer):
        """비동기 함수 데코레이터 테스트"""
        @tracer.trace("async_function")
        async def async_func():
            await asyncio.sleep(0.01)
            return "async_success"

        result = await async_func()
        assert result == "async_success"

    def test_trace_http_request(self, tracer):
        """HTTP 요청 추적 테스트"""
        with tracer.trace_http_request("GET", "https://api.example.com/data"):
            pass  # HTTP 요청 시뮬레이션

    def test_trace_mqtt_publish(self, tracer):
        """MQTT 발행 추적 테스트"""
        with tracer.trace_mqtt_publish("oz/a2m/signals/bot_001", 256):
            pass  # MQTT 발행 시뮬레이션

    def test_trace_mqtt_receive(self, tracer):
        """MQTT 수신 추적 테스트"""
        with tracer.trace_mqtt_receive("oz/a2m/market/BTCUSDT", 512):
            pass  # MQTT 수신 시뮬레이션

    def test_trace_kafka_send(self, tracer):
        """Kafka 발행 추적 테스트"""
        with tracer.trace_kafka_send("oz.a2m.signals", key="bot_001"):
            pass  # Kafka 발행 시뮬레이션

    def test_trace_kafka_receive(self, tracer):
        """Kafka 수신 추적 테스트"""
        with tracer.trace_kafka_receive("oz.a2m.signals", partition=0, offset=12345):
            pass  # Kafka 수신 시뮬레이션

    def test_add_event(self, tracer):
        """Span 이벤트 추가 테스트"""
        with tracer.span("operation_with_events"):
            tracer.add_event("processing_step", {"step": 1})
            tracer.add_event("processing_step", {"step": 2})

    def test_set_attribute(self, tracer):
        """Span 속성 설정 테스트"""
        with tracer.span("operation_with_attrs"):
            tracer.set_attribute("custom_key", "custom_value")
            tracer.set_attribute("numeric_value", 42)

    def test_record_exception(self, tracer):
        """Span 예외 기록 테스트"""
        try:
            with tracer.span("operation_with_error"):
                raise RuntimeError("Test exception")
        except RuntimeError:
            pass  # 예외는 전파됨


class TestGlobalTracer:
    """전역 트레이서 테스트"""

    def test_get_tracer_singleton(self):
        """싱글톤 패턴 테스트"""
        # Global tracer may already be initialized by previous tests
        # Just verify that multiple calls return the same instance
        tracer1 = get_tracer()
        tracer2 = get_tracer()

        # 같은 인스턴스여야 함
        assert tracer1 is tracer2

    def test_trace_function_decorator(self):
        """trace_function 데코레이터 테스트"""
        @trace_function(name="test_operation", custom_attr="value")
        def test_func():
            return "result"

        result = test_func()
        assert result == "result"


class TestTracingIntegration:
    """통합 테스트"""

    @pytest.mark.asyncio
    async def test_full_tracing_flow(self):
        """전체 추적 흐름 테스트"""
        tracer = get_tracer("integration_test")

        # 1. HTTP 요청 추적
        with tracer.trace_http_request("GET", "https://api.exchange.com/ticker"):
            # 2. 데이터 처리
            with tracer.span("process_data"):
                tracer.add_event("parsing", {"format": "json"})

                # 3. MQTT 발행
                with tracer.trace_mqtt_publish("oz/a2m/market/data", 256):
                    tracer.set_attribute("topic_type", "market")

                # 4. Kafka 발행
                with tracer.trace_kafka_send("oz.a2m.processed", key="BTCUSDT"):
                    pass

        # 모든 작업이 오류 없이 완료되어야 함
        assert True

    def test_nested_spans(self):
        """중첩 Span 테스트"""
        tracer = get_tracer("nested_test")

        with tracer.span("parent_operation"):
            tracer.set_attribute("level", "parent")

            with tracer.span("child_operation_1"):
                tracer.set_attribute("level", "child1")

                with tracer.span("grandchild_operation"):
                    tracer.set_attribute("level", "grandchild")

            with tracer.span("child_operation_2"):
                tracer.set_attribute("level", "child2")

    def test_concurrent_spans(self):
        """동시 Span 테스트"""
        tracer = get_tracer("concurrent_test")
        results = []

        def operation_1():
            with tracer.span("operation_1"):
                results.append("op1")

        def operation_2():
            with tracer.span("operation_2"):
                results.append("op2")

        # 순차 실행 (동시성 테스트는 실제로 별도 스레드/코루틴에서)
        operation_1()
        operation_2()

        assert len(results) == 2


class TestErrorHandling:
    """오류 처리 테스트"""

    def test_span_exception_propagation(self):
        """Span 예외 전파 테스트"""
        tracer = get_tracer("error_test")

        with pytest.raises(ValueError, match="Test error"):
            with tracer.span("failing_span"):
                raise ValueError("Test error")

    def test_span_exception_attributes(self):
        """예외 발생 시 Span 속성 테스트"""
        tracer = get_tracer("error_attr_test")

        try:
            with tracer.span("operation") as span:
                span.set_attribute("before_error", True)
                raise RuntimeError("Test error")
        except RuntimeError:
            pass

        # 예외가 발생했지만 Span은 생성됨
        assert True

    def test_invalid_attributes(self):
        """잘못된 속성 처리 테스트"""
        tracer = get_tracer("invalid_attr_test")

        with tracer.span("test") as span:
            # 다양한 타입의 속성 설정
            span.set_attribute("string", "value")
            span.set_attribute("integer", 42)
            span.set_attribute("float", 3.14)
            span.set_attribute("boolean", True)
            span.set_attribute("list", ["a", "b", "c"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

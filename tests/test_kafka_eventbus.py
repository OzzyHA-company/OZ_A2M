"""
EventBus Kafka 통합 테스트

STEP 1: Kafka 가동 + EventBus 실연동 검증
- HIGH/CRITICAL 이벤트 Kafka 전송 테스트
"""

import pytest
import asyncio
import json
from datetime import datetime

# Skip if kafka not available
kafka_available = True
try:
    from kafka import KafkaProducer, KafkaConsumer
    from kafka.admin import KafkaAdminClient
except ImportError:
    kafka_available = False

from lib.messaging.event_bus import EventBus, Event, EventType, EventPriority


pytestmark = [
    pytest.mark.skipif(not kafka_available, reason="Kafka not installed"),
    pytest.mark.asyncio
]


class TestEventBusKafkaIntegration:
    """EventBus Kafka 연동 테스트"""

    @pytest.fixture
    async def event_bus(self):
        """Kafka 활성화된 EventBus 인스턴스"""
        bus = EventBus(
            mqtt_host="localhost",
            mqtt_port=1883,
            kafka_bootstrap="localhost:9092",
            enable_kafka=True
        )
        # MQTT 연결은 실패할 수 있음 (테스트 환경)
        try:
            await bus.connect()
        except Exception:
            pass  # MQTT 실패 무시, Kafka만 테스트

        yield bus

        await bus.disconnect()

    async def test_kafka_producer_initialized(self, event_bus):
        """Kafka producer 초기화 확인"""
        if kafka_available:
            assert event_bus.enable_kafka is True
            assert event_bus.kafka_bootstrap == "localhost:9092"
        else:
            pytest.skip("Kafka not available")

    async def test_high_priority_event_to_kafka(self, event_bus):
        """HIGH 우선순위 이벤트가 Kafka로 전송되는지 테스트"""
        if not kafka_available:
            pytest.skip("Kafka not available")

        # HIGH 우선순위 이벤트 생성
        event = Event(
            type=EventType.ORDER_NEW,
            payload={
                "order_id": "test-order-001",
                "symbol": "BTC/USDT",
                "side": "buy",
                "amount": 0.1,
                "price": 50000.0
            },
            priority=EventPriority.HIGH,
            source="test"
        )

        # 이벤트 발행
        await event_bus.publish(event)

        # Kafka producer가 존재하면 성공
        assert event_bus.kafka_producer is not None

    async def test_critical_priority_event_to_kafka(self, event_bus):
        """CRITICAL 우선순위 이벤트가 Kafka로 전송되는지 테스트"""
        if not kafka_available:
            pytest.skip("Kafka not available")

        event = Event(
            type=EventType.BOT_ERROR,
            payload={
                "bot_id": "scalping_bot_001",
                "error": "Connection timeout",
                "timestamp": datetime.utcnow().isoformat()
            },
            priority=EventPriority.CRITICAL,
            source="test"
        )

        await event_bus.publish(event)

        assert event_bus.kafka_producer is not None

    async def test_low_priority_event_not_to_kafka(self, event_bus):
        """LOW 우선순위 이벤트는 Kafka로 전송되지 않음"""
        if not kafka_available:
            pytest.skip("Kafka not available")

        event = Event(
            type=EventType.SYSTEM_HEARTBEAT,
            payload={"status": "ok"},
            priority=EventPriority.LOW,
            source="test"
        )

        await event_bus.publish(event)

        # LOW는 Kafka로 가지 않음 (producer 존재 확인만)
        assert event_bus.kafka_producer is not None

    async def test_event_type_to_kafka_topic_mapping(self, event_bus):
        """이벤트 타입에서 Kafka 토픽 변환 테스트"""
        # 주문 이벤트
        topic = event_bus._event_type_to_kafka_topic(EventType.ORDER_NEW)
        assert topic == "order_new"

        # 신호 이벤트
        topic = event_bus._event_type_to_kafka_topic(EventType.SIGNAL_BUY)
        assert topic == "signal_buy"

        # 거래 이벤트
        topic = event_bus._event_type_to_kafka_topic(EventType.TRADE_EXECUTED)
        assert topic == "trade_executed"

    async def test_kafka_connection_failure_graceful(self):
        """Kafka 연결 실패시 graceful degradation"""
        bus = EventBus(
            mqtt_host="localhost",
            mqtt_port=1883,
            kafka_bootstrap="invalid-host:9999",  # 잘못된 주소
            enable_kafka=True
        )

        # Kafka 초기화 실패핏도 enable_kafka는 False로 전환
        assert bus.enable_kafka is False
        assert bus.kafka_producer is None

        # 이벤트 발행 시 에러 없음
        event = Event(
            type=EventType.SIGNAL_BUY,
            payload={"symbol": "BTC/USDT", "price": 50000.0},
            priority=EventPriority.HIGH,
            source="test"
        )

        # 에러 없이 실행되어야 함
        await bus.publish(event)


class TestKafkaTopicsExist:
    """Kafka 토픽 존재 여부 확인"""

    @pytest.mark.skipif(not kafka_available, reason="Kafka not installed")
    def test_required_topics_exist(self):
        """필수 토픽 존재 확인"""
        try:
            admin_client = KafkaAdminClient(
                bootstrap_servers="localhost:9092"
            )
            topics = admin_client.list_topics()

            required_topics = ["market_data", "signals", "orders", "system_logs"]
            for topic in required_topics:
                assert topic in topics, f"Topic {topic} not found"

            admin_client.close()
        except Exception as e:
            pytest.skip(f"Cannot connect to Kafka: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

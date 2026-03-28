"""
OZ_A2M Event Bus
Kafka + MQTT 하이브리드 이벤트 버스

P1 작업: Phase 7 인프라 연동
- 고유 이벤트는 Kafka에 영속화
- 실시간 이벤트는 MQTT로 브로드캐스트
"""

import asyncio
import json
from enum import Enum
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, asdict
from datetime import datetime
import logging

from .mqtt_client import MQTTClient, MQTTConfig

logger = logging.getLogger(__name__)


class EventPriority(Enum):
    """이벤트 우선순위"""
    LOW = "low"        # 로그, 메트릭
    MEDIUM = "medium"  # 일반 상태 업데이트
    HIGH = "high"      # 주문, 체결 (Kafka 영속화)
    CRITICAL = "critical"  # 에러, 알림


class EventType(Enum):
    """이벤트 유형"""
    # 시장 데이터
    MARKET_DATA = "market.data"
    OHLCV = "market.ohlcv"
    ORDERBOOK = "market.orderbook"
    TRADE_TICK = "market.trade"

    # 시그널
    SIGNAL = "signal"
    SIGNAL_BUY = "signal.buy"
    SIGNAL_SELL = "signal.sell"

    # 주문/실행
    ORDER_NEW = "order.new"
    ORDER_UPDATE = "order.update"
    ORDER_FILL = "order.fill"
    TRADE_EXECUTED = "trade.executed"

    # 봇 상태
    BOT_START = "bot.start"
    BOT_STOP = "bot.stop"
    BOT_ERROR = "bot.error"
    BOT_STATUS = "bot.status"

    # 시스템
    SYSTEM_HEARTBEAT = "system.heartbeat"
    SYSTEM_LOG = "system.log"
    SYSTEM_ALERT = "system.alert"


@dataclass
class Event:
    """이벤트 데이터"""
    type: EventType
    payload: Dict[str, Any]
    priority: EventPriority = EventPriority.MEDIUM
    timestamp: Optional[str] = None
    source: Optional[str] = None
    event_id: Optional[str] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()
        if self.event_id is None:
            import uuid
            self.event_id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type.value,
            "priority": self.priority.value,
            "timestamp": self.timestamp,
            "source": self.source,
            "payload": self.payload
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class EventBus:
    """
    하이브리드 이벤트 버스

    - MQTT: 실시간 브로드캐스트 (낮은 지연)
    - Kafka: 이벤트 영속화 (높은 우선순위)
    """

    def __init__(
        self,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        kafka_bootstrap: Optional[str] = None,
        enable_kafka: bool = True  # Kafka 연동 활성화 (STEP 1)
    ):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.kafka_bootstrap = kafka_bootstrap or "localhost:9092"
        self.enable_kafka = enable_kafka

        # MQTT
        mqtt_config = MQTTConfig(
            host=mqtt_host,
            port=mqtt_port,
            client_id="event_bus"
        )
        self.mqtt = MQTTClient(config=mqtt_config)
        self._mqtt_connected = False

        # Kafka (선택적)
        self.kafka_producer = None
        self.kafka_consumer = None
        if enable_kafka:
            self._init_kafka()

        # 구독자 관리
        self._subscribers: Dict[EventType, List[Callable]] = {}

        logger.info(f"EventBus initialized (Kafka: {enable_kafka})")

    def _init_kafka(self):
        """Kafka 초기화"""
        try:
            from kafka import KafkaProducer
            self.kafka_producer = KafkaProducer(
                bootstrap_servers=self.kafka_bootstrap,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            logger.info("Kafka producer initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize Kafka: {e}")
            self.enable_kafka = False

    async def connect(self):
        """연결"""
        try:
            await self.mqtt.connect()
            self._mqtt_connected = True
            logger.info("EventBus MQTT connected")
        except Exception as e:
            logger.error(f"EventBus MQTT connection failed: {e}")

    async def disconnect(self):
        """연결 해제"""
        if self._mqtt_connected:
            await self.mqtt.disconnect()
            self._mqtt_connected = False

        if self.kafka_producer:
            self.kafka_producer.close()

    async def publish(self, event: Event):
        """
        이벤트 발행

        - HIGH/CRITICAL: Kafka + MQTT
        - LOW/MEDIUM: MQTT만
        """
        # MQTT 발행 (실시간 브로드캐스트)
        if self._mqtt_connected:
            try:
                topic = self._event_type_to_topic(event.type)
                await self.mqtt.publish(topic, event.to_json())
            except Exception as e:
                logger.error(f"Failed to publish to MQTT: {e}")

        # Kafka 발행 (영속화가 필요한 높은 우선순위 이벤트)
        if self.enable_kafka and event.priority in (EventPriority.HIGH, EventPriority.CRITICAL):
            try:
                self._publish_to_kafka(event)
            except Exception as e:
                logger.error(f"Failed to publish to Kafka: {e}")

        # 로컬 구독자 호출
        await self._notify_subscribers(event)

    def _publish_to_kafka(self, event: Event):
        """Kafka에 이벤트 발행"""
        if not self.kafka_producer:
            return

        topic = self._event_type_to_kafka_topic(event.type)
        self.kafka_producer.send(topic, event.to_dict())
        logger.debug(f"Published to Kafka: {topic}")

    async def subscribe(
        self,
        event_type: EventType,
        callback: Callable[[Event], asyncio.Future]
    ):
        """이벤트 구독"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

        # MQTT 토픽 구독
        if self._mqtt_connected:
            topic = self._event_type_to_topic(event_type)
            await self.mqtt.subscribe(topic, self._on_mqtt_message)

    async def _on_mqtt_message(self, message):
        """MQTT 메시지 수신"""
        try:
            topic = message.topic.value
            payload = message.payload.decode()
            data = json.loads(payload)

            # Event 객체로 변환
            event = Event(
                type=EventType(data["type"]),
                payload=data["payload"],
                priority=EventPriority(data["priority"]),
                timestamp=data.get("timestamp"),
                source=data.get("source"),
                event_id=data.get("event_id")
            )

            await self._notify_subscribers(event)
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")

    async def _notify_subscribers(self, event: Event):
        """구독자에게 알림"""
        callbacks = self._subscribers.get(event.type, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                logger.error(f"Subscriber error: {e}")

    def _event_type_to_topic(self, event_type: EventType) -> str:
        """이벤트 타입을 MQTT 토픽으로 변환"""
        return f"events/{event_type.value}"

    def _event_type_to_kafka_topic(self, event_type: EventType) -> str:
        """이벤트 타입을 Kafka 토픽으로 변환"""
        return event_type.value.replace(".", "_")

    # 편의 메서드
    async def emit_signal(
        self,
        signal_type: str,
        symbol: str,
        price: float,
        confidence: float,
        **kwargs
    ):
        """시그널 이벤트 발행"""
        event_type = EventType.SIGNAL_BUY if signal_type == "buy" else EventType.SIGNAL_SELL
        event = Event(
            type=event_type,
            payload={
                "symbol": symbol,
                "price": price,
                "confidence": confidence,
                **kwargs
            },
            priority=EventPriority.HIGH,
            source="event_bus"
        )
        await self.publish(event)

    async def emit_order(
        self,
        order_id: str,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        order_type: str = "market"
    ):
        """주문 이벤트 발행"""
        event = Event(
            type=EventType.ORDER_NEW,
            payload={
                "order_id": order_id,
                "symbol": symbol,
                "side": side,
                "amount": amount,
                "price": price,
                "order_type": order_type
            },
            priority=EventPriority.HIGH,
            source="event_bus"
        )
        await self.publish(event)

    async def emit_trade(
        self,
        trade_id: str,
        order_id: str,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        pnl: Optional[float] = None
    ):
        """체결 이벤트 발행"""
        event = Event(
            type=EventType.TRADE_EXECUTED,
            payload={
                "trade_id": trade_id,
                "order_id": order_id,
                "symbol": symbol,
                "side": side,
                "amount": amount,
                "price": price,
                "pnl": pnl
            },
            priority=EventPriority.HIGH,
            source="event_bus"
        )
        await self.publish(event)

    async def emit_bot_status(
        self,
        bot_id: str,
        status: str,
        detail: Optional[Dict] = None
    ):
        """봇 상태 이벤트 발행"""
        event = Event(
            type=EventType.BOT_STATUS,
            payload={
                "bot_id": bot_id,
                "status": status,
                "detail": detail or {}
            },
            priority=EventPriority.MEDIUM,
            source="event_bus"
        )
        await self.publish(event)


# 전역 인스턴스
_event_bus_instance: Optional[EventBus] = None


def get_event_bus(
    mqtt_host: str = "localhost",
    mqtt_port: int = 1883,
    enable_kafka: bool = False
) -> EventBus:
    """전역 EventBus 인스턴스 가져오기"""
    global _event_bus_instance
    if _event_bus_instance is None:
        _event_bus_instance = EventBus(
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            enable_kafka=enable_kafka
        )
    return _event_bus_instance


# 테스트
if __name__ == "__main__":
    async def test():
        bus = get_event_bus()
        await bus.connect()

        # 구독
        async def on_signal(event: Event):
            print(f"Received signal: {event.payload}")

        await bus.subscribe(EventType.SIGNAL_BUY, on_signal)

        # 발행
        await bus.emit_signal(
            signal_type="buy",
            symbol="BTC/USDT",
            price=65000.0,
            confidence=0.85
        )

        await asyncio.sleep(1)
        await bus.disconnect()

    asyncio.run(test())

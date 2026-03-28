"""
Verification Pipeline

신호 검증 파이프라인
MQTT: signals/raw → 처리 → signals/verified 발행
"""

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime
from typing import Dict, Any, Optional

import aiomqtt

# 프로젝트 루트 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from lib.core.logger import get_logger
from lib.core.tracer import get_tracer, trace_function
from lib.messaging.event_bus import get_event_bus
from occore.analytics.event_logger import EventLogger, EventType
from .noise_filter import NoiseFilter, SignalVerifier, FilterResult

logger = get_logger(__name__)
tracer = get_tracer("dept2_verification")

# 설정
MQTT_HOST = os.getenv('MQTT_HOST', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
VERIFICATION_COOLDOWN = float(os.getenv('VERIFICATION_COOLDOWN', '60'))


class VerificationPipeline:
    """
    신호 검증 파이프라인

    동작:
    1. MQTT 구독: oz/a2m/signals/raw
    2. 노이즈 필터 적용 (RSI/볼린저밴드)
    3. 신호 검증 (중복/쿨다운 체크)
    4. 검증 결과 MQTT 발행: oz/a2m/signals/verified
    """

    def __init__(
        self,
        mqtt_host: str = MQTT_HOST,
        mqtt_port: int = MQTT_PORT,
    ):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.noise_filter = NoiseFilter()
        self.signal_verifier = SignalVerifier(cooldown_seconds=VERIFICATION_COOLDOWN)
        self.event_logger = EventLogger(enable_console=True)

        self._running = False
        self._mqtt_client: Optional[aiomqtt.Client] = None
        self._event_bus = get_event_bus(enable_kafka=False)

        logger.info(f"VerificationPipeline initialized: {mqtt_host}:{mqtt_port}")

    async def start(self):
        """파이프라인 시작"""
        self._running = True
        logger.info("Starting Verification Pipeline...")

        # MQTT 연결
        while self._running:
            try:
                async with aiomqtt.Client(
                    hostname=self.mqtt_host,
                    port=self.mqtt_port,
                    client_id="dept2_verification_pipeline",
                ) as client:
                    self._mqtt_client = client
                    logger.info("Connected to MQTT")

                    # 토픽 구독
                    await client.subscribe("oz/a2m/signals/raw")
                    logger.info("Subscribed to oz/a2m/signals/raw")

                    # 이벤트 수신 루프
                    async for message in client.messages:
                        if not self._running:
                            break
                        await self._handle_message(message)

            except aiomqtt.MqttError as e:
                logger.error(f"MQTT error: {e}")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Pipeline error: {e}")
                await asyncio.sleep(5)

    async def stop(self):
        """파이프라인 중지"""
        logger.info("Stopping Verification Pipeline...")
        self._running = False

    async def _handle_message(self, message: aiomqtt.Message):
        """MQTT 메시지 처리"""
        try:
            payload = json.loads(message.payload.decode())
            logger.debug(f"Received raw signal: {payload}")

            # 이벤트 로깅
            await self.event_logger.log_event(
                event_type=EventType.TASK_START,
                department="dept2",
                task_name="verify_signal",
                metadata={"signal_id": payload.get("signal_id")},
            )

            # 신호 검증 파이프라인 실행
            await self._process_signal(payload)

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"Message handling error: {e}")

    @trace_function("verify_signal")
    async def _process_signal(self, signal: Dict[str, Any]):
        """
        신호 처리

        Args:
            signal: 원본 신호
        """
        symbol = signal.get("symbol", "")
        action = signal.get("action", "")

        logger.info(f"Processing signal: {symbol} {action}")

        # 1. 신호 검증 (쿨다운, 중복 체크)
        verify_result = self.signal_verifier.verify_signal(signal)

        if not verify_result.is_valid:
            logger.warning(f"Signal rejected: {verify_result.rejection_reason}")
            await self._publish_rejection(signal, verify_result)
            return

        # 2. 노이즈 필터링 (RSI/볼린저밴드)
        # 가격 히스토리는 신호에서 가져오거나 기본값 사용
        price_history = signal.get("price_history", [])
        if not price_history and "price" in signal:
            # 가격 히스토리가 없으면 현재가로 기본 생성
            price_history = [signal["price"] * (1 - 0.001 * i) for i in range(20)]
            price_history.reverse()

        volume = signal.get("volume", 0.0)

        filter_result = self.noise_filter.filter_signal(
            signal, price_history, volume
        )

        # 3. 결과 발행
        if filter_result.is_valid and filter_result.quality.value in ["excellent", "good"]:
            await self._publish_verified_signal(signal, filter_result)
        else:
            await self._publish_rejection(signal, filter_result)

        # 이벤트 로깅
        await self.event_logger.log_event(
            event_type=EventType.TASK_COMPLETE,
            department="dept2",
            task_name="verify_signal",
            metadata={
                "symbol": symbol,
                "action": action,
                "quality": filter_result.quality.value,
                "confidence": filter_result.confidence,
            },
        )

    async def _publish_verified_signal(
        self,
        signal: Dict[str, Any],
        filter_result: FilterResult,
    ):
        """검증된 신호 발행"""
        verified_signal = {
            **signal,
            "verified_at": datetime.utcnow().isoformat(),
            "verification": {
                "quality": filter_result.quality.value,
                "confidence": filter_result.confidence,
                "indicators": filter_result.indicators,
            },
            "department": "dept2",
        }

        topic = "oz/a2m/signals/verified"
        payload = json.dumps(verified_signal)

        if self._mqtt_client:
            await self._mqtt_client.publish(topic, payload, qos=1)
            logger.info(f"Published verified signal: {signal.get('symbol')} {signal.get('action')}")

        # Kafka로도 발행 (HIGH priority)
        try:
            await self._event_bus.publish_async(
                "oz.a2m.signals.verified",
                verified_signal,
                priority="HIGH",
            )
        except Exception as e:
            logger.warning(f"Kafka publish failed: {e}")

    async def _publish_rejection(
        self,
        signal: Dict[str, Any],
        result: FilterResult,
    ):
        """거부된 신호 발행"""
        rejection = {
            "original_signal": signal,
            "rejected_at": datetime.utcnow().isoformat(),
            "reason": result.rejection_reason,
            "quality": result.quality.value,
            "department": "dept2",
        }

        topic = "oz/a2m/signals/rejected"
        payload = json.dumps(rejection)

        if self._mqtt_client:
            await self._mqtt_client.publish(topic, payload, qos=1)
            logger.info(f"Published rejection: {result.rejection_reason}")

    def get_stats(self) -> Dict[str, Any]:
        """파이프라인 통계"""
        return {
            "verifier": self.signal_verifier.get_stats(),
            "running": self._running,
            "mqtt_host": self.mqtt_host,
        }


async def main():
    """메인 실행 함수"""
    pipeline = VerificationPipeline()

    # 시그널 핸들러
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}")
        asyncio.create_task(pipeline.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 파이프라인 실행
    try:
        await pipeline.start()
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
    finally:
        await pipeline.stop()
        logger.info("Verification Pipeline stopped")


if __name__ == "__main__":
    asyncio.run(main())

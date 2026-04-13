"""
OZ_A2M 제2부서: 정보검증분석센터 - 메인 서비스

D1 관제탑에서 MQTT로 수신한 데이터를 검증하고
검증된 신호를 D3, D4, D7로 발행합니다.
"""

import asyncio
import json
import logging
import os
import sys
from typing import Dict, Any, Optional
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from lib.messaging import get_mqtt_client
from lib.messaging import BaseMessage as MQTTMessage
from lib.core import get_logger
from occore.verification import VerificationPipeline
from occore.verification.models import (
    TradingSignal, FilteredData, IndicatorValues,
    SignalDirection, VerificationResult
)

logger = get_logger(__name__)


class D2VerificationService:
    """D2 검증 분석 서비스"""

    def __init__(
        self,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883
    ):
        self.mqtt = get_mqtt_client()
        self.verifier = VerificationPipeline()
        self._running = False

        # 수신 데이터 버퍼
        self._price_buffer: Dict[str, Any] = {}
        self._orderbook_buffer: Dict[str, Any] = {}

    async def start(self):
        """서비스 시작"""
        await self.mqtt.connect()

        # D1 데이터 구독
        await self.mqtt.subscribe("oz_a2m/market/+/price", self._on_price)
        await self.mqtt.subscribe("oz_a2m/market/+/orderbook", self._on_orderbook)
        await self.mqtt.subscribe("oz_a2m/market/+/snapshot", self._on_snapshot)

        # D6 시스템 명령 구독
        await self.mqtt.subscribe("oz_a2m/system/verify", self._on_verify_command)

        self._running = True
        logger.info("D2 Verification Service started")

        # 처리 루프
        while self._running:
            await asyncio.sleep(1)

    async def stop(self):
        """서비스 중지"""
        self._running = False
        await self.mqtt.disconnect()
        logger.info("D2 Verification Service stopped")

    async def _on_price(self, message: MQTTMessage):
        """가격 데이터 수신"""
        try:
            payload = json.loads(message.payload.decode())
            symbol = payload.get("symbol", "")
            self._price_buffer[symbol] = payload
            logger.debug(f"Price received: {symbol}")
        except Exception as e:
            logger.error(f"Price processing error: {e}")

    async def _on_orderbook(self, message: MQTTMessage):
        """오더북 데이터 수신"""
        try:
            payload = json.loads(message.payload.decode())
            symbol = payload.get("symbol", "")
            self._orderbook_buffer[symbol] = payload
            logger.debug(f"Orderbook received: {symbol}")
        except Exception as e:
            logger.error(f"Orderbook processing error: {e}")

    async def _on_snapshot(self, message: MQTTMessage):
        """스냅샷 수신 - 검증 트리거"""
        try:
            payload = json.loads(message.payload.decode())
            symbol = payload.get("symbol", "")

            # 검증 수행
            result = await self._verify_signal(symbol, payload)

            if result and result.status.value in ["passed", "warning"]:
                # 검증 통과 시 D3/D4/D7로 발행
                await self._publish_verified_signal(symbol, result, payload)

        except Exception as e:
            logger.error(f"Snapshot processing error: {e}")

    async def _on_verify_command(self, message: MQTTMessage):
        """검증 명령 수신"""
        try:
            payload = json.loads(message.payload.decode())
            symbol = payload.get("symbol", "")

            logger.info(f"Verification command received: {symbol}")

            # 수동 검증 트리거
            snapshot = self._price_buffer.get(symbol, {})
            if snapshot:
                result = await self._verify_signal(symbol, snapshot)
                await self._publish_verified_signal(symbol, result, snapshot)

        except Exception as e:
            logger.error(f"Verify command error: {e}")

    async def _verify_signal(
        self,
        symbol: str,
        snapshot: Dict[str, Any]
    ) -> Optional[VerificationResult]:
        """신호 검증 수행"""
        try:
            price = snapshot.get("price", 0)
            if price == 0:
                return None

            # TradingSignal 생성
            signal = TradingSignal(
                id=f"sig_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                direction=SignalDirection.LONG,  # TODO: 실제 시그널 방향 결정
                entry_price=Decimal(str(price)),
                confidence=0.75,
                timestamp=datetime.now()
            )

            # FilteredData 생성
            filtered_data = FilteredData(
                symbol=symbol,
                timestamp=datetime.now(),
                noise_filtered=True,
                anomaly_checked=True
            )

            # 지표값 생성 (TODO: 실제 지표 계산 연동)
            indicators = IndicatorValues(
                rsi_14=50.0,
                macd=0.0,
                macd_signal=0.0,
                sma_20=price,
                sma_50=price
            )

            # 검증 실행
            result = self.verifier.execute(
                signal=signal,
                filtered_data=filtered_data,
                indicators=indicators,
                additional_data={
                    "spread_pct": 0.001,
                    "exchange_prices": {snapshot.get("exchange", "unknown"): Decimal(str(price))}
                }
            )

            logger.info(
                f"Verification completed: {symbol} "
                f"score={result.overall_score:.2f} status={result.status.value}"
            )

            return result

        except Exception as e:
            logger.error(f"Verification error: {e}")
            return None

    async def _publish_verified_signal(
        self,
        symbol: str,
        result: VerificationResult,
        source_data: Dict[str, Any]
    ):
        """검증된 신호 발행"""
        topic = f"oz_a2m/signal/{symbol.replace('/', '_')}"

        payload = {
            "symbol": symbol,
            "signal": "buy" if result.status.value != "failed" else "neutral",
            "price": float(source_data.get("price", 0)),
            "confidence": result.overall_score,
            "verification_status": result.status.value,
            "warnings": result.warnings,
            "recommendations": result.recommendations,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "d2_verification"
        }

        try:
            await self.mqtt.publish(topic, payload)
            logger.info(f"Verified signal published: {symbol} score={result.overall_score:.2f}")
        except Exception as e:
            logger.error(f"Failed to publish signal: {e}")


async def main():
    """메인 실행"""
    service = D2VerificationService()

    try:
        await service.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await service.stop()


if __name__ == "__main__":
    asyncio.run(main())

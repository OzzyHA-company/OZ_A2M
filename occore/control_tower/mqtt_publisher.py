"""
OZ_A2M D1 → MQTT 데이터 발행기

관제탑에서 수집한 데이터를 MQTT로 발행하여 D2 및 다른 부서로 전달
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from lib.messaging import get_mqtt_client
from lib.cache import get_redis_cache

logger = logging.getLogger(__name__)


class MQTTPublisher:
    """관제탑 데이터 MQTT 발행기"""

    def __init__(
        self,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        redis_host: str = "localhost",
        redis_port: int = 6379
    ):
        self.mqtt = get_mqtt_client()
        self.redis = get_redis_cache(host=redis_host, port=redis_port)
        self._running = False

    async def start(self):
        """발행기 시작"""
        await self.mqtt.connect()
        await self.redis.connect()
        self._running = True
        logger.info("MQTT Publisher started")

    async def stop(self):
        """발행기 중지"""
        self._running = False
        await self.mqtt.disconnect()
        await self.redis.disconnect()
        logger.info("MQTT Publisher stopped")

    async def publish_price(
        self,
        symbol: str,
        price: float,
        exchange: str = "unknown",
        timestamp: Optional[str] = None
    ):
        """가격 데이터 발행"""
        if not self._running:
            return

        topic = f"oz_a2m/market/{symbol.replace('/', '_')}/price"
        payload = {
            "symbol": symbol,
            "price": price,
            "exchange": exchange,
            "timestamp": timestamp or datetime.utcnow().isoformat(),
            "source": "d1_control_tower"
        }

        try:
            await self.mqtt.publish(topic, payload)
            # Redis에도 캐싱
            await self.redis.set_price(symbol, price, exchange)
            logger.debug(f"Price published: {symbol} = {price}")
        except Exception as e:
            logger.error(f"Failed to publish price: {e}")

    async def publish_orderbook(
        self,
        symbol: str,
        bids: list,
        asks: list,
        exchange: str = "unknown"
    ):
        """오더북 데이터 발행"""
        if not self._running:
            return

        topic = f"oz_a2m/market/{symbol.replace('/', '_')}/orderbook"
        payload = {
            "symbol": symbol,
            "bids": bids[:10],  # 상위 10개만
            "asks": asks[:10],
            "exchange": exchange,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "d1_control_tower"
        }

        try:
            await self.mqtt.publish(topic, payload)
            await self.redis.set_orderbook(symbol, bids, asks, exchange)
            logger.debug(f"Orderbook published: {symbol}")
        except Exception as e:
            logger.error(f"Failed to publish orderbook: {e}")

    async def publish_snapshot(
        self,
        symbol: str,
        snapshot: Dict[str, Any]
    ):
        """시장 스냅샷 발행"""
        if not self._running:
            return

        topic = f"oz_a2m/market/{symbol.replace('/', '_')}/snapshot"
        payload = {
            **snapshot,
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "d1_control_tower"
        }

        try:
            await self.mqtt.publish(topic, payload)
            await self.redis.set_market_snapshot(symbol, snapshot)
            logger.debug(f"Snapshot published: {symbol}")
        except Exception as e:
            logger.error(f"Failed to publish snapshot: {e}")

    async def publish_trade(
        self,
        symbol: str,
        trade: Dict[str, Any]
    ):
        """체결 데이터 발행"""
        if not self._running:
            return

        topic = f"oz_a2m/market/{symbol.replace('/', '_')}/trade"
        payload = {
            **trade,
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "d1_control_tower"
        }

        try:
            await self.mqtt.publish(topic, payload)
            logger.debug(f"Trade published: {symbol}")
        except Exception as e:
            logger.error(f"Failed to publish trade: {e}")


# 전역 인스턴스
_publisher_instance: Optional[MQTTPublisher] = None


def get_mqtt_publisher(
    mqtt_host: str = "localhost",
    mqtt_port: int = 1883
) -> MQTTPublisher:
    """전역 MQTTPublisher 인스턴스 가져오기"""
    global _publisher_instance
    if _publisher_instance is None:
        _publisher_instance = MQTTPublisher(
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port
        )
    return _publisher_instance

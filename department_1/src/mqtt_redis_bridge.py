"""
MQTT to Redis Bridge

MQTT로 수신한 시장 데이터를 Redis에 캐싱하는 브리지
"""

import asyncio
import json
import logging
from typing import Dict, Any

from lib.messaging import get_mqtt_client, MQTTMessage
from lib.cache import get_redis_cache

logger = logging.getLogger(__name__)


class MqttRedisBridge:
    """MQTT 메시지를 Redis에 캐싱하는 브리지"""

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
        """브리지 시작"""
        # Redis 연결
        connected = await self.redis.connect()
        if not connected:
            logger.error("Failed to connect to Redis")
            return False

        # MQTT 연결 및 구독
        await self.mqtt.connect()

        # 시장 데이터 토픽 구독
        await self.mqtt.subscribe("oz_a2m/market/+/price", self._on_price_message)
        await self.mqtt.subscribe("oz_a2m/market/+/orderbook", self._on_orderbook_message)
        await self.mqtt.subscribe("oz_a2m/market/+/snapshot", self._on_snapshot_message)
        await self.mqtt.subscribe("oz_a2m/signal/+", self._on_signal_message)
        await self.mqtt.subscribe("oz_a2m/agent/+/heartbeat", self._on_agent_heartbeat)

        self._running = True
        logger.info("MQTT-Redis Bridge started")
        return True

    async def stop(self):
        """브리지 중지"""
        self._running = False
        await self.mqtt.disconnect()
        await self.redis.disconnect()
        logger.info("MQTT-Redis Bridge stopped")

    async def _on_price_message(self, message: MQTTMessage):
        """가격 메시지 처리"""
        try:
            topic = message.topic.value
            payload = json.loads(message.payload.decode())

            # 토픽에서 심볼 추출 (oz_a2m/market/BTC/USDT/price)
            parts = topic.split("/")
            if len(parts) >= 4:
                symbol = "/".join(parts[2:-1])  # BTC/USDT

                price = payload.get("price", 0.0)
                source = payload.get("source", "mqtt")

                await self.redis.set_price(symbol, price, source)
                logger.debug(f"Price cached from MQTT: {symbol} = {price}")

        except Exception as e:
            logger.error(f"Error processing price message: {e}")

    async def _on_orderbook_message(self, message: MQTTMessage):
        """오더북 메시지 처리"""
        try:
            topic = message.topic.value
            payload = json.loads(message.payload.decode())

            parts = topic.split("/")
            if len(parts) >= 4:
                symbol = "/".join(parts[2:-1])

                bids = payload.get("bids", [])
                asks = payload.get("asks", [])
                source = payload.get("source", "mqtt")

                await self.redis.set_orderbook(symbol, bids, asks, source)
                logger.debug(f"Orderbook cached: {symbol}")

        except Exception as e:
            logger.error(f"Error processing orderbook message: {e}")

    async def _on_snapshot_message(self, message: MQTTMessage):
        """시장 스냅샷 메시지 처리"""
        try:
            topic = message.topic.value
            payload = json.loads(message.payload.decode())

            parts = topic.split("/")
            if len(parts) >= 4:
                symbol = "/".join(parts[2:-1])

                await self.redis.set_market_snapshot(symbol, payload)
                logger.debug(f"Snapshot cached: {symbol}")

        except Exception as e:
            logger.error(f"Error processing snapshot message: {e}")

    async def _on_signal_message(self, message: MQTTMessage):
        """트레이딩 시그널 메시지 처리"""
        try:
            topic = message.topic.value
            payload = json.loads(message.payload.decode())

            # 토픽: oz_a2m/signal/BTC/USDT
            parts = topic.split("/")
            if len(parts) >= 3:
                symbol = "/".join(parts[2:])

                signal_type = payload.get("signal", "unknown")
                price = payload.get("price", 0.0)
                confidence = payload.get("confidence", 0.0)
                source = payload.get("source", "strategy")

                await self.redis.set_signal(symbol, signal_type, price, confidence, source)
                logger.info(f"Signal cached: {symbol} {signal_type} @ {price}")

        except Exception as e:
            logger.error(f"Error processing signal message: {e}")

    async def _on_agent_heartbeat(self, message: MQTTMessage):
        """에이전트 하트비트 처리"""
        try:
            topic = message.topic.value
            payload = json.loads(message.payload.decode())

            # 토픽: oz_a2m/agent/d1-market/heartbeat
            parts = topic.split("/")
            if len(parts) >= 3:
                agent_id = parts[2]

                await self.redis.update_agent_heartbeat(agent_id)
                logger.debug(f"Agent heartbeat: {agent_id}")

        except Exception as e:
            logger.error(f"Error processing heartbeat: {e}")


async def main():
    """메인 실행"""
    logging.basicConfig(level=logging.INFO)

    bridge = MqttRedisBridge()
    started = await bridge.start()

    if not started:
        logger.error("Failed to start bridge")
        return

    try:
        while bridge._running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await bridge.stop()


if __name__ == "__main__":
    asyncio.run(main())

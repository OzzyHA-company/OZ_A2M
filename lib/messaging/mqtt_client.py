"""Async MQTT client for OZ_A2M."""

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Dict, Optional, Union

import aiomqtt
from aiomqtt import Client

from ..core.config import get_settings
from ..core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MQTTConfig:
    """MQTT configuration."""
    host: str = "localhost"
    port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    keepalive: int = 60
    client_id: Optional[str] = None

    @classmethod
    def from_settings(cls) -> "MQTTConfig":
        """Create config from application settings."""
        settings = get_settings()
        return cls(
            host=settings.mqtt_host,
            port=settings.mqtt_port,
            username=settings.mqtt_username,
            password=settings.mqtt_password,
            keepalive=settings.mqtt_keepalive,
        )


class MQTTClient:
    """Async MQTT client wrapper."""

    def __init__(self, config: Optional[MQTTConfig] = None):
        self.config = config or MQTTConfig.from_settings()
        self._client: Optional[Client] = None
        self._subscribers: Dict[str, list] = {}
        self._connected = False
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected

    async def connect(self) -> None:
        """Connect to MQTT broker."""
        async with self._lock:
            if self._connected:
                return

            try:
                auth = {}
                if self.config.username:
                    auth = {"username": self.config.username, "password": self.config.password}

                self._client = Client(
                    hostname=self.config.host,
                    port=self.config.port,
                    keepalive=self.config.keepalive,
                    identifier=self.config.client_id,
                    **auth
                )
                await self._client.__aenter__()
                self._connected = True
                logger.info(
                    "MQTT connected",
                    host=self.config.host,
                    port=self.config.port,
                )
            except Exception as e:
                logger.error("MQTT connection failed", error=str(e))
                raise

    async def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        async with self._lock:
            if self._client and self._connected:
                await self._client.__aexit__(None, None, None)
                self._connected = False
                logger.info("MQTT disconnected")

    async def publish(
        self,
        topic: str,
        payload: Union[str, bytes, dict],
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        """Publish message to topic."""
        if not self._connected:
            await self.connect()

        try:
            if isinstance(payload, dict):
                import json
                payload = json.dumps(payload)
            await self._client.publish(topic, payload, qos=qos, retain=retain)
            logger.debug("MQTT message published", topic=topic, qos=qos)
        except Exception as e:
            logger.error("MQTT publish failed", topic=topic, error=str(e))
            raise

    async def subscribe(
        self,
        topic: str,
        callback: Callable[[aiomqtt.Message], Coroutine[Any, Any, None]],
        qos: int = 0,
    ) -> None:
        """Subscribe to topic with callback."""
        if not self._connected:
            await self.connect()

        try:
            await self._client.subscribe(topic, qos=qos)
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            self._subscribers[topic].append(callback)
            logger.info("MQTT subscribed", topic=topic, qos=qos)

            # Start listening for messages
            asyncio.create_task(self._listen(topic, callback))
        except Exception as e:
            logger.error("MQTT subscribe failed", topic=topic, error=str(e))
            raise

    async def _listen(
        self,
        topic: str,
        callback: Callable[[aiomqtt.Message], Coroutine[Any, Any, None]]
    ) -> None:
        """Listen for messages on a topic."""
        try:
            async for message in self._client.messages:
                # Filter messages by topic (simple wildcard support)
                if self._topic_matches(topic, message.topic.value):
                    try:
                        await callback(message)
                    except Exception as e:
                        logger.error("Message callback error", error=str(e))
        except Exception as e:
            logger.error("MQTT listener error", topic=topic, error=str(e))

    def _topic_matches(self, subscription: str, topic: str) -> bool:
        """Check if topic matches subscription pattern."""
        if subscription == topic:
            return True
        if subscription.endswith("/+"):
            prefix = subscription[:-2]
            return topic.startswith(prefix + "/") and "/" not in topic[len(prefix)+1:]
        if subscription.endswith("/#"):
            prefix = subscription[:-2]
            return topic.startswith(prefix)
        return False

    async def __aenter__(self) -> "MQTTClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()


# Global client instance
_mqtt_client: Optional[MQTTClient] = None


def get_mqtt_client() -> MQTTClient:
    """Get or create global MQTT client."""
    global _mqtt_client
    if _mqtt_client is None:
        _mqtt_client = MQTTClient()
    return _mqtt_client

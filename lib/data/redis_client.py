"""Redis client for caching and state management."""

import json
from typing import Any, Optional, Union

import redis.asyncio as redis

from ..core.config import get_settings
from ..core.logger import get_logger

logger = get_logger(__name__)


class RedisClient:
    """Async Redis client wrapper."""

    def __init__(self):
        self._client: Optional[redis.Redis] = None
        self._settings = get_settings()

    async def connect(self) -> None:
        """Connect to Redis."""
        if self._client is None:
            self._client = redis.from_url(
                self._settings.redis_url,
                decode_responses=True,
            )
            logger.info("Redis connected")

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis disconnected")

    async def get(self, key: str) -> Optional[str]:
        """Get value by key."""
        await self.connect()
        return await self._client.get(key)

    async def set(
        self,
        key: str,
        value: Union[str, int, float, dict, list],
        expire: Optional[int] = None,
    ) -> None:
        """Set value with optional expiration (seconds)."""
        await self.connect()
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        await self._client.set(key, value, ex=expire)

    async def delete(self, key: str) -> int:
        """Delete key(s)."""
        await self.connect()
        return await self._client.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        await self.connect()
        return await self._client.exists(key) > 0

    async def expire(self, key: str, seconds: int) -> bool:
        """Set key expiration."""
        await self.connect()
        return await self._client.expire(key, seconds)

    async def ttl(self, key: str) -> int:
        """Get time-to-live for key."""
        await self.connect()
        return await self._client.ttl(key)

    async def incr(self, key: str) -> int:
        """Increment key value."""
        await self.connect()
        return await self._client.incr(key)

    async def decr(self, key: str) -> int:
        """Decrement key value."""
        await self.connect()
        return await self._client.decr(key)

    async def lpush(self, key: str, *values: Any) -> int:
        """Push values to list head."""
        await self.connect()
        return await self._client.lpush(key, *values)

    async def rpop(self, key: str) -> Optional[str]:
        """Pop value from list tail."""
        await self.connect()
        return await self._client.rpop(key)

    async def lrange(self, key: str, start: int, end: int) -> list:
        """Get list range."""
        await self.connect()
        return await self._client.lrange(key, start, end)


# Global client
_redis_client: Optional[RedisClient] = None


def get_redis_client() -> RedisClient:
    """Get or create global Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client

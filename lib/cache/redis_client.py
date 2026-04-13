"""
OZ_A2M Redis Cache Client

실시간 시장 데이터 캐싱 및 에이전트 레지스트리 관리
"""

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisCache:
    """Redis 기반 캐시 클라이언트"""

    # 키 접두사
    KEY_PRICE = "oz:a2m:price:{symbol}"
    KEY_ORDERBOOK = "oz:a2m:orderbook:{symbol}"
    KEY_AGENT = "oz:a2m:agent:{agent_id}"
    KEY_AGENTS_LIST = "oz:a2m:agents:active"
    KEY_MARKET_SNAPSHOT = "oz:a2m:snapshot:{symbol}"
    KEY_SIGNAL = "oz:a2m:signal:{symbol}"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6380,
        db: int = 0,
        password: Optional[str] = None,
        socket_timeout: float = 5.0
    ):
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.socket_timeout = socket_timeout
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> bool:
        """Redis 연결"""
        try:
            self._client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                socket_timeout=self.socket_timeout,
                decode_responses=True
            )
            await self._client.ping()
            logger.info(f"Redis connected: {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            return False

    async def disconnect(self):
        """Redis 연결 해제"""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis disconnected")

    # === 가격 데이터 캐싱 ===

    async def set_price(
        self,
        symbol: str,
        price: float,
        source: str = "gateway",
        ttl_seconds: int = 10
    ):
        """심볼 가격 캐싱"""
        if not self._client:
            return

        key = self.KEY_PRICE.format(symbol=symbol.upper())
        data = {
            "symbol": symbol.upper(),
            "price": price,
            "timestamp": datetime.utcnow().isoformat(),
            "source": source
        }

        try:
            await self._client.setex(key, ttl_seconds, json.dumps(data))
            logger.debug(f"Price cached: {symbol} = {price}")
        except Exception as e:
            logger.error(f"Failed to cache price: {e}")

    async def get_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """심볼 가격 조회"""
        if not self._client:
            return None

        key = self.KEY_PRICE.format(symbol=symbol.upper())
        try:
            data = await self._client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to get price: {e}")
            return None

    async def get_prices(self, symbols: List[str]) -> Dict[str, Any]:
        """여러 심볼 가격 조회"""
        if not self._client:
            return {"prices": []}

        prices = []
        for symbol in symbols:
            price_data = await self.get_price(symbol)
            if price_data:
                prices.append(price_data)
            else:
                prices.append({
                    "symbol": symbol.upper(),
                    "price": 0.0,
                    "timestamp": datetime.utcnow().isoformat(),
                    "source": "cache_miss"
                })

        return {"prices": prices}

    # === 오더북 캐싱 ===

    async def set_orderbook(
        self,
        symbol: str,
        bids: List[List[float]],
        asks: List[List[float]],
        source: str = "gateway",
        ttl_seconds: int = 5
    ):
        """오더북 캐싱"""
        if not self._client:
            return

        key = self.KEY_ORDERBOOK.format(symbol=symbol.upper())
        data = {
            "symbol": symbol.upper(),
            "bids": bids,
            "asks": asks,
            "timestamp": datetime.utcnow().isoformat(),
            "source": source
        }

        try:
            await self._client.setex(key, ttl_seconds, json.dumps(data))
        except Exception as e:
            logger.error(f"Failed to cache orderbook: {e}")

    async def get_orderbook(self, symbol: str) -> Optional[Dict[str, Any]]:
        """오더북 조회"""
        if not self._client:
            return None

        key = self.KEY_ORDERBOOK.format(symbol=symbol.upper())
        try:
            data = await self._client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to get orderbook: {e}")
            return None

    # === 에이전트 레지스트리 ===

    async def register_agent(
        self,
        agent_id: str,
        department: str,
        role: str,
        status: str = "active",
        metadata: Optional[Dict] = None,
        ttl_seconds: int = 60
    ):
        """에이전트 등록"""
        if not self._client:
            return

        key = self.KEY_AGENT.format(agent_id=agent_id)
        data = {
            "id": agent_id,
            "department": department,
            "role": role,
            "status": status,
            "last_heartbeat": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        }

        try:
            await self._client.setex(key, ttl_seconds, json.dumps(data))
            # 활성 에이전트 목록에 추가
            await self._client.sadd(self.KEY_AGENTS_LIST, agent_id)
            logger.debug(f"Agent registered: {agent_id}")
        except Exception as e:
            logger.error(f"Failed to register agent: {e}")

    async def update_agent_heartbeat(self, agent_id: str, ttl_seconds: int = 60):
        """에이전트 하트비트 업데이트"""
        if not self._client:
            return

        key = self.KEY_AGENT.format(agent_id=agent_id)
        try:
            data = await self._client.get(key)
            if data:
                agent_data = json.loads(data)
                agent_data["last_heartbeat"] = datetime.utcnow().isoformat()
                await self._client.setex(key, ttl_seconds, json.dumps(agent_data))
        except Exception as e:
            logger.error(f"Failed to update heartbeat: {e}")

    async def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """에이전트 정보 조회"""
        if not self._client:
            return None

        key = self.KEY_AGENT.format(agent_id=agent_id)
        try:
            data = await self._client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to get agent: {e}")
            return None

    async def list_agents(self) -> List[Dict[str, Any]]:
        """활성 에이전트 목록 조회"""
        if not self._client:
            return []

        try:
            agent_ids = await self._client.smembers(self.KEY_AGENTS_LIST)
            agents = []
            for agent_id in agent_ids:
                agent_data = await self.get_agent(agent_id)
                if agent_data:
                    agents.append(agent_data)
                else:
                    # 만료된 에이전트 제거
                    await self._client.srem(self.KEY_AGENTS_LIST, agent_id)
            return agents
        except Exception as e:
            logger.error(f"Failed to list agents: {e}")
            return []

    async def set_agent_status(self, agent_id: str, status: str):
        """에이전트 상태 변경"""
        if not self._client:
            return

        key = self.KEY_AGENT.format(agent_id=agent_id)
        try:
            data = await self._client.get(key)
            if data:
                agent_data = json.loads(data)
                agent_data["status"] = status
                agent_data["last_updated"] = datetime.utcnow().isoformat()
                await self._client.set(key, json.dumps(agent_data))
        except Exception as e:
            logger.error(f"Failed to set agent status: {e}")

    async def set_agent_status(self, agent_id: str, status: str):
        """에이전트 상태 변경"""
        if not self._client:
            return

        key = self.KEY_AGENT.format(agent_id=agent_id)
        try:
            data = await self._client.get(key)
            if data:
                agent_data = json.loads(data)
                agent_data["status"] = status
                agent_data["last_updated"] = datetime.utcnow().isoformat()
                await self._client.set(key, json.dumps(agent_data))
        except Exception as e:
            logger.error(f"Failed to set agent status: {e}")

    # === 봇 상태 관리 ===

    KEY_BOT_STATUS = "oz:a2m:bot:{bot_id}:status"
    KEY_BOTS_LIST = "oz:a2m:bots:active"

    async def set_bot_status(
        self,
        bot_id: str,
        status: str,
        bot_type: str = "unknown",
        capital: float = 0,
        pnl: float = 0,
        trades: int = 0,
        mock_mode: bool = False,
        exchange: str = "unknown",
        symbol: str = "unknown",
        ttl_seconds: int = 30
    ):
        """봇 상태 저장"""
        if not self._client:
            return

        key = self.KEY_BOT_STATUS.format(bot_id=bot_id)
        data = {
            "bot_id": bot_id,
            "status": status,
            "type": bot_type,
            "capital": capital,
            "pnl": pnl,
            "trades": trades,
            "mock_mode": mock_mode,
            "exchange": exchange,
            "symbol": symbol,
            "last_update": datetime.utcnow().isoformat()
        }

        try:
            await self._client.setex(key, ttl_seconds, json.dumps(data))
            await self._client.sadd(self.KEY_BOTS_LIST, bot_id)
            logger.debug(f"Bot status saved: {bot_id} -> {status}")
        except Exception as e:
            logger.error(f"Failed to save bot status: {e}")

    async def get_bot_status(self, bot_id: str) -> Optional[Dict[str, Any]]:
        """봇 상태 조회"""
        if not self._client:
            return None

        key = self.KEY_BOT_STATUS.format(bot_id=bot_id)
        try:
            data = await self._client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to get bot status: {e}")
            return None

    async def list_bot_statuses(self) -> List[Dict[str, Any]]:
        """모든 봇 상태 조회"""
        if not self._client:
            return []

        try:
            bot_ids = await self._client.smembers(self.KEY_BOTS_LIST)
            bots = []
            for bot_id in bot_ids:
                bot_data = await self.get_bot_status(bot_id)
                if bot_data:
                    bots.append(bot_data)
                else:
                    await self._client.srem(self.KEY_BOTS_LIST, bot_id)
            return bots
        except Exception as e:
            logger.error(f"Failed to list bot statuses: {e}")
            return []

    # === 시장 스냅샷 ===

    async def set_market_snapshot(
        self,
        symbol: str,
        snapshot: Dict[str, Any],
        ttl_seconds: int = 10
    ):
        """시장 스냅샷 캐싱"""
        if not self._client:
            return

        key = self.KEY_MARKET_SNAPSHOT.format(symbol=symbol.upper())
        try:
            snapshot["timestamp"] = datetime.utcnow().isoformat()
            await self._client.setex(key, ttl_seconds, json.dumps(snapshot))
        except Exception as e:
            logger.error(f"Failed to cache snapshot: {e}")

    async def get_market_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """시장 스냅샷 조회"""
        if not self._client:
            return None

        key = self.KEY_MARKET_SNAPSHOT.format(symbol=symbol.upper())
        try:
            data = await self._client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to get snapshot: {e}")
            return None

    # === 시그널 캐싱 ===

    async def set_signal(
        self,
        symbol: str,
        signal_type: str,
        price: float,
        confidence: float,
        source: str,
        ttl_seconds: int = 300
    ):
        """트레이딩 시그널 캐싱"""
        if not self._client:
            return

        key = self.KEY_SIGNAL.format(symbol=symbol.upper())
        data = {
            "symbol": symbol.upper(),
            "signal": signal_type,
            "price": price,
            "confidence": confidence,
            "source": source,
            "timestamp": datetime.utcnow().isoformat()
        }

        try:
            await self._client.setex(key, ttl_seconds, json.dumps(data))
            logger.info(f"Signal cached: {symbol} {signal_type} @ {price}")
        except Exception as e:
            logger.error(f"Failed to cache signal: {e}")

    async def get_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        """시그널 조회"""
        if not self._client:
            return None

        key = self.KEY_SIGNAL.format(symbol=symbol.upper())
        try:
            data = await self._client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to get signal: {e}")
            return None

    # === 유틸리티 ===

    async def publish_to_stream(self, stream: str, data: Dict[str, Any]):
        """Redis Stream에 발행"""
        if not self._client:
            return

        try:
            await self._client.xadd(stream, {"data": json.dumps(data)})
        except Exception as e:
            logger.error(f"Failed to publish to stream: {e}")

    async def health_check(self) -> Dict[str, Any]:
        """Redis 상태 확인"""
        if not self._client:
            return {"status": "disconnected", "error": "Not connected"}

        try:
            start = datetime.utcnow()
            await self._client.ping()
            latency = (datetime.utcnow() - start).total_seconds() * 1000

            info = await self._client.info("server")
            return {
                "status": "connected",
                "latency_ms": round(latency, 2),
                "version": info.get("redis_version", "unknown"),
                "connected_clients": info.get("connected_clients", 0)
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}


# 전역 인스턴스
_redis_cache_instance: Optional[RedisCache] = None


def get_redis_cache(
    host: str = "localhost",
    port: int = 6380,
    db: int = 0
) -> RedisCache:
    """전역 RedisCache 인스턴스 가져오기"""
    global _redis_cache_instance
    if _redis_cache_instance is None:
        _redis_cache_instance = RedisCache(host=host, port=port, db=db)
    return _redis_cache_instance

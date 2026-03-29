"""Market data router with Redis cache integration."""

from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
from datetime import datetime

from lib.core import get_logger
from lib.cache import get_redis_cache

router = APIRouter()
logger = get_logger(__name__)

# Redis 캐시 인스턴스
_redis_cache = None


async def _get_cache():
    """Redis 캐시 인스턴스 가져오기 (지연 초기화)"""
    global _redis_cache
    if _redis_cache is None:
        _redis_cache = get_redis_cache(host="localhost", port=6379, db=0)
        await _redis_cache.connect()
    return _redis_cache


@router.get("/price/{symbol}")
async def get_price(symbol: str):
    """Get current price for symbol from Redis cache."""
    cache = await _get_cache()
    price_data = await cache.get_price(symbol)

    if price_data:
        return price_data

    # 캐시 미스 시 기본값 반환
    return {
        "symbol": symbol.upper(),
        "price": 0.0,
        "timestamp": datetime.utcnow().isoformat(),
        "source": "cache_miss",
    }


@router.get("/prices")
async def get_prices(symbols: Optional[List[str]] = Query(None)):
    """Get prices for multiple symbols from Redis cache."""
    symbols = symbols or ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]

    cache = await _get_cache()
    return await cache.get_prices(symbols)


@router.get("/orderbook/{symbol}")
async def get_orderbook(symbol: str, depth: int = 10):
    """Get orderbook for symbol from Redis cache."""
    cache = await _get_cache()
    orderbook = await cache.get_orderbook(symbol)

    if orderbook:
        # depth 제한 적용
        orderbook["bids"] = orderbook.get("bids", [])[:depth]
        orderbook["asks"] = orderbook.get("asks", [])[:depth]
        return orderbook

    # 캐시 미스
    return {
        "symbol": symbol.upper(),
        "bids": [],
        "asks": [],
        "timestamp": datetime.utcnow().isoformat(),
        "source": "cache_miss",
    }


@router.get("/snapshot/{symbol}")
async def get_market_snapshot(symbol: str):
    """Get market snapshot for symbol."""
    cache = await _get_cache()
    snapshot = await cache.get_market_snapshot(symbol)

    if snapshot:
        return snapshot

    return {
        "symbol": symbol.upper(),
        "error": "No snapshot available",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/signal/{symbol}")
async def get_signal(symbol: str):
    """Get latest trading signal for symbol."""
    cache = await _get_cache()
    signal = await cache.get_signal(symbol)

    if signal:
        return signal

    return {
        "symbol": symbol.upper(),
        "signal": None,
        "message": "No active signal",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/subscribe")
async def subscribe_market_data(symbols: List[str]):
    """Subscribe to market data updates via MQTT."""
    from lib.messaging import get_mqtt_client

    mqtt = get_mqtt_client()
    for symbol in symbols:
        await mqtt.publish(
            "oz_a2m/market/subscribe",
            {"symbol": symbol.upper(), "action": "subscribe"}
        )
        logger.info(f"Subscribed to market data: {symbol}")

    return {"status": "subscribed", "symbols": [s.upper() for s in symbols]}


@router.post("/cache/price")
async def cache_price(symbol: str, price: float, source: str = "gateway"):
    """Manually cache a price (for internal use)."""
    cache = await _get_cache()
    await cache.set_price(symbol, price, source)
    return {"status": "cached", "symbol": symbol.upper(), "price": price}


@router.post("/cache/orderbook")
async def cache_orderbook(
    symbol: str,
    bids: List[List[float]],
    asks: List[List[float]],
    source: str = "gateway"
):
    """Manually cache orderbook (for internal use)."""
    cache = await _get_cache()
    await cache.set_orderbook(symbol, bids, asks, source)
    return {
        "status": "cached",
        "symbol": symbol.upper(),
        "bid_count": len(bids),
        "ask_count": len(asks)
    }


@router.get("/health/redis")
async def redis_health():
    """Check Redis connection health."""
    cache = await _get_cache()
    return await cache.health_check()

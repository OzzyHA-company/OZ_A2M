"""Market data router."""

from fastapi import APIRouter, Query
from typing import List, Optional

from lib.core import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get("/price/{symbol}")
async def get_price(symbol: str):
    """Get current price for symbol."""
    # TODO: Implement price fetching from Redis/cache
    return {
        "symbol": symbol.upper(),
        "price": 0.0,
        "timestamp": "2024-03-28T00:00:00Z",
        "source": "gateway",
    }


@router.get("/prices")
async def get_prices(symbols: Optional[List[str]] = Query(None)):
    """Get prices for multiple symbols."""
    symbols = symbols or ["BTC/USDT", "ETH/USDT"]
    return {
        "prices": [
            {"symbol": s.upper(), "price": 0.0} for s in symbols
        ]
    }


@router.get("/orderbook/{symbol}")
async def get_orderbook(symbol: str, depth: int = 10):
    """Get orderbook for symbol."""
    return {
        "symbol": symbol.upper(),
        "bids": [],
        "asks": [],
        "timestamp": "2024-03-28T00:00:00Z",
    }


@router.post("/subscribe")
async def subscribe_market_data(symbols: List[str]):
    """Subscribe to market data updates."""
    from lib.messaging import get_mqtt_client

    mqtt = get_mqtt_client()
    for symbol in symbols:
        await mqtt.publish(
            "oz_a2m/market/subscribe",
            {"symbol": symbol.upper(), "action": "subscribe"}
        )

    return {"status": "subscribed", "symbols": [s.upper() for s in symbols]}

"""
OZ_A2M Phase 5: 제7부서 운영팀 - 봇 템플릿

4가지 전략 봇 템플릿 제공
"""

from .scalping_bot import ScalpingBot
from .trend_following_bot import TrendFollowingBot
from .market_making_bot import MarketMakingBot
from .arbitrage_bot import ArbitrageBot

__all__ = [
    "ScalpingBot",
    "TrendFollowingBot",
    "MarketMakingBot",
    "ArbitrageBot"
]

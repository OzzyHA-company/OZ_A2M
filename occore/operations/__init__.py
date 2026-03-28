"""
OZ_A2M Phase 5: 제7부서 운영팀 (Operations Team)

실제 거래 실행 및 봇 운영을 담당하는 부서
- BotManager: 봇 생명주기 관리
- ExecutionEngine: 주문 실행
- PositionManager: 포지션 관리
- RiskController: 리스크 관리/Kill Switch
- ExchangeConnector: 거래소 연결
"""

from .models import (
    Position, Order, Trade,
    OrderSide, OrderType, OrderStatus,
    PositionSide, BotStatus, BotStrategy,
    RiskLimit, BotConfig, DailyStats
)
from .exchange_connector import ExchangeConnector, ExchangeManager, MockExchangeConnector
from .execution_engine import ExecutionEngine, create_market_buy, create_market_sell
from .position_manager import PositionManager
from .risk_controller import RiskController, RiskEvent, RiskAlert
from .bot_manager import BotManager, BaseBot

# 봇 템플릿
from .templates import ScalpingBot, TrendFollowingBot, MarketMakingBot, ArbitrageBot

__all__ = [
    # Models
    "Position", "Order", "Trade",
    "OrderSide", "OrderType", "OrderStatus",
    "PositionSide", "BotStatus", "BotStrategy",
    "RiskLimit", "BotConfig", "DailyStats",
    # Connectors
    "ExchangeConnector", "ExchangeManager", "MockExchangeConnector",
    # Engines
    "ExecutionEngine", "create_market_buy", "create_market_sell",
    # Managers
    "PositionManager", "RiskController", "BotManager",
    # Risk
    "RiskEvent", "RiskAlert",
    # Bot
    "BaseBot",
    # Templates
    "ScalpingBot", "TrendFollowingBot", "MarketMakingBot", "ArbitrageBot"
]

__version__ = "1.0.0"

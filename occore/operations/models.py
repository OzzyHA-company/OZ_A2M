"""
OZ_A2M Phase 5: 제7부서 운영팀 - 데이터 모델

Position, Order, Trade, RiskLimit, BotConfig 등
운영팀 핵심 데이터 모델 정의
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field


class OrderSide(str, Enum):
    """주문 방향"""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """주문 유형"""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class OrderStatus(str, Enum):
    """주문 상태"""
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PositionSide(str, Enum):
    """포지션 방향"""
    LONG = "long"
    SHORT = "short"
    NONE = "none"


class BotStatus(str, Enum):
    """봇 상태"""
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class BotStrategy(str, Enum):
    """봇 전략 유형"""
    SCALPING = "scalping"
    TREND_FOLLOWING = "trend_following"
    MARKET_MAKING = "market_making"
    ARBITRAGE = "arbitrage"


@dataclass
class Position:
    """포지션 데이터 모델"""
    id: str
    symbol: str
    side: PositionSide
    amount: Decimal
    entry_price: Decimal
    mark_price: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    leverage: float = 1.0
    margin: Decimal = Decimal("0")
    exchange: str = "binance"
    bot_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side.value,
            "amount": str(self.amount),
            "entry_price": str(self.entry_price),
            "mark_price": str(self.mark_price),
            "unrealized_pnl": str(self.unrealized_pnl),
            "realized_pnl": str(self.realized_pnl),
            "leverage": self.leverage,
            "margin": str(self.margin),
            "exchange": self.exchange,
            "bot_id": self.bot_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata
        }

    def update_pnl(self, current_price: Decimal):
        """미실현 손익 업데이트"""
        if self.side == PositionSide.LONG:
            self.unrealized_pnl = (current_price - self.entry_price) * self.amount
        elif self.side == PositionSide.SHORT:
            self.unrealized_pnl = (self.entry_price - current_price) * self.amount
        self.mark_price = current_price
        self.updated_at = datetime.utcnow()

    @property
    def pnl_percent(self) -> float:
        """손익률 (%)"""
        if self.entry_price == 0:
            return 0.0
        return float((self.mark_price - self.entry_price) / self.entry_price * 100)


@dataclass
class Order:
    """주문 데이터 모델"""
    id: str
    order_id: Optional[str]  # 거래소 주문 ID
    symbol: str
    side: OrderSide
    order_type: OrderType
    amount: Decimal
    price: Optional[Decimal] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_amount: Decimal = Decimal("0")
    remaining_amount: Decimal = Decimal("0")
    avg_fill_price: Decimal = Decimal("0")
    fee: Decimal = Decimal("0")
    fee_currency: str = "USDT"
    exchange: str = "binance"
    bot_id: Optional[str] = None
    position_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "id": self.id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "amount": str(self.amount),
            "price": str(self.price) if self.price else None,
            "status": self.status.value,
            "filled_amount": str(self.filled_amount),
            "remaining_amount": str(self.remaining_amount),
            "avg_fill_price": str(self.avg_fill_price),
            "fee": str(self.fee),
            "fee_currency": self.fee_currency,
            "exchange": self.exchange,
            "bot_id": self.bot_id,
            "position_id": self.position_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata
        }

    def update_fill(self, filled: Decimal, price: Decimal, fee: Decimal):
        """체결 업데이트"""
        self.filled_amount += filled
        self.remaining_amount = self.amount - self.filled_amount
        self.avg_fill_price = (
            (self.avg_fill_price * (self.filled_amount - filled) + price * filled)
            / self.filled_amount
        )
        self.fee += fee
        self.updated_at = datetime.utcnow()

        if self.filled_amount >= self.amount:
            self.status = OrderStatus.FILLED
        elif self.filled_amount > 0:
            self.status = OrderStatus.PARTIALLY_FILLED


@dataclass
class Trade:
    """체결(Trade) 데이터 모델"""
    id: str
    trade_id: Optional[str]  # 거래소 체결 ID
    order_id: str
    symbol: str
    side: OrderSide
    amount: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    exchange: str = "binance"
    bot_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "id": self.id,
            "trade_id": self.trade_id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "amount": str(self.amount),
            "price": str(self.price),
            "fee": str(self.fee),
            "fee_currency": self.fee_currency,
            "exchange": self.exchange,
            "bot_id": self.bot_id,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }

    @property
    def total_value(self) -> Decimal:
        """총 거래 가치"""
        return self.amount * self.price

    @property
    def net_value(self) -> Decimal:
        """수수료 차감 순거래 가치"""
        return self.total_value - self.fee


@dataclass
class RiskLimit:
    """리스크 한도 설정"""
    id: str
    bot_id: Optional[str]  # None이면 전역 설정
    exchange: Optional[str]  # None이면 모든 거래소

    # 손실 한도
    max_daily_loss: Decimal = Decimal("-1000")  # 일일 최대 손실 (USDT)
    max_trade_loss: Decimal = Decimal("-100")   # 거래당 최대 손실 (USDT)

    # 포지션 한도
    max_position_size: Decimal = Decimal("1.0")  # 최대 포지션 크기 (BTC 등)
    max_total_position: Decimal = Decimal("10000")  # 총 포지션 가치 한도 (USDT)

    # 레버리지 한도
    max_leverage: float = 10.0

    # 주문 한도
    max_orders_per_minute: int = 10
    max_orders_per_day: int = 1000

    # 자산 한도
    max_capital_usage_percent: float = 80.0  # 최대 자본 사용률 (%)

    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "id": self.id,
            "bot_id": self.bot_id,
            "exchange": self.exchange,
            "max_daily_loss": str(self.max_daily_loss),
            "max_trade_loss": str(self.max_trade_loss),
            "max_position_size": str(self.max_position_size),
            "max_total_position": str(self.max_total_position),
            "max_leverage": self.max_leverage,
            "max_orders_per_minute": self.max_orders_per_minute,
            "max_orders_per_day": self.max_orders_per_day,
            "max_capital_usage_percent": self.max_capital_usage_percent,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }


@dataclass
class BotConfig:
    """봇 설정"""
    id: str
    name: str
    strategy: BotStrategy
    status: BotStatus = BotStatus.IDLE

    # 거래 설정
    exchange: str = "binance"
    symbol: str = "BTC/USDT"
    timeframe: str = "1m"

    # 전략 파라미터
    strategy_params: Dict[str, Any] = field(default_factory=dict)

    # 리스크 설정
    risk_limit_id: Optional[str] = None

    # 자본 설정
    initial_capital: Decimal = Decimal("1000")
    current_capital: Decimal = Decimal("1000")

    # 실행 설정
    dry_run: bool = True  # 모의 거래 모드
    auto_restart: bool = False
    max_runtime_hours: Optional[float] = None

    # 알림 설정
    notify_on_trade: bool = True
    notify_on_error: bool = True
    notify_on_risk: bool = True

    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_run_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "id": self.id,
            "name": self.name,
            "strategy": self.strategy.value,
            "status": self.status.value,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "strategy_params": self.strategy_params,
            "risk_limit_id": self.risk_limit_id,
            "initial_capital": str(self.initial_capital),
            "current_capital": str(self.current_capital),
            "dry_run": self.dry_run,
            "auto_restart": self.auto_restart,
            "max_runtime_hours": self.max_runtime_hours,
            "notify_on_trade": self.notify_on_trade,
            "notify_on_error": self.notify_on_error,
            "notify_on_risk": self.notify_on_risk,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "metadata": self.metadata
        }


@dataclass
class DailyStats:
    """일일 거래 통계"""
    date: str  # YYYY-MM-DD
    bot_id: Optional[str]
    exchange: str

    # 거래 통계
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    # 금액 통계
    gross_profit: Decimal = Decimal("0")
    gross_loss: Decimal = Decimal("0")
    net_pnl: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")

    # 포지션 통계
    total_volume: Decimal = Decimal("0")
    max_position_size: Decimal = Decimal("0")

    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "date": self.date,
            "bot_id": self.bot_id,
            "exchange": self.exchange,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "gross_profit": str(self.gross_profit),
            "gross_loss": str(self.gross_loss),
            "net_pnl": str(self.net_pnl),
            "total_fees": str(self.total_fees),
            "total_volume": str(self.total_volume),
            "max_position_size": str(self.max_position_size),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @property
    def win_rate(self) -> float:
        """승률 (%)"""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100

    @property
    def profit_factor(self) -> float:
        """수익 팩터"""
        if self.gross_loss == 0:
            return float('inf') if self.gross_profit > 0 else 0.0
        return float(abs(self.gross_profit / self.gross_loss))

    def add_trade(self, trade: Trade, realized_pnl: Decimal):
        """거래 추가"""
        self.total_trades += 1
        self.total_volume += trade.total_value
        self.total_fees += trade.fee

        if realized_pnl > 0:
            self.winning_trades += 1
            self.gross_profit += realized_pnl
        else:
            self.losing_trades += 1
            self.gross_loss += realized_pnl

        self.net_pnl = self.gross_profit + self.gross_loss
        self.updated_at = datetime.utcnow()


# SQLAlchemy용 테이블 정의 (선택사항)
try:
    from sqlalchemy import Column, String, DateTime, Numeric, Integer, Float, Boolean, JSON
    from sqlalchemy.ext.declarative import declarative_base

    Base = declarative_base()

    class PositionORM(Base):
        """Position SQLAlchemy 모델"""
        __tablename__ = "positions"

        id = Column(String(36), primary_key=True)
        symbol = Column(String(20), nullable=False)
        side = Column(String(10), nullable=False)
        amount = Column(Numeric(20, 8), nullable=False)
        entry_price = Column(Numeric(20, 8), nullable=False)
        mark_price = Column(Numeric(20, 8), default=0)
        unrealized_pnl = Column(Numeric(20, 8), default=0)
        realized_pnl = Column(Numeric(20, 8), default=0)
        leverage = Column(Float, default=1.0)
        margin = Column(Numeric(20, 8), default=0)
        exchange = Column(String(20), default="binance")
        bot_id = Column(String(36), nullable=True)
        created_at = Column(DateTime, default=datetime.utcnow)
        updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
        metadata_json = Column(JSON, default=dict)

    class OrderORM(Base):
        """Order SQLAlchemy 모델"""
        __tablename__ = "orders"

        id = Column(String(36), primary_key=True)
        order_id = Column(String(50), nullable=True)
        symbol = Column(String(20), nullable=False)
        side = Column(String(10), nullable=False)
        order_type = Column(String(20), nullable=False)
        amount = Column(Numeric(20, 8), nullable=False)
        price = Column(Numeric(20, 8), nullable=True)
        status = Column(String(20), default="pending")
        filled_amount = Column(Numeric(20, 8), default=0)
        remaining_amount = Column(Numeric(20, 8), default=0)
        avg_fill_price = Column(Numeric(20, 8), default=0)
        fee = Column(Numeric(20, 8), default=0)
        fee_currency = Column(String(10), default="USDT")
        exchange = Column(String(20), default="binance")
        bot_id = Column(String(36), nullable=True)
        position_id = Column(String(36), nullable=True)
        created_at = Column(DateTime, default=datetime.utcnow)
        updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
        metadata_json = Column(JSON, default=dict)

except ImportError:
    pass  # SQLAlchemy 미설치 시 무시


if __name__ == "__main__":
    # 테스트
    pos = Position(
        id="pos-001",
        symbol="BTC/USDT",
        side=PositionSide.LONG,
        amount=Decimal("0.1"),
        entry_price=Decimal("50000"),
        mark_price=Decimal("51000")
    )
    pos.update_pnl(Decimal("51000"))
    print(f"Position PnL: {pos.unrealized_pnl} ({pos.pnl_percent}%)")

    order = Order(
        id="order-001",
        order_id=None,
        symbol="BTC/USDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        amount=Decimal("0.1")
    )
    print(f"Order status: {order.status.value}")

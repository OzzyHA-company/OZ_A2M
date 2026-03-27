"""
제5부서: 일일 성과분석팀 (PnL Center) - 모델 정의

수익/손실 계산 및 성과 분석에 사용되는 데이터 모델들을 정의합니다.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Any


class PnLType(Enum):
    """PnL 유형"""
    REALIZED = "realized"       # 실현 손익
    UNREALIZED = "unrealized"   # 미실현 손익


class TradeStatus(Enum):
    """거래 상태"""
    OPEN = "open"               # 포지션 보유 중
    CLOSED = "closed"           # 포지션 종료
    PARTIAL = "partial"         # 부분 청산


class PositionSide(Enum):
    """포지션 방향"""
    LONG = "long"
    SHORT = "short"


@dataclass
class TradeRecord:
    """개별 거래 레코드"""
    trade_id: str
    symbol: str
    side: PositionSide
    entry_price: Decimal
    quantity: Decimal
    entry_time: datetime
    exit_price: Optional[Decimal] = None
    exit_time: Optional[datetime] = None
    fees: Decimal = Decimal('0')
    slippage: Decimal = Decimal('0')
    pnl: Decimal = field(init=False)
    pnl_percent: float = field(init=False)
    status: TradeStatus = field(default=TradeStatus.OPEN)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.exit_price is not None and self.entry_price is not None:
            if self.side == PositionSide.LONG:
                self.pnl = (self.exit_price - self.entry_price) * self.quantity
            else:  # SHORT
                self.pnl = (self.entry_price - self.exit_price) * self.quantity

            # 수수료/슬리피지 차감
            self.pnl -= (self.fees + self.slippage)

            # 수익률 계산
            cost = self.entry_price * self.quantity
            if cost != 0:
                self.pnl_percent = float(self.pnl / cost) * 100
            else:
                self.pnl_percent = 0.0

            self.status = TradeStatus.CLOSED
        else:
            self.pnl = Decimal('0')
            self.pnl_percent = 0.0

    def update_exit(
        self,
        exit_price: Decimal,
        exit_time: datetime,
        fees: Optional[Decimal] = None,
        slippage: Optional[Decimal] = None
    ):
        """포지션 종료 정보 업데이트"""
        self.exit_price = exit_price
        self.exit_time = exit_time
        if fees is not None:
            self.fees += fees  # 합산으로 변경
        if slippage is not None:
            self.slippage += slippage  # 합산으로 변경
        self.__post_init__()


@dataclass
class DailyPnL:
    """일일 손익 집계"""
    date: date
    realized_pnl: Decimal = Decimal('0')
    unrealized_pnl: Decimal = Decimal('0')
    fees: Decimal = Decimal('0')
    net_pnl: Decimal = field(init=False)
    gross_pnl: Decimal = field(init=False)
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = field(init=False)
    avg_trade_pnl: Decimal = field(init=False)
    largest_win: Decimal = Decimal('0')
    largest_loss: Decimal = Decimal('0')
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.gross_pnl = self.realized_pnl + self.unrealized_pnl
        self.net_pnl = self.gross_pnl - self.fees

        if self.trade_count > 0:
            self.win_rate = (self.win_count / self.trade_count) * 100
            self.avg_trade_pnl = self.net_pnl / self.trade_count
        else:
            self.win_rate = 0.0
            self.avg_trade_pnl = Decimal('0')

    def add_trade(self, trade: TradeRecord):
        """거래 추가 및 집계 업데이트"""
        if trade.status == TradeStatus.CLOSED:
            self.realized_pnl += trade.pnl
            self.trade_count += 1

            if trade.pnl > 0:
                self.win_count += 1
                if trade.pnl > self.largest_win:
                    self.largest_win = trade.pnl
            elif trade.pnl < 0:
                self.loss_count += 1
                if trade.pnl < self.largest_loss:
                    self.largest_loss = trade.pnl
        else:
            self.unrealized_pnl += trade.pnl

        self.fees += trade.fees
        self.__post_init__()


@dataclass
class PerformanceMetrics:
    """성과 지표"""
    period_start: date
    period_end: date
    total_return: Decimal = Decimal('0')
    total_return_percent: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_amount: Decimal = Decimal('0')
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: Decimal = Decimal('0')
    avg_loss: Decimal = Decimal('0')
    avg_win_loss_ratio: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    break_even_trades: int = 0
    volatility: float = 0.0
    calmar_ratio: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionSummary:
    """포지션 요약"""
    symbol: str
    side: PositionSide
    quantity: Decimal
    avg_entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal = field(init=False)
    unrealized_pnl_percent: float = field(init=False)

    def __post_init__(self):
        if self.side == PositionSide.LONG:
            self.unrealized_pnl = (self.current_price - self.avg_entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.avg_entry_price - self.current_price) * self.quantity

        if self.avg_entry_price != 0:
            self.unrealized_pnl_percent = float(
                self.unrealized_pnl / (self.avg_entry_price * self.quantity)
            ) * 100
        else:
            self.unrealized_pnl_percent = 0.0


# 설정 상수
DEFAULT_PNL_CONFIG = {
    'realized_pnl_threshold': Decimal('0.01'),
    'daily_reset_hour': 0,  # UTC 기준 자정
    'max_trade_history': 10000,
    'sharpe_risk_free_rate': 0.02,  # 연간 무위험 수익률 2%
    'report_format': 'table',  # 'json', 'csv', 'table'
    'decimal_precision': 8,
}

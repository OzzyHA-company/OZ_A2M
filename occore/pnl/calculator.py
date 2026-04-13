"""
제5부서: 일일 성과분석팀 (PnL Center) - 수익 계산기

거래 수익/손실 계산 및 일일 집계를 담당합니다.
"""

import logging
import threading
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Optional, Any

from .models import (
    TradeRecord, DailyPnL, PositionSummary,
    PositionSide, TradeStatus,
    DEFAULT_PNL_CONFIG,
)
from .exceptions import (
    TradeNotFoundError, InvalidTradeError, CalculationError,
)
from .config import DEFAULT_PNL_CONFIG

logger = logging.getLogger(__name__)


class ProfitCalculator:
    """수익/손실 계산기"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or DEFAULT_PNL_CONFIG.copy()
        self._trades: Dict[str, TradeRecord] = {}
        self._daily_pnl: Dict[date, DailyPnL] = {}
        self._open_positions: Dict[str, PositionSummary] = {}
        self._lock = threading.RLock()

    def add_trade(
        self,
        trade_id: str,
        symbol: str,
        side: PositionSide,
        entry_price: Decimal,
        quantity: Decimal,
        entry_time: Optional[datetime] = None,
        fees: Optional[Decimal] = None,
        slippage: Optional[Decimal] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TradeRecord:
        """새로운 거래 추가"""
        if trade_id in self._trades:
            raise InvalidTradeError(f"Trade '{trade_id}' already exists")

        if quantity <= 0:
            raise InvalidTradeError("Quantity must be positive", field="quantity")

        if entry_price <= 0:
            raise InvalidTradeError("Entry price must be positive", field="entry_price")

        trade = TradeRecord(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            entry_time=entry_time or datetime.utcnow(),
            fees=fees or Decimal('0'),
            slippage=slippage or Decimal('0'),
            metadata=metadata or {},
        )

        with self._lock:
            self._trades[trade_id] = trade
            self._update_position(trade)

        logger.info(f"Added trade {trade_id}: {symbol} {side.value} {quantity} @ {entry_price}")
        return trade

    def close_trade(
        self,
        trade_id: str,
        exit_price: Decimal,
        exit_time: Optional[datetime] = None,
        fees: Optional[Decimal] = None,
        slippage: Optional[Decimal] = None,
    ) -> TradeRecord:
        """거래 종료"""
        if trade_id not in self._trades:
            raise TradeNotFoundError(trade_id)

        trade = self._trades[trade_id]

        if trade.status == TradeStatus.CLOSED:
            raise InvalidTradeError(f"Trade '{trade_id}' is already closed")

        trade.update_exit(
            exit_price=exit_price,
            exit_time=exit_time or datetime.utcnow(),
            fees=fees,
            slippage=slippage,
        )

        with self._lock:
            # 일일 PnL 업데이트
            trade_date = trade.exit_time.date()
            if trade_date not in self._daily_pnl:
                self._daily_pnl[trade_date] = DailyPnL(date=trade_date)

            self._daily_pnl[trade_date].add_trade(trade)
            self._update_position(trade, closing=True)

        logger.info(
            f"Closed trade {trade_id}: PnL={trade.pnl:.2f} ({trade.pnl_percent:.2f}%)"
        )
        return trade

    def get_trade(self, trade_id: str) -> TradeRecord:
        """거래 조회"""
        if trade_id not in self._trades:
            raise TradeNotFoundError(trade_id)
        return self._trades[trade_id]

    def get_all_trades(self) -> List[TradeRecord]:
        """모든 거래 조회"""
        return list(self._trades.values())

    def get_open_trades(self) -> List[TradeRecord]:
        """미체결 거래 조회"""
        return [
            trade for trade in self._trades.values()
            if trade.status == TradeStatus.OPEN
        ]

    def get_closed_trades(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[TradeRecord]:
        """기간별 종료된 거래 조회"""
        trades = [
            trade for trade in self._trades.values()
            if trade.status == TradeStatus.CLOSED
        ]

        if start_date:
            trades = [t for t in trades if t.exit_time and t.exit_time.date() >= start_date]
        if end_date:
            trades = [t for t in trades if t.exit_time and t.exit_time.date() <= end_date]

        return trades

    def get_daily_pnl(self, target_date: date) -> Optional[DailyPnL]:
        """특정 일자의 PnL 조회"""
        return self._daily_pnl.get(target_date)

    def get_daily_pnl_range(
        self,
        start_date: date,
        end_date: date,
    ) -> List[DailyPnL]:
        """기간별 일일 PnL 조회"""
        return [
            pnl for pnl_date, pnl in sorted(self._daily_pnl.items())
            if start_date <= pnl_date <= end_date
        ]

    def get_open_positions(self) -> List[PositionSummary]:
        """현재 보유 포지션 조회"""
        return list(self._open_positions.values())

    def update_position_price(self, symbol: str, current_price: Decimal):
        """포지션 현재가 업데이트 (미실현 손익 계산용)"""
        if symbol in self._open_positions:
            pos = self._open_positions[symbol]
            pos.current_price = current_price
            # 재계산
            pos.__post_init__()

    def get_total_realized_pnl(self) -> Decimal:
        """총 실현 손익"""
        return sum(
            (daily.realized_pnl for daily in self._daily_pnl.values()),
            Decimal('0')
        )

    def get_total_unrealized_pnl(self) -> Decimal:
        """총 미실현 손익"""
        return sum(
            (pos.unrealized_pnl for pos in self._open_positions.values()),
            Decimal('0')
        )

    def get_total_fees(self) -> Decimal:
        """총 수수료"""
        return sum(
            (daily.fees for daily in self._daily_pnl.values()),
            Decimal('0')
        )

    def _update_position(self, trade: TradeRecord, closing: bool = False):
        """포지션 상태 업데이트"""
        symbol = trade.symbol

        if closing:
            # 포지션 감소 또는 제거 로직 (간단화)
            if symbol in self._open_positions:
                del self._open_positions[symbol]
        else:
            # 새 포지션 또는 추가
            self._open_positions[symbol] = PositionSummary(
                symbol=symbol,
                side=trade.side,
                quantity=trade.quantity,
                avg_entry_price=trade.entry_price,
                current_price=trade.entry_price,
            )

    def clear_history(self, before_date: Optional[date] = None):
        """거래 이력 정리"""
        with self._lock:
            if before_date:
                self._daily_pnl = {
                    d: pnl for d, pnl in self._daily_pnl.items()
                    if d >= before_date
                }
            else:
                self._daily_pnl.clear()
                self._trades.clear()
                self._open_positions.clear()


# 싱글톤 인스턴스
_calculator_instance: Optional[ProfitCalculator] = None


def get_calculator() -> ProfitCalculator:
    """ProfitCalculator 싱글톤 인스턴스 가져오기"""
    global _calculator_instance
    if _calculator_instance is None:
        _calculator_instance = ProfitCalculator()
    return _calculator_instance


def init_calculator(config: Optional[Dict[str, Any]] = None) -> ProfitCalculator:
    """ProfitCalculator 초기화"""
    global _calculator_instance
    _calculator_instance = ProfitCalculator(config=config)
    return _calculator_instance


# 호환성 별칭
PnLCalculator = ProfitCalculator

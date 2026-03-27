"""
제5부서: 일일 성과분석팀 (PnL Center) - 성과 분석기

샤프 비율, MDD, 승률 등 포트폴리오 성과 지표를 계산합니다.
"""

import logging
import statistics
import threading
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any

from .models import (
    TradeRecord, DailyPnL, PerformanceMetrics,
    DEFAULT_PNL_CONFIG,
)
from .exceptions import InsufficientDataError, CalculationError

logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """성과 분석기"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or DEFAULT_PNL_CONFIG.copy()

    def calculate_sharpe_ratio(
        self,
        returns: List[float],
        risk_free_rate: Optional[float] = None,
        periods_per_year: int = 252,
    ) -> float:
        """
        샤프 비율 계산

        Args:
            returns: 수익률 리스트 (일간/월간 등)
            risk_free_rate: 무위험 수익률 (연간)
            periods_per_year: 연간 기간 수 (주식 252, 암호화폐 365)

        Returns:
            샤프 비율
        """
        if len(returns) < 2:
            raise InsufficientDataError(
                "Sharpe ratio", required=2, actual=len(returns)
            )

        rf = risk_free_rate or self.config.get('sharpe_risk_free_rate', 0.02)
        rf_per_period = rf / periods_per_year

        avg_return = statistics.mean(returns)

        try:
            std_return = statistics.stdev(returns)
        except statistics.StatisticsError:
            return 0.0

        if std_return == 0:
            return 0.0

        sharpe = (avg_return - rf_per_period) / std_return
        annualized_sharpe = sharpe * (periods_per_year ** 0.5)

        return annualized_sharpe

    def calculate_sortino_ratio(
        self,
        returns: List[float],
        risk_free_rate: Optional[float] = None,
        periods_per_year: int = 252,
    ) -> float:
        """
        소티노 비율 계산 (하방 위험만 고려)
        """
        if len(returns) < 2:
            raise InsufficientDataError(
                "Sortino ratio", required=2, actual=len(returns)
            )

        rf = risk_free_rate or self.config.get('sharpe_risk_free_rate', 0.02)
        rf_per_period = rf / periods_per_year

        avg_return = statistics.mean(returns)

        # 하방 편차만 계산
        downside_returns = [r for r in returns if r < rf_per_period]
        if not downside_returns:
            return float('inf')  # 하방 위험 없음

        downside_std = (sum((r - rf_per_period) ** 2 for r in downside_returns) / len(downside_returns)) ** 0.5

        if downside_std == 0:
            return float('inf')

        sortino = (avg_return - rf_per_period) / downside_std
        annualized_sortino = sortino * (periods_per_year ** 0.5)

        return annualized_sortino

    def calculate_max_drawdown(
        self,
        equity_curve: List[Decimal],
    ) -> tuple[float, Decimal]:
        """
        최대 낙폭 (MDD) 계산

        Returns:
            (MDD 비율 %, MDD 금액)
        """
        if len(equity_curve) < 2:
            raise InsufficientDataError(
                "Max drawdown", required=2, actual=len(equity_curve)
            )

        max_dd = Decimal('0')
        max_dd_percent = 0.0
        peak = equity_curve[0]

        for equity in equity_curve:
            if equity > peak:
                peak = equity

            drawdown = peak - equity
            drawdown_percent = float(drawdown / peak) * 100 if peak != 0 else 0

            if drawdown > max_dd:
                max_dd = drawdown
                max_dd_percent = drawdown_percent

        return max_dd_percent, max_dd

    def calculate_win_rate(self, trades: List[TradeRecord]) -> float:
        """승률 계산"""
        if not trades:
            return 0.0

        closed_trades = [t for t in trades if t.status.value == 'closed']
        if not closed_trades:
            return 0.0

        wins = sum(1 for t in closed_trades if t.pnl > 0)
        return (wins / len(closed_trades)) * 100

    def calculate_profit_factor(self, trades: List[TradeRecord]) -> float:
        """수익 팩터 계산 (총 수익 / 총 손실)"""
        closed_trades = [t for t in trades if t.status.value == 'closed']

        total_gains = sum(float(t.pnl) for t in closed_trades if t.pnl > 0)
        total_losses = abs(sum(float(t.pnl) for t in closed_trades if t.pnl < 0))

        if total_losses == 0:
            return float('inf') if total_gains > 0 else 0.0

        return total_gains / total_losses

    def calculate_volatility(
        self,
        returns: List[float],
        periods_per_year: int = 252,
    ) -> float:
        """변동성 계산 (연간화)"""
        if len(returns) < 2:
            return 0.0

        try:
            std = statistics.stdev(returns)
        except statistics.StatisticsError:
            return 0.0

        return std * (periods_per_year ** 0.5)

    def calculate_calmar_ratio(
        self,
        annual_return: float,
        max_drawdown: float,
    ) -> float:
        """Calmar 비율 계산 (연간 수익률 / MDD)"""
        if max_drawdown == 0:
            return float('inf') if annual_return > 0 else 0.0

        return annual_return / abs(max_drawdown)

    def analyze_trades(
        self,
        trades: List[TradeRecord],
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
    ) -> PerformanceMetrics:
        """
        거래 리스트로부터 종합 성과 분석
        """
        closed_trades = [t for t in trades if t.status.value == 'closed']

        if not closed_trades:
            return PerformanceMetrics(
                period_start=period_start or date.today(),
                period_end=period_end or date.today(),
            )

        # 기간 설정
        if not period_start:
            period_start = min(t.exit_time.date() for t in closed_trades)
        if not period_end:
            period_end = max(t.exit_time.date() for t in closed_trades)

        # 기본 통계
        total_pnl = sum(t.pnl for t in closed_trades)
        initial_equity = Decimal('10000')  # 기준 자본 (config에서 가져올 수 있음)
        total_return_percent = float(total_pnl / initial_equity) * 100

        # 승/패
        wins = [t for t in closed_trades if t.pnl > 0]
        losses = [t for t in closed_trades if t.pnl < 0]
        break_evens = [t for t in closed_trades if t.pnl == 0]

        # 평균 승/패
        avg_win = sum(t.pnl for t in wins) / len(wins) if wins else Decimal('0')
        avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else Decimal('0')

        # 수익률 리스트 (일간 가정)
        returns = [float(t.pnl_percent / 100) for t in closed_trades]

        # 샤프 비율
        try:
            sharpe = self.calculate_sharpe_ratio(returns)
        except InsufficientDataError:
            sharpe = 0.0

        # 소티노 비율
        try:
            sortino = self.calculate_sortino_ratio(returns)
        except InsufficientDataError:
            sortino = 0.0

        # MDD 계산
        equity_curve = [initial_equity]
        for trade in closed_trades:
            equity_curve.append(equity_curve[-1] + trade.pnl)

        try:
            mdd_percent, mdd_amount = self.calculate_max_drawdown(equity_curve)
        except InsufficientDataError:
            mdd_percent, mdd_amount = 0.0, Decimal('0')

        # 기타 지표
        win_rate = self.calculate_win_rate(trades)
        profit_factor = self.calculate_profit_factor(trades)
        volatility = self.calculate_volatility(returns)
        calmar = self.calculate_calmar_ratio(total_return_percent, mdd_percent)

        # 승패 비율
        win_loss_ratio = float(avg_win / abs(avg_loss)) if avg_loss != 0 else float('inf')

        return PerformanceMetrics(
            period_start=period_start,
            period_end=period_end,
            total_return=total_pnl,
            total_return_percent=total_return_percent,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=mdd_percent,
            max_drawdown_amount=mdd_amount,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_win_loss_ratio=win_loss_ratio,
            total_trades=len(closed_trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            break_even_trades=len(break_evens),
            volatility=volatility,
            calmar_ratio=calmar,
        )


# 싱글톤 인스턴스
_analyzer_instance: Optional[PerformanceAnalyzer] = None


def get_analyzer() -> PerformanceAnalyzer:
    """PerformanceAnalyzer 싱글톤 인스턴스 가져오기"""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = PerformanceAnalyzer()
    return _analyzer_instance


def init_analyzer(config: Optional[Dict[str, Any]] = None) -> PerformanceAnalyzer:
    """PerformanceAnalyzer 초기화"""
    global _analyzer_instance
    _analyzer_instance = PerformanceAnalyzer(config=config)
    return _analyzer_instance

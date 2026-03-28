"""
제5부서: 일일 성과분석팀 (PnL Center) - 리포트 생성기

일일/주간/월간 성과 리포트를 생성합니다.
"""

import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any

from .models import (
    DailyPnL, PerformanceMetrics, TradeRecord,
    DEFAULT_PNL_CONFIG,
)
from .calculator import ProfitCalculator, get_calculator
from .performance import PerformanceAnalyzer, get_analyzer

logger = logging.getLogger(__name__)


class ReportGenerator:
    """성과 리포트 생성기"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or DEFAULT_PNL_CONFIG.copy()
        self.calculator = get_calculator()
        self.analyzer = get_analyzer()

    def generate_daily_report(self, target_date: Optional[date] = None) -> str:
        """일일 리포트 생성"""
        target_date = target_date or datetime.utcnow().date()
        daily_pnl = self.calculator.get_daily_pnl(target_date)

        if not daily_pnl:
            return self._format_empty_report(target_date)

        return self._format_daily_report(daily_pnl)

    def generate_period_report(
        self,
        start_date: date,
        end_date: date,
    ) -> str:
        """기간 리포트 생성"""
        daily_pnls = self.calculator.get_daily_pnl_range(start_date, end_date)
        trades = self.calculator.get_closed_trades(start_date, end_date)

        if not daily_pnls:
            return self._format_empty_period_report(start_date, end_date)

        metrics = self.analyzer.analyze_trades(trades, start_date, end_date)

        return self._format_period_report(daily_pnls, metrics)

    def generate_weekly_report(self, year: int, week: int) -> str:
        """주간 리포트 생성"""
        # ISO 주차 기준
        start_date = datetime.strptime(f"{year}-W{week}-1", "%Y-W%W-%w").date()
        end_date = start_date + timedelta(days=6)

        return self.generate_period_report(start_date, end_date)

    def generate_monthly_report(self, year: int, month: int) -> str:
        """월간 리포트 생성"""
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        return self.generate_period_report(start_date, end_date)

    def _format_daily_report(self, daily: DailyPnL) -> str:
        """일일 리포트 테이블 형식으로 포맷팅"""
        date_str = daily.date.strftime("%Y-%m-%d")

        lines = [
            "╔══════════════════════════════════════════════════════════╗",
            f"║     OZ_A2M 일일 성과 리포트 ({date_str})          ║",
            "╠══════════════════════════════════════════════════════════╣",
            f"║  순손익:       {self._format_decimal(daily.net_pnl):>18} USD    ║",
            f"║  실현손익:     {self._format_decimal(daily.realized_pnl):>18} USD    ║",
            f"║  미실현손익:   {self._format_decimal(daily.unrealized_pnl):>18} USD    ║",
            f"║  수수료:       {self._format_decimal(daily.fees):>18} USD    ║",
            "╠══════════════════════════════════════════════════════════╣",
            f"║  거래횟수: {daily.trade_count:>4}  승: {daily.win_count:>3}  패: {daily.loss_count:>3}  승률: {daily.win_rate:>5.1f}% ║",
            f"║  최대수익:  {self._format_decimal(daily.largest_win):>15}  최대손실: {self._format_decimal(daily.largest_loss):>15} ║",
            "╚══════════════════════════════════════════════════════════╝",
        ]

        return "\n".join(lines)

    def _format_period_report(
        self,
        daily_pnls: List[DailyPnL],
        metrics: PerformanceMetrics,
    ) -> str:
        """기간 리포트 테이블 형식으로 포맷팅"""
        start_str = metrics.period_start.strftime("%Y-%m-%d")
        end_str = metrics.period_end.strftime("%Y-%m-%d")

        # 기간 집계
        total_net = sum(d.net_pnl for d in daily_pnls)
        total_realized = sum(d.realized_pnl for d in daily_pnls)
        total_fees = sum(d.fees for d in daily_pnls)
        total_trades = sum(d.trade_count for d in daily_pnls)

        lines = [
            "╔══════════════════════════════════════════════════════════╗",
            f"║     OZ_A2M 성과 리포트 ({start_str} ~ {end_str})   ║",
            "╠══════════════════════════════════════════════════════════╣",
            "║  수익 요약                                               ║",
            f"║    순손익:      {self._format_decimal(total_net):>18} USD    ║",
            f"║    총수익률:    {metrics.total_return_percent:>17.2f}%     ║",
            f"║    실현손익:    {self._format_decimal(total_realized):>18} USD    ║",
            f"║    총수수료:    {self._format_decimal(total_fees):>18} USD    ║",
            "╠══════════════════════════════════════════════════════════╣",
            "║  성과 지표                                               ║",
            f"║    샤프 비율:       {metrics.sharpe_ratio:>8.2f}                              ║",
            f"║    소티노 비율:     {metrics.sortino_ratio:>8.2f}                              ║",
            f"║    최대낙폭(MDD):   {metrics.max_drawdown:>7.2f}%                              ║",
            f"║    Calmar 비율:     {metrics.calmar_ratio:>8.2f}                              ║",
            "╠══════════════════════════════════════════════════════════╣",
            "║  거래 통계                                               ║",
            f"║    총거래: {metrics.total_trades:>5}  승: {metrics.winning_trades:>5}  패: {metrics.losing_trades:>5}         ║",
            f"║    승률:    {metrics.win_rate:>6.1f}%  수익팩터: {metrics.profit_factor:>6.2f}                   ║",
            f"║    평균승: {self._format_decimal(metrics.avg_win):>10}  평균패: {self._format_decimal(metrics.avg_loss):>10}           ║",
            "╚══════════════════════════════════════════════════════════╝",
        ]

        return "\n".join(lines)

    def _format_empty_report(self, target_date: date) -> str:
        """빈 리포트"""
        return f"""
╔══════════════════════════════════════════════════════════╗
║     OZ_A2M 일일 성과 리포트 ({target_date})          ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║              해당 일자에 거래 데이터 없음                ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
"""

    def _format_empty_period_report(self, start: date, end: date) -> str:
        """빈 기간 리포트"""
        return f"""
╔══════════════════════════════════════════════════════════╗
║     OZ_A2M 성과 리포트 ({start} ~ {end})   ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║              해당 기간에 거래 데이터 없음                ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
"""

    def _format_decimal(self, value: Decimal) -> str:
        """Decimal 값 포맷팅"""
        if value == 0:
            return "0.00"
        return f"{float(value):,.2f}"

    def export_to_json(self, metrics: PerformanceMetrics) -> str:
        """성과 지표를 JSON으로 내보내기"""
        data = {
            "period_start": metrics.period_start.isoformat(),
            "period_end": metrics.period_end.isoformat(),
            "total_return": str(metrics.total_return),
            "total_return_percent": metrics.total_return_percent,
            "sharpe_ratio": metrics.sharpe_ratio,
            "sortino_ratio": metrics.sortino_ratio,
            "max_drawdown": metrics.max_drawdown,
            "max_drawdown_amount": str(metrics.max_drawdown_amount),
            "win_rate": metrics.win_rate,
            "profit_factor": metrics.profit_factor,
            "avg_win": str(metrics.avg_win),
            "avg_loss": str(metrics.avg_loss),
            "avg_win_loss_ratio": metrics.avg_win_loss_ratio,
            "total_trades": metrics.total_trades,
            "winning_trades": metrics.winning_trades,
            "losing_trades": metrics.losing_trades,
            "break_even_trades": metrics.break_even_trades,
            "volatility": metrics.volatility,
            "calmar_ratio": metrics.calmar_ratio,
        }
        return json.dumps(data, indent=2)

    def export_trades_to_csv(self, trades: List[TradeRecord]) -> str:
        """거래 내역을 CSV로 내보내기"""
        lines = ["trade_id,symbol,side,entry_price,exit_price,quantity,pnl,pnl_percent,entry_time,exit_time"]

        for trade in trades:
            lines.append(
                f"{trade.trade_id},{trade.symbol},{trade.side.value},"
                f"{trade.entry_price},{trade.exit_price or ''},{trade.quantity},"
                f"{trade.pnl},{trade.pnl_percent:.2f},"
                f"{trade.entry_time.isoformat()},{trade.exit_time.isoformat() if trade.exit_time else ''}"
            )

        return "\n".join(lines)


# 싱글톤 인스턴스
_report_generator_instance: Optional[ReportGenerator] = None


def get_report_generator() -> ReportGenerator:
    """ReportGenerator 싱글톤 인스턴스 가져오기"""
    global _report_generator_instance
    if _report_generator_instance is None:
        _report_generator_instance = ReportGenerator()
    return _report_generator_instance


def init_report_generator(config: Optional[Dict[str, Any]] = None) -> ReportGenerator:
    """ReportGenerator 초기화"""
    global _report_generator_instance
    _report_generator_instance = ReportGenerator(config=config)
    return _report_generator_instance

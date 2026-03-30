"""
제5부서: 일일 성과분석 대책개선팀 - 성과 추적 및 캘린더
PnL 캘린더, 리포트 생성, 성과 분석
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path

import sys
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DailyPerformance:
    """일일 성과 데이터"""
    date: str  # YYYY-MM-DD
    pnl: float
    pnl_pct: float
    trades: int
    win_count: int
    loss_count: int
    capital: float
    notes: Optional[str] = None
    bots_performance: Dict[str, Any] = None

    def __post_init__(self):
        if self.bots_performance is None:
            self.bots_performance = {}


class PerformanceTracker:
    """성과 추적기 - 캘린더 뷰 및 리포트"""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path(project_root) / 'data' / 'performance'
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 성과 데이터 저장소
        self.daily_data: Dict[str, DailyPerformance] = {}
        self._load_historical_data()

    def _load_historical_data(self):
        """역사적 성과 데이터 로드"""
        data_file = self.data_dir / 'daily_performance.json'
        if data_file.exists():
            try:
                with open(data_file, 'r') as f:
                    data = json.load(f)
                    for date_str, perf_data in data.items():
                        self.daily_data[date_str] = DailyPerformance(**perf_data)
                logger.info(f"Loaded {len(self.daily_data)} days of performance data")
            except Exception as e:
                logger.error(f"Failed to load performance data: {e}")

    def _save_historical_data(self):
        """성과 데이터 저장"""
        data_file = self.data_dir / 'daily_performance.json'
        try:
            with open(data_file, 'w') as f:
                json.dump(
                    {k: asdict(v) for k, v in self.daily_data.items()},
                    f,
                    indent=2
                )
        except Exception as e:
            logger.error(f"Failed to save performance data: {e}")

    def record_daily_performance(
        self,
        date: str,
        pnl: float,
        trades: int = 0,
        win_count: int = 0,
        loss_count: int = 0,
        capital: float = 0,
        bots_performance: Optional[Dict] = None
    ) -> DailyPerformance:
        """일일 성과 기록"""
        pnl_pct = (pnl / capital * 100) if capital > 0 else 0

        perf = DailyPerformance(
            date=date,
            pnl=pnl,
            pnl_pct=pnl_pct,
            trades=trades,
            win_count=win_count,
            loss_count=loss_count,
            capital=capital,
            bots_performance=bots_performance or {}
        )

        self.daily_data[date] = perf
        self._save_historical_data()

        logger.info(f"Recorded performance for {date}: PnL=${pnl:.2f} ({pnl_pct:.2f}%)")
        return perf

    def get_calendar_data(self, year: int, month: int) -> List[Dict]:
        """캘린더 데이터 생성"""
        calendar = []

        # 해당 월의 모든 날짜
        import calendar
        cal = calendar.Calendar()

        for week in cal.monthdayscalendar(year, month):
            week_data = []
            for day in week:
                if day == 0:
                    week_data.append(None)
                else:
                    date_str = f"{year:04d}-{month:02d}-{day:02d}"
                    perf = self.daily_data.get(date_str)

                    day_data = {
                        'day': day,
                        'date': date_str,
                        'has_data': perf is not None,
                    }

                    if perf:
                        day_data.update({
                            'pnl': perf.pnl,
                            'pnl_pct': perf.pnl_pct,
                            'trades': perf.trades,
                            'win_count': perf.win_count,
                            'loss_count': perf.loss_count,
                            'capital': perf.capital,
                        })

                    week_data.append(day_data)

            calendar.append(week_data)

        return calendar

    def get_monthly_summary(self, year: int, month: int) -> Dict:
        """월간 요약"""
        prefix = f"{year:04d}-{month:02d}"
        monthly_data = [
            perf for date, perf in self.daily_data.items()
            if date.startswith(prefix)
        ]

        if not monthly_data:
            return {
                'month': f"{year}-{month:02d}",
                'total_pnl': 0,
                'total_trades': 0,
                'win_days': 0,
                'loss_days': 0,
                'avg_daily_pnl': 0,
            }

        total_pnl = sum(d.pnl for d in monthly_data)
        total_trades = sum(d.trades for d in monthly_data)
        win_days = sum(1 for d in monthly_data if d.pnl > 0)
        loss_days = sum(1 for d in monthly_data if d.pnl < 0)

        return {
            'month': f"{year}-{month:02d}",
            'total_pnl': total_pnl,
            'total_trades': total_trades,
            'win_days': win_days,
            'loss_days': loss_days,
            'avg_daily_pnl': total_pnl / len(monthly_data),
            'days_traded': len(monthly_data),
        }

    def get_performance_range(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict]:
        """기간별 성과 조회"""
        start = start_date or (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        end = end_date or datetime.now().strftime('%Y-%m-%d')

        results = []
        for date_str, perf in sorted(self.daily_data.items()):
            if start <= date_str <= end:
                results.append(asdict(perf))

        return results

    def generate_report(self, start_date: str, end_date: str) -> Dict:
        """리포트 생성"""
        performances = self.get_performance_range(start_date, end_date)

        if not performances:
            return {
                'period': f"{start_date} ~ {end_date}",
                'message': 'No data available for the specified period'
            }

        total_pnl = sum(p['pnl'] for p in performances)
        total_trades = sum(p['trades'] for p in performances)
        total_wins = sum(p['win_count'] for p in performances)
        total_losses = sum(p['loss_count'] for p in performances)

        win_rate = (total_wins / (total_wins + total_losses) * 100) if (total_wins + total_losses) > 0 else 0

        # 최고/최저 수익일
        best_day = max(performances, key=lambda x: x['pnl'])
        worst_day = min(performances, key=lambda x: x['pnl'])

        return {
            'period': f"{start_date} ~ {end_date}",
            'summary': {
                'total_pnl': total_pnl,
                'total_trades': total_trades,
                'win_rate': win_rate,
                'profit_days': sum(1 for p in performances if p['pnl'] > 0),
                'loss_days': sum(1 for p in performances if p['pnl'] < 0),
            },
            'best_day': best_day,
            'worst_day': worst_day,
            'daily_performances': performances,
            'generated_at': datetime.utcnow().isoformat(),
        }

    def get_bot_performance(self, bot_id: Optional[str] = None) -> Dict:
        """봇별 성과 조회"""
        bot_stats = {}

        for date, perf in self.daily_data.items():
            for bid, bot_perf in (perf.bots_performance or {}).items():
                if bot_id and bid != bot_id:
                    continue

                if bid not in bot_stats:
                    bot_stats[bid] = {
                        'total_pnl': 0,
                        'total_trades': 0,
                        'win_count': 0,
                        'loss_count': 0,
                    }

                bot_stats[bid]['total_pnl'] += bot_perf.get('pnl', 0)
                bot_stats[bid]['total_trades'] += bot_perf.get('trades', 0)
                bot_stats[bid]['win_count'] += bot_perf.get('wins', 0)
                bot_stats[bid]['loss_count'] += bot_perf.get('losses', 0)

        return bot_stats


# 전역 성과 추적기 인스턴스
performance_tracker = PerformanceTracker()


# 샘플 데이터 생성
def generate_sample_data():
    """샘플 성과 데이터 생성 (테스트용)"""
    tracker = PerformanceTracker()

    # 지난 30일 샘플 데이터
    for i in range(30):
        date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        import random
        pnl = random.uniform(-50, 100)
        trades = random.randint(0, 20)
        wins = random.randint(0, trades)

        tracker.record_daily_performance(
            date=date,
            pnl=pnl,
            trades=trades,
            win_count=wins,
            loss_count=trades - wins,
            capital=1000 + i * 10,
            bots_performance={
                'grid_binance_001': {'pnl': pnl * 0.3, 'trades': trades // 3},
                'scalper_bybit_001': {'pnl': pnl * 0.5, 'trades': trades // 2},
                'dca_binance_001': {'pnl': pnl * 0.2, 'trades': trades // 6},
            }
        )

    return tracker


if __name__ == '__main__':
    # 테스트
    tracker = generate_sample_data()
    print("=== Performance Tracker Test ===")
    print(f"Total days: {len(tracker.daily_data)}")

    # 캘린더 데이터
    now = datetime.now()
    calendar = tracker.get_calendar_data(now.year, now.month)
    print(f"\nCalendar for {now.year}-{now.month:02d}:")
    print(f"Weeks: {len(calendar)}")

    # 월간 요약
    summary = tracker.get_monthly_summary(now.year, now.month)
    print(f"\nMonthly Summary:")
    print(f"  Total PnL: ${summary['total_pnl']:.2f}")
    print(f"  Win Days: {summary['win_days']}")
    print(f"  Loss Days: {summary['loss_days']}")

"""
전략 평가 및 분석기 (제6부서 R&D)

- 전략별 성과 순위 계산
- 최하위 전략 → 폐기 플래그
- 최상위 전략 → 강화 플래그
"""

import json
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from .strategy_db import get_strategy_db, StrategyPerformance, StrategyRank

logger = logging.getLogger(__name__)


@dataclass
class StrategySignal:
    """전략 개선 신호"""
    strategy_id: str
    signal_type: str  # 'strengthen', 'deprecate', 'maintain', 'investigate'
    reason: str
    metrics: Dict[str, Any]
    recommended_action: Optional[str] = None


class StrategyEvaluator:
    """
    전략 성과 평가기

    일일 분석 루프:
    1. 전날 전략 결과 조회
    2. 성과 DB 저장
    3. 개선 신호 생성
    """

    def __init__(self):
        self.db = get_strategy_db()

    def analyze_daily_performance(
        self,
        target_date: Optional[str] = None
    ) -> List[StrategySignal]:
        """
        일일 성과 분석

        Returns:
            개선 신호 리스트
        """
        if target_date is None:
            target_date = (date.today() - timedelta(days=1)).isoformat()

        signals = []
        summary = self.db.get_daily_summary(target_date)

        if summary['strategy_count'] == 0:
            logger.warning(f"No performance data for {target_date}")
            return signals

        # 전략별 분석
        for strategy_data in summary['strategies']:
            signal = self._evaluate_strategy(strategy_data, target_date)
            if signal:
                signals.append(signal)

        logger.info(f"Analyzed {len(signals)} strategies for {target_date}")
        return signals

    def _evaluate_strategy(
        self,
        strategy_data: Dict[str, Any],
        target_date: str
    ) -> Optional[StrategySignal]:
        """개별 전략 평가"""
        strategy_id = strategy_data['strategy_id']
        pnl = strategy_data['pnl']
        sharpe = strategy_data['sharpe']
        mdd = strategy_data['mdd']
        win_rate = strategy_data['win_rate']
        trades = strategy_data['trades']

        # 최근 7일 평균과 비교
        recent_perf = self.db.get_performance(strategy_id)
        recent_pnl_avg = sum(p.pnl for p in recent_perf[:7]) / max(1, len(recent_perf[:7]))

        # 신호 결정 로직
        if pnl < -1000 or (mdd > 0.15 and sharpe < 0.5):
            return StrategySignal(
                strategy_id=strategy_id,
                signal_type='deprecate',
                reason=f"Significant loss (PnL: {pnl:.2f}) or high MDD ({mdd:.2%})",
                metrics={'pnl': pnl, 'mdd': mdd, 'sharpe': sharpe},
                recommended_action='Stop and review strategy parameters'
            )
        elif pnl > 2000 and sharpe > 1.5 and win_rate > 0.6:
            return StrategySignal(
                strategy_id=strategy_id,
                signal_type='strengthen',
                reason=f"Excellent performance (PnL: {pnl:.2f}, Sharpe: {sharpe:.2f})",
                metrics={'pnl': pnl, 'sharpe': sharpe, 'win_rate': win_rate},
                recommended_action='Increase position size and optimize parameters'
            )
        elif abs(pnl - recent_pnl_avg) > 2 * abs(recent_pnl_avg):
            return StrategySignal(
                strategy_id=strategy_id,
                signal_type='investigate',
                reason=f"Unusual deviation from average (PnL: {pnl:.2f} vs avg: {recent_pnl_avg:.2f})",
                metrics={'pnl': pnl, 'recent_avg': recent_pnl_avg, 'deviation': abs(pnl - recent_pnl_avg)},
                recommended_action='Check market conditions and strategy behavior'
            )
        elif trades < 5 and pnl != 0:
            return StrategySignal(
                strategy_id=strategy_id,
                signal_type='investigate',
                reason=f"Low trade count ({trades}) with non-zero PnL",
                metrics={'trades': trades, 'pnl': pnl},
                recommended_action='Verify signal generation logic'
            )

        return None

    def generate_ranking_report(self, days: int = 30) -> Dict[str, Any]:
        """순위 보고서 생성"""
        rankings = self.db.get_rankings(days)

        strengthen_list = [r for r in rankings if r.flag == 'strengthen']
        deprecate_list = [r for r in rankings if r.flag == 'deprecate']
        maintain_list = [r for r in rankings if r.flag == 'maintain']

        report = {
            'generated_at': datetime.now().isoformat(),
            'period_days': days,
            'total_strategies': len(rankings),
            'summary': {
                'strengthen': len(strengthen_list),
                'maintain': len(maintain_list),
                'deprecate': len(deprecate_list)
            },
            'rankings': [
                {
                    'rank': r.rank,
                    'strategy_id': r.strategy_id,
                    'total_pnl': r.total_pnl,
                    'avg_sharpe': r.avg_sharpe,
                    'flag': r.flag
                }
                for r in rankings
            ],
            'recommendations': {
                'strengthen': [
                    {'strategy_id': r.strategy_id, 'pnl': r.total_pnl}
                    for r in strengthen_list
                ],
                'deprecate': [
                    {'strategy_id': r.strategy_id, 'pnl': r.total_pnl}
                    for r in deprecate_list
                ]
            }
        }

        return report

    def run_daily_analysis_loop(self) -> Dict[str, Any]:
        """
        일일 분석 루프 실행

        전략 평가 → 성과 DB 저장 → 개선 신호 생성
        """
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        logger.info(f"Running daily analysis for {yesterday}")

        # 1. 성과 분석 및 신호 생성
        signals = self.analyze_daily_performance(yesterday)

        # 2. 순위 보고서 생성
        report = self.generate_ranking_report()

        # 3. 콘솔 출력
        self._print_analysis_results(signals, report)

        return {
            'date': yesterday,
            'signals': [
                {
                    'strategy_id': s.strategy_id,
                    'signal_type': s.signal_type,
                    'reason': s.reason,
                    'recommended_action': s.recommended_action
                }
                for s in signals
            ],
            'report': report
        }

    def _print_analysis_results(self, signals: List[StrategySignal], report: Dict):
        """분석 결과 콘솔 출력"""
        print("\n" + "=" * 60)
        print(" DAILY STRATEGY ANALYSIS REPORT ")
        print("=" * 60)

        print(f"\nPeriod: Last {report['period_days']} days")
        print(f"Total Strategies: {report['total_strategies']}")

        print("\n[Summary]")
        for flag, count in report['summary'].items():
            print(f"  {flag}: {count}")

        print("\n[Top 5 Rankings]")
        for r in report['rankings'][:5]:
            flag_icon = "🔥" if r['flag'] == 'strengthen' else "⚠️" if r['flag'] == 'deprecate' else "✓"
            print(f"  {r['rank']:2d}. {r['strategy_id']:20s} "
                  f"PnL: ${r['total_pnl']:>10.2f} "
                  f"Sharpe: {r['avg_sharpe']:.2f} "
                  f"{flag_icon}")

        if signals:
            print("\n[Signals Generated]")
            for s in signals:
                icon = {
                    'strengthen': '📈',
                    'deprecate': '📉',
                    'investigate': '🔍',
                    'maintain': '➡️'
                }.get(s.signal_type, '•')
                print(f"  {icon} {s.strategy_id}: {s.signal_type}")
                print(f"      Reason: {s.reason}")
                print(f"      Action: {s.recommended_action}")

        print("\n" + "=" * 60)


def run_analysis():
    """CLI 실행 함수"""
    evaluator = StrategyEvaluator()
    result = evaluator.run_daily_analysis_loop()
    return result


if __name__ == "__main__":
    run_analysis()

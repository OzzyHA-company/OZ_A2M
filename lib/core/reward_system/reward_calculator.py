"""
Reward Calculator - FinRL 기반 보상 계산 모듈

수익 극대화를 위한 다양한 보상 함수 구현
참고: AI4Finance-Foundation/FinRL

Reward Functions:
1. Sharpe Ratio - 위험 조정 수익률
2. Sortino Ratio - 하방 위험만 페널티
3. Calmar Ratio - 최대 낙폭 대비 수익
4. Custom OZ_A2M - 봇 유형별 최적화
"""

import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class RewardType(Enum):
    """보상 함수 유형"""
    SHARPE = "sharpe"           # 위험 조정 수익률
    SORTINO = "sortino"         # 하방 변동성만 페널티 (안정봇용)
    CALMAR = "calmar"           # 연수익/최대낙폭 (도파민봇용)
    OMEGA = "omega"             # 상방/하방 비율
    CUSTOM_ARB = "custom_arb"   # 차익거래용
    CUSTOM_AI = "custom_ai"     # AI 분석용
    OZ_ENSEMBLE = "oz_ensemble" # OZ_A2M 통합 보상


@dataclass
class TradeRecord:
    """거래 기록 데이터"""
    timestamp: datetime
    pnl: float              # 실현 손익
    pnl_pct: float          # 수익률 (%)
    position_size: float    # 포지션 크기
    holding_period: float   # 보유 기간 (시간)
    win: bool               # 승/패 여부


@dataclass
class RewardResult:
    """보상 계산 결과"""
    bot_id: str
    reward_type: RewardType
    score: float            # 최종 보상 점수
    metrics: Dict[str, float]  # 세부 지표
    timestamp: datetime
    period_days: int        # 분석 기간


class RewardCalculator:
    """
    FinRL 기반 보상 계산기

    수익 극대화를 위한 다양한 보상 함수 제공
    봇 유형별 최적 보상 함수 자동 선택
    """

    def __init__(self, risk_free_rate: float = 0.02):
        """
        초기화

        Args:
            risk_free_rate: 무위험 수익률 (연간, 기본 2%)
        """
        self.risk_free_rate = risk_free_rate
        self.logger = logging.getLogger(self.__class__.__name__)

    def calculate(
        self,
        bot_id: str,
        trades: List[TradeRecord],
        reward_type: RewardType = RewardType.SHARPE,
        lookback_days: int = 7,
        llm_confidence: Optional[float] = None,
    ) -> RewardResult:
        """
        보상 점수 계산

        Args:
            bot_id: 봇 ID
            trades: 거래 기록 목록
            reward_type: 보상 함수 유형
            lookback_days: 분석 기간 (일)
            llm_confidence: LLM 신뢰도 배율 (0.5 ~ 1.5)

        Returns:
            RewardResult: 보상 계산 결과
        """
        if not trades:
            return RewardResult(
                bot_id=bot_id,
                reward_type=reward_type,
                score=0.0,
                metrics={},
                timestamp=datetime.utcnow(),
                period_days=lookback_days,
            )

        # 기간 필터링
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        recent_trades = [t for t in trades if t.timestamp >= cutoff]

        if not recent_trades:
            recent_trades = trades[-30:] if len(trades) > 30 else trades

        # 보상 함수 선택
        if reward_type == RewardType.SHARPE:
            score, metrics = self._calc_sharpe(recent_trades)
        elif reward_type == RewardType.SORTINO:
            score, metrics = self._calc_sortino(recent_trades)
        elif reward_type == RewardType.CALMAR:
            score, metrics = self._calc_calmar(recent_trades, lookback_days)
        elif reward_type == RewardType.OMEGA:
            score, metrics = self._calc_omega(recent_trades)
        elif reward_type == RewardType.CUSTOM_ARB:
            score, metrics = self._calc_arb_reward(recent_trades)
        elif reward_type == RewardType.CUSTOM_AI:
            score, metrics = self._calc_ai_reward(recent_trades)
        elif reward_type == RewardType.OZ_ENSEMBLE:
            score, metrics = self._calc_oz_ensemble(recent_trades, lookback_days)
        else:
            score, metrics = self._calc_sharpe(recent_trades)

        # LLM 신뢰도 적용 (Phase 2)
        if llm_confidence is not None:
            multiplier = max(0.5, min(1.5, llm_confidence))
            score *= multiplier
            metrics['llm_multiplier'] = multiplier

        return RewardResult(
            bot_id=bot_id,
            reward_type=reward_type,
            score=round(score, 4),
            metrics=metrics,
            timestamp=datetime.utcnow(),
            period_days=lookback_days,
        )

    def _calc_sharpe(self, trades: List[TradeRecord]) -> Tuple[float, Dict[str, float]]:
        """
        Sharpe Ratio 계산
        수익 / 변동성 (위험 조정 수익률)
        """
        if len(trades) < 2:
            return 0.0, {'trades': len(trades)}

        returns = np.array([t.pnl_pct for t in trades])

        # 연율화 계수 (일간 데이터 가정)
        ann_factor = np.sqrt(365)

        mean_return = np.mean(returns)
        std_return = np.std(returns, ddof=1)

        if std_return == 0:
            sharpe = 0.0
        else:
            sharpe = (mean_return - self.risk_free_rate / 365) / std_return * ann_factor

        metrics = {
            'mean_return': round(mean_return, 4),
            'std_return': round(std_return, 4),
            'sharpe_ratio': round(sharpe, 4),
            'trades': len(trades),
        }

        # 점수 정규화 (-5 ~ 5 범위를 0 ~ 100으로)
        score = (sharpe + 5) * 10
        score = max(0, min(100, score))

        return score, metrics

    def _calc_sortino(self, trades: List[TradeRecord]) -> Tuple[float, Dict[str, float]]:
        """
        Sortino Ratio 계산
        하방 변동성만 페널티 (안정봇용)

        FinRL-Trading의 sortino_hyperopt_loss.py 참고
        """
        if len(trades) < 2:
            return 0.0, {'trades': len(trades)}

        returns = np.array([t.pnl_pct for t in trades])

        mean_return = np.mean(returns)

        # 하방 편차만 계산 (음수 수익률)
        downside_returns = returns[returns < 0]
        downside_std = np.std(downside_returns, ddof=1) if len(downside_returns) > 0 else 0

        if downside_std == 0:
            sortino = mean_return * 100  # 하방 리스크 없음 = 최고 보상
        else:
            ann_factor = np.sqrt(365)
            sortino = (mean_return - self.risk_free_rate / 365) / downside_std * ann_factor

        metrics = {
            'mean_return': round(mean_return, 4),
            'downside_std': round(downside_std, 4),
            'sortino_ratio': round(sortino, 4),
            'downside_trades': len(downside_returns),
            'trades': len(trades),
        }

        # 점수 정규화
        score = (sortino + 5) * 10
        score = max(0, min(100, score))

        return score, metrics

    def _calc_calmar(self, trades: List[TradeRecord], period_days: int) -> Tuple[float, Dict[str, float]]:
        """
        Calmar Ratio 계산
        연수익률 / 최대낙폭 (도파민봇용)

        단기 고수익이 목표 → 빠른 수익 누적 보상
        """
        if len(trades) < 2:
            return 0.0, {'trades': len(trades)}

        returns = np.array([t.pnl_pct for t in trades])

        # 누적 수익률
        cumulative = np.cumprod(1 + returns / 100) - 1

        # 최대 낙폭 (MDD) 계산
        peak = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - peak) / (peak + 1e-10)
        max_drawdown = abs(np.min(drawdown))

        # 연율화 수익률
        total_return = cumulative[-1]
        ann_return = (1 + total_return) ** (365 / period_days) - 1 if period_days > 0 else total_return

        if max_drawdown == 0:
            calmar = ann_return * 100
        else:
            calmar = ann_return / max_drawdown

        metrics = {
            'ann_return': round(ann_return * 100, 2),
            'max_drawdown': round(max_drawdown * 100, 2),
            'calmar_ratio': round(calmar, 4),
            'trades': len(trades),
        }

        # 점수 정규화
        score = min(calmar * 10, 100) if calmar > 0 else max(calmar * 5 + 50, 0)
        score = max(0, min(100, score))

        return score, metrics

    def _calc_omega(self, trades: List[TradeRecord]) -> Tuple[float, Dict[str, float]]:
        """
        Omega Ratio 계산
        상방 수익 / 하방 손실 비율
        """
        if len(trades) < 2:
            return 0.0, {'trades': len(trades)}

        returns = np.array([t.pnl_pct for t in trades])

        threshold = 0  # 기준 수익률

        gains = returns[returns > threshold]
        losses = returns[returns < threshold]

        upside = np.sum(gains - threshold) if len(gains) > 0 else 0
        downside = abs(np.sum(losses - threshold)) if len(losses) > 0 else 1e-10

        omega = upside / downside if downside > 0 else 10.0

        metrics = {
            'upside_sum': round(upside, 4),
            'downside_sum': round(downside, 4),
            'omega_ratio': round(omega, 4),
            'win_trades': len(gains),
            'loss_trades': len(losses),
        }

        # 점수 정규화 (Omega 0~2를 0~100으로)
        score = min(omega * 50, 100)

        return score, metrics

    def _calc_arb_reward(self, trades: List[TradeRecord]) -> Tuple[float, Dict[str, float]]:
        """
        차익거래용 커스텀 보상
        (수익 - 거래비용) / 기회비용
        """
        if not trades:
            return 0.0, {'trades': 0}

        total_pnl = sum(t.pnl for t in trades)
        trading_cost = len(trades) * 0.001  # 거래당 0.1% 가정
        net_pnl = total_pnl - trading_cost

        # 승률
        win_count = sum(1 for t in trades if t.win)
        win_rate = win_count / len(trades) if trades else 0

        # 평균 보유 기간 (짧을수록 좋음)
        avg_holding = np.mean([t.holding_period for t in trades]) if trades else 0
        holding_score = max(0, 1 - avg_holding / 24)  # 24시간 기준

        # 종합 점수
        pnl_score = min(max(net_pnl * 10, 0), 50)  # 수익 50점
        win_score = win_rate * 30  # 승률 30점
        speed_score = holding_score * 20  # 속도 20점

        score = pnl_score + win_score + speed_score

        metrics = {
            'total_pnl': round(total_pnl, 4),
            'trading_cost': round(trading_cost, 4),
            'net_pnl': round(net_pnl, 4),
            'win_rate': round(win_rate, 4),
            'avg_holding_hours': round(avg_holding, 2),
            'trades': len(trades),
        }

        return score, metrics

    def _calc_ai_reward(self, trades: List[TradeRecord]) -> Tuple[float, Dict[str, float]]:
        """
        AI 분석봇용 커스텀 보상
        예측 정확도 × 기대수익
        """
        if not trades:
            return 0.0, {'trades': 0}

        returns = [t.pnl_pct for t in trades]

        # 예측 정확도 (양수 수익 비율)
        correct_predictions = sum(1 for r in returns if r > 0)
        accuracy = correct_predictions / len(trades) if trades else 0

        # 평균 수익 (예측 성공시)
        avg_positive = np.mean([r for r in returns if r > 0]) if any(r > 0 for r in returns) else 0

        # 평균 손실 (예측 실패시)
        avg_negative = np.mean([r for r in returns if r < 0]) if any(r < 0 for r in returns) else 0

        # 기대수익 = 정확도 × 평균수익 - (1-정확도) × |평균손실|
        expected_return = accuracy * avg_positive - (1 - accuracy) * abs(avg_negative)

        # 정확도 60점 + 기대수익 40점
        score = accuracy * 60 + min(max(expected_return, 0), 40)

        metrics = {
            'accuracy': round(accuracy, 4),
            'avg_positive': round(avg_positive, 4),
            'avg_negative': round(avg_negative, 4),
            'expected_return': round(expected_return, 4),
            'trades': len(trades),
        }

        return score, metrics

    def _calc_oz_ensemble(
        self,
        trades: List[TradeRecord],
        period_days: int
    ) -> Tuple[float, Dict[str, float]]:
        """
        OZ_A2M 통합 앙상블 보상

        FinRL-Trading Ensemble Strategy 방식
        여러 보상 함수의 가중 평균
        """
        # 각 보상 함수별 점수
        sharpe_score, sharpe_metrics = self._calc_sharpe(trades)
        sortino_score, sortino_metrics = self._calc_sortino(trades)
        calmar_score, calmar_metrics = self._calc_calmar(trades, period_days)
        omega_score, omega_metrics = self._calc_omega(trades)

        # 가중치 (OZ_A2M 최적화)
        weights = {
            'sharpe': 0.25,
            'sortino': 0.30,  # 하방 리스크 중시
            'calmar': 0.25,   # 낙폭 관리
            'omega': 0.20,
        }

        # 가중 평균
        ensemble_score = (
            sharpe_score * weights['sharpe'] +
            sortino_score * weights['sortino'] +
            calmar_score * weights['calmar'] +
            omega_score * weights['omega']
        )

        metrics = {
            'sharpe_score': round(sharpe_score, 4),
            'sortino_score': round(sortino_score, 4),
            'calmar_score': round(calmar_score, 4),
            'omega_score': round(omega_score, 4),
            'ensemble_score': round(ensemble_score, 4),
            'trades': len(trades),
        }

        return ensemble_score, metrics

    def batch_calculate(
        self,
        bot_trades: Dict[str, List[TradeRecord]],
        reward_type: RewardType = RewardType.OZ_ENSEMBLE,
        lookback_days: int = 7,
    ) -> Dict[str, RewardResult]:
        """
        다중 봇 일괄 보상 계산

        Args:
            bot_trades: {bot_id: trades} 매핑
            reward_type: 보상 함수 유형
            lookback_days: 분석 기간

        Returns:
            Dict[str, RewardResult]: 봇별 보상 결과
        """
        results = {}
        for bot_id, trades in bot_trades.items():
            results[bot_id] = self.calculate(
                bot_id=bot_id,
                trades=trades,
                reward_type=reward_type,
                lookback_days=lookback_days,
            )
        return results

    def get_rankings(
        self,
        results: Dict[str, RewardResult]
    ) -> List[Tuple[str, float]]:
        """
        보상 점수 기반 봇 순위

        Returns:
            List[Tuple[str, float]]: [(bot_id, score), ...] 내림차순
        """
        ranked = sorted(
            [(bot_id, r.score) for bot_id, r in results.items()],
            key=lambda x: x[1],
            reverse=True,
        )
        return ranked

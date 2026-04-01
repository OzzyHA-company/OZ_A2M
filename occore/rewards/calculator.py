"""
OZ_A2M Rewards System — 보상 계산기

온라인(실시간) 보상 계산과 트레이딩 봇 전용 리스크 조정 보상을 담당합니다.

TradingRewardCalculator 보상 공식:
  R = +α×(Sharpe 조정 수익) - β×(MDD 증가) - γ×(규칙 위반) - δ×(슬리피지+수수료)
"""

import logging
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Any

from .models import (
    AgentAction,
    AgentSession,
    RewardEvent,
    RewardEventType,
    RewardScore,
    SafetyViolationType,
    TradingRewardConfig,
    DEFAULT_REWARD_CONFIG,
    DEFAULT_TRADING_REWARD_CONFIG,
)

logger = logging.getLogger(__name__)


class RewardCalculator:
    """
    온라인(실시간) 보상 계산기

    매 에이전트 이벤트에서 즉각적인 보상 점수를 계산합니다.
    안전 위반은 강한 페널티, 성공/증거 제공은 가산점을 부여합니다.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = {**DEFAULT_REWARD_CONFIG, **(config or {})}
        self._lock = threading.Lock()
        self._session_scores: Dict[str, RewardScore] = {}

    # ------------------------------------------------------------------
    # 개별 이벤트 처리
    # ------------------------------------------------------------------

    def process_event(self, event: RewardEvent) -> float:
        """
        단일 이벤트로부터 즉각적인 보상 점수를 반환합니다.

        Returns:
            이 이벤트의 즉각적인 raw 보상 점수 (양수=보상, 음수=페널티)
        """
        score = self._score_event(event)
        event.raw_score = score
        logger.debug(
            "reward_event agent=%s session=%s type=%s score=%.2f",
            event.agent_id, event.session_id, event.event_type.value, score,
        )
        return score

    def _score_event(self, event: RewardEvent) -> float:
        """이벤트 유형에 따른 점수 계산"""
        cfg = self.config
        etype = event.event_type

        # ---- 성공 이벤트 ----
        if etype == RewardEventType.TASK_SUCCESS:
            return float(cfg["task_success_reward"])

        if etype == RewardEventType.NO_TRADE:
            return float(cfg["no_trade_reward"])

        if etype == RewardEventType.SAFE_DECISION:
            return float(cfg["safe_decision_reward"])

        if etype == RewardEventType.EVIDENCE_PROVIDED:
            return float(cfg["evidence_reward"])

        # ---- 페널티 이벤트 ----
        if etype == RewardEventType.TASK_FAILURE:
            return float(cfg["task_failure_penalty"])

        if etype == RewardEventType.COST_EXCESS:
            cost_units = float(event.metadata.get("cost_units", 1.0))
            return float(cfg["cost_penalty_per_unit"]) * cost_units

        if etype == RewardEventType.LATENCY_EXCESS:
            excess_seconds = float(event.metadata.get("excess_seconds", 1.0))
            return float(cfg["latency_penalty_per_second"]) * excess_seconds

        if etype == RewardEventType.UNNECESSARY_TOOL_CALL:
            return float(cfg["unnecessary_tool_penalty"])

        if etype == RewardEventType.FALSE_CONFIDENCE:
            return float(cfg["false_confidence_penalty"])

        # ---- 안전 위반 (강한 페널티) ----
        if etype == RewardEventType.SAFETY_VIOLATION:
            return self._safety_penalty(event)

        if etype == RewardEventType.RULE_VIOLATION:
            violation_key = event.metadata.get("violation_type", "frequency_violation")
            penalties = cfg["safety_violation_penalty"]
            return float(penalties.get(violation_key, -10.0))

        return 0.0

    def _safety_penalty(self, event: RewardEvent) -> float:
        """안전 위반 페널티 계산"""
        penalties: Dict[str, float] = self.config["safety_violation_penalty"]
        if event.safety_violation:
            key = event.safety_violation.value
            return float(penalties.get(key, -20.0))
        return -20.0

    # ------------------------------------------------------------------
    # 세션 단위 집계
    # ------------------------------------------------------------------

    def compute_session_reward(self, session: AgentSession) -> RewardScore:
        """
        에이전트 세션 전체를 집계하여 RewardScore를 반환합니다.
        """
        task_success = 0.0
        cost_penalty = 0.0
        latency_penalty = 0.0
        safety_penalty = 0.0
        violation_count = 0

        for event in session.events:
            raw = self.process_event(event)

            if event.event_type in (
                RewardEventType.TASK_SUCCESS,
                RewardEventType.NO_TRADE,
                RewardEventType.SAFE_DECISION,
                RewardEventType.EVIDENCE_PROVIDED,
            ):
                task_success += raw

            elif event.event_type in (
                RewardEventType.COST_EXCESS,
                RewardEventType.UNNECESSARY_TOOL_CALL,
            ):
                cost_penalty += raw

            elif event.event_type == RewardEventType.LATENCY_EXCESS:
                latency_penalty += raw

            elif event.event_type in (
                RewardEventType.SAFETY_VIOLATION,
                RewardEventType.RULE_VIOLATION,
                RewardEventType.FALSE_CONFIDENCE,
            ):
                safety_penalty += raw
                violation_count += 1

        online_reward = task_success + cost_penalty + latency_penalty + safety_penalty

        # 클리핑
        online_reward = max(
            float(self.config["min_online_reward"]),
            min(float(self.config["max_online_reward"]), online_reward),
        )

        score = RewardScore(
            session_id=session.session_id,
            agent_id=session.agent_id,
            timestamp=datetime.now(timezone.utc),
            online_reward=online_reward,
            task_success_score=task_success,
            cost_penalty=cost_penalty,
            latency_penalty=latency_penalty,
            safety_penalty=safety_penalty,
            total_events=len(session.events),
            violation_count=violation_count,
        )

        with self._lock:
            self._session_scores[session.session_id] = score

        logger.info(
            "session_reward agent=%s session=%s online=%.2f total=%.2f violations=%d",
            session.agent_id, session.session_id,
            score.online_reward, score.total_reward, violation_count,
        )
        return score

    def get_session_score(self, session_id: str) -> Optional[RewardScore]:
        """세션 보상 점수 조회"""
        return self._session_scores.get(session_id)

    def get_all_scores(self) -> List[RewardScore]:
        """모든 세션 보상 점수 조회"""
        return list(self._session_scores.values())


class TradingRewardCalculator:
    """
    트레이딩 봇 전용 리스크 조정 보상 계산기

    보상 공식:
        R = +α×(리스크 조정 수익) - β×(MDD 증가) - γ×(규칙 위반 수) - δ×(슬리피지+수수료)

    수익률 단독 지표 대신 리스크 페널티가 강한 보상 체계를 사용합니다.
    "거래 안 함(No-trade)"이 최선인 경우 양의 보상을 부여합니다.
    """

    def __init__(self, config: Optional[TradingRewardConfig] = None) -> None:
        self.config = config or DEFAULT_TRADING_REWARD_CONFIG

    def compute(
        self,
        *,
        pnl: float,
        sharpe_ratio: float,
        mdd_delta: float,
        rule_violations: int,
        slippage_fees: float,
        no_trade: bool = False,
    ) -> float:
        """
        단일 트레이딩 스텝의 보상을 계산합니다.

        Args:
            pnl: 실현 손익 (USD 기준)
            sharpe_ratio: 현 시점 샤프 비율 (음수 가능)
            mdd_delta: 이번 스텝에서 MDD가 증가한 비율 (0~1, 감소 시 0)
            rule_violations: 포지션 한도·손절·빈도 등 위반 횟수
            slippage_fees: 슬리피지+수수료 합계 (USD)
            no_trade: 거래하지 않기로 결정한 스텝이면 True

        Returns:
            보상 점수 (클리핑 적용)
        """
        cfg = self.config

        if no_trade:
            # 불확실하거나 데이터 결함 시 거래 안 함 → 소폭 양의 보상
            return 1.0

        # 리스크 조정 수익: sharpe_ratio를 활용해 변동성 패널티 내재
        risk_adjusted_return = pnl * max(sharpe_ratio, 0.0)
        reward = cfg.alpha * risk_adjusted_return

        # MDD 증가 페널티: MDD 증가 비율에 현재 손익 규모를 곱해 스케일링
        reward -= cfg.beta * max(mdd_delta, 0.0) * abs(pnl)

        # 규칙 위반 페널티 (위반 1건당 강한 차감)
        reward -= cfg.gamma * rule_violations

        # 슬리피지+수수료 페널티
        reward -= cfg.delta * slippage_fees

        # 클리핑
        reward = max(cfg.min_reward, min(cfg.max_reward, reward))
        logger.debug(
            "trading_reward pnl=%.4f sharpe=%.3f mdd_delta=%.4f "
            "violations=%d fees=%.4f → reward=%.4f",
            pnl, sharpe_ratio, mdd_delta, rule_violations, slippage_fees, reward,
        )
        return reward

    def compute_from_trade_record(
        self,
        pnl: Decimal,
        sharpe_ratio: float,
        mdd_delta: float,
        rule_violations: int,
        slippage: Decimal,
        fees: Decimal,
        no_trade: bool = False,
    ) -> float:
        """
        PnL 모듈의 TradeRecord 수치를 그대로 받아 보상을 계산합니다.
        """
        return self.compute(
            pnl=float(pnl),
            sharpe_ratio=sharpe_ratio,
            mdd_delta=mdd_delta,
            rule_violations=rule_violations,
            slippage_fees=float(slippage + fees),
            no_trade=no_trade,
        )


# ---------------------------------------------------------------------------
# 싱글톤 관리
# ---------------------------------------------------------------------------

_reward_calc_instance: Optional[RewardCalculator] = None
_trading_calc_instance: Optional[TradingRewardCalculator] = None


def get_reward_calculator() -> RewardCalculator:
    """RewardCalculator 싱글톤 인스턴스"""
    global _reward_calc_instance
    if _reward_calc_instance is None:
        _reward_calc_instance = RewardCalculator()
    return _reward_calc_instance


def init_reward_calculator(config: Optional[Dict[str, Any]] = None) -> RewardCalculator:
    """RewardCalculator 초기화 (설정 적용)"""
    global _reward_calc_instance
    _reward_calc_instance = RewardCalculator(config=config)
    return _reward_calc_instance


def get_trading_reward_calculator() -> TradingRewardCalculator:
    """TradingRewardCalculator 싱글톤 인스턴스"""
    global _trading_calc_instance
    if _trading_calc_instance is None:
        _trading_calc_instance = TradingRewardCalculator()
    return _trading_calc_instance

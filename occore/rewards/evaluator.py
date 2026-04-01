"""
OZ_A2M Rewards System — 배치 평가기

오프라인(배치) 에이전트 품질 평가를 수행합니다.

평가 항목:
  - 정확도 / 성공률 (accuracy)
  - 재현성 — 같은 입력에서 결과의 분산이 과도하지 않은가 (reproducibility)
  - 툴 사용 적합성 — 필요할 때 호출하고 불필요한 호출은 없는가 (tool_use)
  - 정책 준수 — 금융 컴플라이언스·안전 규칙 위반 없는가 (policy_compliance)

결과로 나온 offline_reward 점수는 RewardScore.offline_reward 에 통합됩니다.
"""

import logging
import statistics
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from .models import (
    AgentSession,
    BatchEvalResult,
    RewardScore,
    DEFAULT_REWARD_CONFIG,
)
from .calculator import RewardCalculator

logger = logging.getLogger(__name__)

# 배치 평가 기본 가중치
_WEIGHTS: Dict[str, float] = {
    "accuracy": DEFAULT_REWARD_CONFIG["accuracy_weight"],
    "reproducibility": DEFAULT_REWARD_CONFIG["reproducibility_weight"],
    "tool_use": DEFAULT_REWARD_CONFIG["tool_use_weight"],
    "policy_compliance": DEFAULT_REWARD_CONFIG["policy_compliance_weight"],
}


class BatchEvaluator:
    """
    오프라인 배치 에이전트 품질 평가기

    사용 예시:
        evaluator = BatchEvaluator()
        sessions = [...]  # AgentSession 리스트

        result = evaluator.evaluate_batch(sessions)
        # result.avg_total_reward, result.scores, ...
    """

    def __init__(
        self,
        reward_calculator: Optional[RewardCalculator] = None,
        weights: Optional[Dict[str, float]] = None,
        max_offline_reward: float = 20.0,
        min_offline_reward: float = -20.0,
    ) -> None:
        self._calc = reward_calculator or RewardCalculator()
        self._weights = {**_WEIGHTS, **(weights or {})}
        self._max = max_offline_reward
        self._min = min_offline_reward

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def evaluate_session(self, session: AgentSession) -> RewardScore:
        """
        단일 세션을 평가하고 RewardScore (online + offline 통합)를 반환합니다.
        """
        # 온라인 보상 먼저 계산
        score = self._calc.compute_session_reward(session)

        # 오프라인 4개 지표 계산
        accuracy = self._accuracy_score(session)
        reproducibility = self._reproducibility_score(session)
        tool_use = self._tool_use_score(session)
        policy = self._policy_compliance_score(session)

        offline = (
            self._weights["accuracy"] * accuracy
            + self._weights["reproducibility"] * reproducibility
            + self._weights["tool_use"] * tool_use
            + self._weights["policy_compliance"] * policy
        )
        # 0~1 범위 가중합을 [min, max] 범위로 선형 매핑 (0→min, 1→max)
        offline = offline * (self._max - self._min) + self._min
        # 가중치 합산 부동소수점 오류 방지용 방어적 클리핑
        offline = max(self._min, min(self._max, offline))

        # RewardScore 는 frozen=False dataclass 이므로 직접 업데이트
        score.offline_reward = offline
        score.total_reward = score.online_reward + score.offline_reward + score.guardrail_penalty

        logger.info(
            "batch_eval agent=%s session=%s offline=%.2f total=%.2f",
            session.agent_id, session.session_id, offline, score.total_reward,
        )
        return score

    def evaluate_batch(self, sessions: List[AgentSession]) -> BatchEvalResult:
        """
        세션 리스트를 일괄 평가하고 BatchEvalResult를 반환합니다.
        """
        if not sessions:
            return BatchEvalResult(
                eval_id=str(uuid.uuid4()),
                evaluated_at=datetime.now(timezone.utc),
                session_count=0,
            )

        scores: List[RewardScore] = [self.evaluate_session(s) for s in sessions]

        total_rewards = [s.total_reward for s in scores]
        online_rewards = [s.online_reward for s in scores]
        offline_rewards = [s.offline_reward for s in scores]
        guardrail_penalties = [s.guardrail_penalty for s in scores]

        best = max(scores, key=lambda s: s.total_reward)
        worst = min(scores, key=lambda s: s.total_reward)

        violated = sum(1 for s in scores if s.violation_count > 0)

        result = BatchEvalResult(
            eval_id=str(uuid.uuid4()),
            evaluated_at=datetime.now(timezone.utc),
            session_count=len(sessions),
            avg_total_reward=statistics.mean(total_rewards),
            avg_online_reward=statistics.mean(online_rewards),
            avg_offline_reward=statistics.mean(offline_rewards),
            avg_guardrail_penalty=statistics.mean(guardrail_penalties),
            top_session_id=best.session_id,
            bottom_session_id=worst.session_id,
            violation_rate=violated / len(sessions),
            scores=scores,
        )
        logger.info(
            "batch_eval_complete sessions=%d avg_total=%.2f violation_rate=%.1f%%",
            len(sessions), result.avg_total_reward, result.violation_rate * 100,
        )
        return result

    # ------------------------------------------------------------------
    # 내부 채점 함수 (0.0 ~ 1.0 반환)
    # ------------------------------------------------------------------

    def _accuracy_score(self, session: AgentSession) -> float:
        """
        정확도/성공률 점수 (0~1)

        세션 성공 여부 + 사용자 피드백을 가중 평균합니다.
        """
        base = 0.5  # 기본 중립

        # 세션 성공 여부
        if session.success is True:
            base = 0.8
        elif session.success is False:
            base = 0.2

        # 사용자 피드백이 있으면 추가 반영 (-1~+1 → 0~1 변환)
        if session.user_feedback is not None:
            feedback_normalized = (session.user_feedback + 1.0) / 2.0  # -1~+1 → 0~1
            base = 0.7 * base + 0.3 * feedback_normalized

        return max(0.0, min(1.0, base))

    def _reproducibility_score(self, session: AgentSession) -> float:
        """
        재현성 점수 (0~1)

        동일 유형 이벤트의 raw_score 분산이 낮을수록 높은 점수.
        이벤트가 부족하면 중립(0.5).
        """
        if len(session.events) < 3:
            return 0.5

        raw_scores = [e.raw_score for e in session.events]
        try:
            stdev = statistics.stdev(raw_scores)
        except statistics.StatisticsError:
            return 0.5

        # stdev 가 0이면 완벽한 재현성, 10 이상이면 불안정
        score = max(0.0, 1.0 - stdev / 10.0)
        return min(1.0, score)

    def _tool_use_score(self, session: AgentSession) -> float:
        """
        툴 사용 적합성 점수 (0~1)

        불필요한 툴 호출 비율이 낮을수록 높은 점수.
        """
        if session.tool_calls == 0:
            return 1.0  # 툴 호출이 없으면 불필요 호출도 없음

        unnecessary_ratio = session.unnecessary_tool_calls / session.tool_calls
        return max(0.0, 1.0 - unnecessary_ratio)

    def _policy_compliance_score(self, session: AgentSession) -> float:
        """
        정책 준수 점수 (0~1)

        위반 횟수가 많을수록 점수 하락.
        """
        if session.policy_violations == 0:
            return 1.0

        # 위반 1건당 0.25 차감, 최소 0
        penalty = 0.25 * session.policy_violations
        return max(0.0, 1.0 - penalty)


# ---------------------------------------------------------------------------
# 싱글톤 관리
# ---------------------------------------------------------------------------

_evaluator_instance: Optional[BatchEvaluator] = None


def get_batch_evaluator() -> BatchEvaluator:
    """BatchEvaluator 싱글톤 인스턴스"""
    global _evaluator_instance
    if _evaluator_instance is None:
        _evaluator_instance = BatchEvaluator()
    return _evaluator_instance


def init_batch_evaluator(
    reward_calculator: Optional[RewardCalculator] = None,
    weights: Optional[Dict[str, float]] = None,
) -> BatchEvaluator:
    """BatchEvaluator 초기화"""
    global _evaluator_instance
    _evaluator_instance = BatchEvaluator(
        reward_calculator=reward_calculator,
        weights=weights,
    )
    return _evaluator_instance

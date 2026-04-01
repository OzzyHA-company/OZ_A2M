#!/usr/bin/env python3
"""
보상 시스템(Rewards System) 테스트

occore.rewards 모듈 전체를 검증합니다:
- RewardCalculator: 온라인 이벤트 처리 및 세션 집계
- TradingRewardCalculator: 리스크 조정 보상 공식
- BatchEvaluator: 오프라인 배치 품질 평가
"""

import sys
import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from occore.rewards import (
    AgentAction,
    AgentSession,
    BatchEvaluator,
    BatchEvalResult,
    RewardCalculator,
    RewardEvent,
    RewardEventType,
    RewardScore,
    SafetyViolationType,
    TradingRewardCalculator,
    TradingRewardConfig,
    get_reward_calculator,
    get_trading_reward_calculator,
    init_reward_calculator,
    get_batch_evaluator,
    init_batch_evaluator,
    DEFAULT_REWARD_CONFIG,
    DEFAULT_TRADING_REWARD_CONFIG,
)


def _make_event(
    event_type: RewardEventType,
    agent_id: str = "agent-01",
    session_id: str = "sess-01",
    action: AgentAction = AgentAction.TOOL_CALL,
    safety_violation: SafetyViolationType | None = None,
    metadata: dict | None = None,
) -> RewardEvent:
    return RewardEvent(
        event_id=f"evt-{event_type.value}",
        agent_id=agent_id,
        session_id=session_id,
        event_type=event_type,
        timestamp=datetime.now(timezone.utc),
        action=action,
        safety_violation=safety_violation,
        metadata=metadata or {},
    )


def _make_session(
    session_id: str = "sess-01",
    agent_id: str = "agent-01",
    events: list | None = None,
    success: bool | None = True,
    user_feedback: float | None = None,
) -> AgentSession:
    session = AgentSession(
        session_id=session_id,
        agent_id=agent_id,
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        success=success,
        user_feedback=user_feedback,
    )
    for evt in (events or []):
        session.add_event(evt)
    return session


# ===========================================================================
# RewardCalculator 테스트
# ===========================================================================

class TestRewardCalculator(unittest.TestCase):

    def setUp(self):
        self.calc = RewardCalculator()

    # ---- 성공 이벤트 ----

    def test_task_success_positive_reward(self):
        evt = _make_event(RewardEventType.TASK_SUCCESS)
        score = self.calc.process_event(evt)
        self.assertGreater(score, 0)

    def test_no_trade_positive_reward(self):
        evt = _make_event(RewardEventType.NO_TRADE)
        score = self.calc.process_event(evt)
        self.assertGreater(score, 0)

    def test_safe_decision_positive_reward(self):
        evt = _make_event(RewardEventType.SAFE_DECISION)
        score = self.calc.process_event(evt)
        self.assertGreater(score, 0)

    def test_evidence_provided_positive_reward(self):
        evt = _make_event(RewardEventType.EVIDENCE_PROVIDED)
        score = self.calc.process_event(evt)
        self.assertGreater(score, 0)

    # ---- 페널티 이벤트 ----

    def test_task_failure_negative_reward(self):
        evt = _make_event(RewardEventType.TASK_FAILURE)
        score = self.calc.process_event(evt)
        self.assertLess(score, 0)

    def test_cost_excess_penalty(self):
        evt = _make_event(
            RewardEventType.COST_EXCESS,
            metadata={"cost_units": 5.0},
        )
        score = self.calc.process_event(evt)
        self.assertLess(score, 0)

    def test_latency_excess_penalty(self):
        evt = _make_event(
            RewardEventType.LATENCY_EXCESS,
            metadata={"excess_seconds": 3.0},
        )
        score = self.calc.process_event(evt)
        self.assertLess(score, 0)

    def test_unnecessary_tool_call_penalty(self):
        evt = _make_event(RewardEventType.UNNECESSARY_TOOL_CALL)
        score = self.calc.process_event(evt)
        self.assertLess(score, 0)

    def test_false_confidence_penalty(self):
        evt = _make_event(RewardEventType.FALSE_CONFIDENCE)
        score = self.calc.process_event(evt)
        self.assertLess(score, 0)

    # ---- 안전 위반 (강한 페널티) ----

    def test_pii_leak_severe_penalty(self):
        evt = _make_event(
            RewardEventType.SAFETY_VIOLATION,
            safety_violation=SafetyViolationType.PII_LEAK,
        )
        score = self.calc.process_event(evt)
        self.assertLessEqual(score, -30.0)

    def test_key_leak_severe_penalty(self):
        evt = _make_event(
            RewardEventType.SAFETY_VIOLATION,
            safety_violation=SafetyViolationType.KEY_LEAK,
        )
        score = self.calc.process_event(evt)
        self.assertLessEqual(score, -30.0)

    def test_prompt_injection_severe_penalty(self):
        evt = _make_event(
            RewardEventType.SAFETY_VIOLATION,
            safety_violation=SafetyViolationType.PROMPT_INJECTION,
        )
        score = self.calc.process_event(evt)
        self.assertLessEqual(score, -30.0)

    def test_safety_violation_stronger_than_task_failure(self):
        """안전 위반 페널티는 일반 실패보다 강해야 한다."""
        failure_evt = _make_event(RewardEventType.TASK_FAILURE)
        safety_evt = _make_event(
            RewardEventType.SAFETY_VIOLATION,
            safety_violation=SafetyViolationType.PII_LEAK,
        )
        failure_score = self.calc.process_event(failure_evt)
        safety_score = self.calc.process_event(safety_evt)
        self.assertLess(safety_score, failure_score)

    # ---- 세션 집계 ----

    def test_session_reward_all_success(self):
        events = [
            _make_event(RewardEventType.TASK_SUCCESS),
            _make_event(RewardEventType.EVIDENCE_PROVIDED),
        ]
        session = _make_session(events=events)
        score = self.calc.compute_session_reward(session)
        self.assertIsInstance(score, RewardScore)
        self.assertGreater(score.online_reward, 0)
        self.assertEqual(score.violation_count, 0)

    def test_session_reward_with_violation(self):
        events = [
            _make_event(RewardEventType.TASK_SUCCESS),
            _make_event(
                RewardEventType.SAFETY_VIOLATION,
                safety_violation=SafetyViolationType.PII_LEAK,
            ),
        ]
        session = _make_session(events=events)
        score = self.calc.compute_session_reward(session)
        self.assertEqual(score.violation_count, 1)
        self.assertLess(score.safety_penalty, 0)

    def test_session_reward_clipping(self):
        """온라인 보상은 설정된 클리핑 범위를 벗어나지 않아야 한다."""
        events = [_make_event(RewardEventType.TASK_SUCCESS)] * 20
        session = _make_session(events=events)
        score = self.calc.compute_session_reward(session)
        self.assertLessEqual(score.online_reward, DEFAULT_REWARD_CONFIG["max_online_reward"])

    def test_session_score_stored_and_retrievable(self):
        session = _make_session(session_id="sess-retrieve")
        self.calc.compute_session_reward(session)
        retrieved = self.calc.get_session_score("sess-retrieve")
        self.assertIsNotNone(retrieved)

    def test_total_reward_equals_sum(self):
        """total_reward = online + offline + guardrail 이어야 한다."""
        session = _make_session(events=[_make_event(RewardEventType.TASK_SUCCESS)])
        score = self.calc.compute_session_reward(session)
        expected = score.online_reward + score.offline_reward + score.guardrail_penalty
        self.assertAlmostEqual(score.total_reward, expected, places=6)

    # ---- 싱글톤 ----

    def test_singleton(self):
        c1 = get_reward_calculator()
        c2 = get_reward_calculator()
        self.assertIs(c1, c2)

    def test_init_creates_new_instance(self):
        c1 = get_reward_calculator()
        c2 = init_reward_calculator()
        self.assertIsNot(c1, c2)


# ===========================================================================
# TradingRewardCalculator 테스트
# ===========================================================================

class TestTradingRewardCalculator(unittest.TestCase):

    def setUp(self):
        self.calc = TradingRewardCalculator()

    def test_no_trade_positive(self):
        """no_trade=True 이면 소폭 양의 보상."""
        reward = self.calc.compute(
            pnl=0.0, sharpe_ratio=0.0, mdd_delta=0.0,
            rule_violations=0, slippage_fees=0.0, no_trade=True,
        )
        self.assertGreater(reward, 0)

    def test_profit_with_good_sharpe_positive(self):
        """좋은 샤프 비율 + 수익 → 양의 보상."""
        reward = self.calc.compute(
            pnl=100.0, sharpe_ratio=2.0, mdd_delta=0.0,
            rule_violations=0, slippage_fees=1.0,
        )
        self.assertGreater(reward, 0)

    def test_high_mdd_reduces_reward(self):
        """MDD 증가는 보상을 감소시켜야 한다."""
        low_mdd = self.calc.compute(
            pnl=50.0, sharpe_ratio=1.5, mdd_delta=0.01,
            rule_violations=0, slippage_fees=0.5,
        )
        high_mdd = self.calc.compute(
            pnl=50.0, sharpe_ratio=1.5, mdd_delta=0.20,
            rule_violations=0, slippage_fees=0.5,
        )
        self.assertGreater(low_mdd, high_mdd)

    def test_rule_violation_reduces_reward(self):
        """규칙 위반은 강한 페널티를 부과해야 한다."""
        no_viol = self.calc.compute(
            pnl=50.0, sharpe_ratio=1.0, mdd_delta=0.0,
            rule_violations=0, slippage_fees=0.0,
        )
        with_viol = self.calc.compute(
            pnl=50.0, sharpe_ratio=1.0, mdd_delta=0.0,
            rule_violations=2, slippage_fees=0.0,
        )
        self.assertGreater(no_viol, with_viol)

    def test_zero_sharpe_zeroes_risk_adjusted_return(self):
        """샤프 비율 0이면 리스크 조정 수익 기여분이 0이어야 한다."""
        cfg = self.calc.config
        reward = self.calc.compute(
            pnl=100.0, sharpe_ratio=0.0, mdd_delta=0.0,
            rule_violations=0, slippage_fees=0.0,
        )
        # alpha * 0 = 0; fees delta도 0 → reward should be exactly 0
        self.assertAlmostEqual(reward, 0.0, places=6)

    def test_reward_clipping(self):
        """보상은 max_reward/min_reward 클리핑을 초과하지 않아야 한다."""
        cfg = self.calc.config
        r_high = self.calc.compute(
            pnl=1_000_000.0, sharpe_ratio=10.0, mdd_delta=0.0,
            rule_violations=0, slippage_fees=0.0,
        )
        self.assertLessEqual(r_high, cfg.max_reward)

        r_low = self.calc.compute(
            pnl=-1_000_000.0, sharpe_ratio=0.0, mdd_delta=1.0,
            rule_violations=100, slippage_fees=1_000.0,
        )
        self.assertGreaterEqual(r_low, cfg.min_reward)

    def test_compute_from_trade_record(self):
        """Decimal 기반 PnL 입력도 정상 처리해야 한다."""
        reward = self.calc.compute_from_trade_record(
            pnl=Decimal("200.00"),
            sharpe_ratio=1.5,
            mdd_delta=0.02,
            rule_violations=0,
            slippage=Decimal("2.00"),
            fees=Decimal("1.50"),
        )
        self.assertIsInstance(reward, float)

    def test_negative_sharpe_treated_as_zero(self):
        """음수 샤프 비율은 리스크 조정 수익을 0으로 취급해야 한다."""
        reward_neg = self.calc.compute(
            pnl=50.0, sharpe_ratio=-1.0, mdd_delta=0.0,
            rule_violations=0, slippage_fees=0.0,
        )
        reward_zero = self.calc.compute(
            pnl=50.0, sharpe_ratio=0.0, mdd_delta=0.0,
            rule_violations=0, slippage_fees=0.0,
        )
        self.assertAlmostEqual(reward_neg, reward_zero, places=6)

    def test_custom_config(self):
        """커스텀 설정으로 초기화 가능해야 한다."""
        cfg = TradingRewardConfig(alpha=2.0, beta=3.0, gamma=10.0, delta=1.0)
        calc = TradingRewardCalculator(config=cfg)
        self.assertEqual(calc.config.alpha, 2.0)

    def test_singleton(self):
        c1 = get_trading_reward_calculator()
        c2 = get_trading_reward_calculator()
        self.assertIs(c1, c2)


# ===========================================================================
# BatchEvaluator 테스트
# ===========================================================================

class TestBatchEvaluator(unittest.TestCase):

    def setUp(self):
        self.evaluator = BatchEvaluator()

    def _success_session(self, session_id: str = "sess-ok") -> AgentSession:
        events = [
            _make_event(RewardEventType.TASK_SUCCESS, session_id=session_id),
            _make_event(RewardEventType.EVIDENCE_PROVIDED, session_id=session_id),
        ]
        return _make_session(
            session_id=session_id, events=events, success=True, user_feedback=0.8
        )

    def _failure_session(self, session_id: str = "sess-fail") -> AgentSession:
        events = [
            _make_event(RewardEventType.TASK_FAILURE, session_id=session_id),
            _make_event(
                RewardEventType.SAFETY_VIOLATION,
                session_id=session_id,
                safety_violation=SafetyViolationType.PII_LEAK,
            ),
        ]
        return _make_session(
            session_id=session_id, events=events, success=False, user_feedback=-0.5
        )

    def test_evaluate_session_returns_reward_score(self):
        score = self.evaluator.evaluate_session(self._success_session())
        self.assertIsInstance(score, RewardScore)

    def test_success_session_higher_than_failure(self):
        good = self.evaluator.evaluate_session(self._success_session("good"))
        bad = self.evaluator.evaluate_session(self._failure_session("bad"))
        self.assertGreater(good.total_reward, bad.total_reward)

    def test_offline_reward_in_range(self):
        score = self.evaluator.evaluate_session(self._success_session())
        self.assertGreaterEqual(score.offline_reward, self.evaluator._min)
        self.assertLessEqual(score.offline_reward, self.evaluator._max)

    def test_evaluate_batch_empty(self):
        result = self.evaluator.evaluate_batch([])
        self.assertIsInstance(result, BatchEvalResult)
        self.assertEqual(result.session_count, 0)

    def test_evaluate_batch_returns_correct_count(self):
        sessions = [
            self._success_session("s1"),
            self._success_session("s2"),
            self._failure_session("s3"),
        ]
        result = self.evaluator.evaluate_batch(sessions)
        self.assertEqual(result.session_count, 3)
        self.assertEqual(len(result.scores), 3)

    def test_batch_violation_rate(self):
        sessions = [
            self._success_session("v1"),   # 위반 없음
            self._failure_session("v2"),   # 위반 있음
        ]
        result = self.evaluator.evaluate_batch(sessions)
        # failure_session 에 SAFETY_VIOLATION 있으므로 violation_rate 0.5
        self.assertAlmostEqual(result.violation_rate, 0.5, places=2)

    def test_batch_top_bottom_session(self):
        sessions = [
            self._success_session("top"),
            self._failure_session("bottom"),
        ]
        result = self.evaluator.evaluate_batch(sessions)
        self.assertEqual(result.top_session_id, "top")
        self.assertEqual(result.bottom_session_id, "bottom")

    def test_tool_use_score_no_unnecessary(self):
        """불필요 툴 호출이 없으면 tool_use_score 1.0이어야 한다."""
        session = _make_session(session_id="toolok")
        # 툴 호출 2회 추가
        for i in range(2):
            evt = _make_event(RewardEventType.TASK_SUCCESS, session_id="toolok")
            evt.action = AgentAction.TOOL_CALL
            session.add_event(evt)

        score = self.evaluator._tool_use_score(session)
        self.assertAlmostEqual(score, 1.0, places=6)

    def test_policy_compliance_score_with_violations(self):
        """위반이 있으면 compliance 점수가 1.0 미만이어야 한다."""
        session = _make_session(session_id="viol")
        evt = _make_event(
            RewardEventType.SAFETY_VIOLATION,
            session_id="viol",
            safety_violation=SafetyViolationType.PII_LEAK,
        )
        session.add_event(evt)
        score = self.evaluator._policy_compliance_score(session)
        self.assertLess(score, 1.0)

    def test_singleton(self):
        e1 = get_batch_evaluator()
        e2 = get_batch_evaluator()
        self.assertIs(e1, e2)

    def test_init_creates_new_instance(self):
        e1 = get_batch_evaluator()
        e2 = init_batch_evaluator()
        self.assertIsNot(e1, e2)


# ===========================================================================
# 모델 테스트
# ===========================================================================

class TestAgentSession(unittest.TestCase):

    def test_add_event_increments_tool_calls(self):
        session = _make_session()
        evt = _make_event(RewardEventType.TASK_SUCCESS)
        evt.action = AgentAction.TOOL_CALL
        session.add_event(evt)
        self.assertEqual(session.tool_calls, 1)

    def test_add_event_tracks_policy_violations(self):
        session = _make_session()
        evt = _make_event(
            RewardEventType.SAFETY_VIOLATION,
            safety_violation=SafetyViolationType.KEY_LEAK,
        )
        session.add_event(evt)
        self.assertEqual(session.policy_violations, 1)

    def test_add_event_tracks_unnecessary_tool_calls(self):
        session = _make_session()
        evt = _make_event(RewardEventType.UNNECESSARY_TOOL_CALL)
        session.add_event(evt)
        self.assertEqual(session.unnecessary_tool_calls, 1)

    def test_duration_seconds(self):
        session = _make_session()
        duration = session.duration_seconds
        self.assertIsNotNone(duration)
        self.assertGreaterEqual(duration, 0)


class TestRewardScorePostInit(unittest.TestCase):

    def test_total_reward_computed_on_init(self):
        score = RewardScore(
            session_id="s1",
            agent_id="a1",
            timestamp=datetime.now(timezone.utc),
            online_reward=10.0,
            offline_reward=5.0,
            guardrail_penalty=-3.0,
        )
        self.assertAlmostEqual(score.total_reward, 12.0, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)

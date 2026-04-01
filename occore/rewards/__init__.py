"""
OZ_A2M Rewards System

AI 에이전트 보상(Reward) 시스템 — 3-Layer 설계

Layer 1 (온라인): 실시간 보상 — 작업 성공/실패, 비용·시간 페널티, 안전 페널티
Layer 2 (오프라인): 배치 품질 평가 — 정확도, 재현성, 툴 사용 적합성
Layer 3 (가드레일): 금지 행동 하드 차단 및 허용 목록(allowlist) 관리

트레이딩 봇에는 리스크-조정 보상(Risk-Adjusted Reward)을 적용합니다:
  +α × (Sharpe 기반 리스크 조정 수익)
  -β × 최대낙폭(MDD) 증가
  -γ × 규칙 위반(포지션 한도/손절/빈도)
  -δ × 슬리피지+수수료
"""

from .models import (
    RewardEventType,
    SafetyViolationType,
    AgentAction,
    RewardEvent,
    RewardScore,
    AgentSession,
    BatchEvalResult,
    TradingRewardConfig,
    DEFAULT_REWARD_CONFIG,
    DEFAULT_TRADING_REWARD_CONFIG,
)
from .calculator import (
    RewardCalculator,
    TradingRewardCalculator,
    get_reward_calculator,
    get_trading_reward_calculator,
    init_reward_calculator,
)
from .evaluator import (
    BatchEvaluator,
    get_batch_evaluator,
    init_batch_evaluator,
)

__all__ = [
    # Enums
    "RewardEventType",
    "SafetyViolationType",
    "AgentAction",
    # Data models
    "RewardEvent",
    "RewardScore",
    "AgentSession",
    "BatchEvalResult",
    "TradingRewardConfig",
    # Configs
    "DEFAULT_REWARD_CONFIG",
    "DEFAULT_TRADING_REWARD_CONFIG",
    # Calculators
    "RewardCalculator",
    "TradingRewardCalculator",
    "get_reward_calculator",
    "get_trading_reward_calculator",
    "init_reward_calculator",
    # Evaluators
    "BatchEvaluator",
    "get_batch_evaluator",
    "init_batch_evaluator",
]

"""
OZ_A2M Rewards System — 데이터 모델

AI 에이전트 보상 계산에 사용되는 모든 데이터 모델을 정의합니다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 열거형 정의
# ---------------------------------------------------------------------------

class RewardEventType(Enum):
    """보상 이벤트 유형"""
    # 성공 이벤트
    TASK_SUCCESS = "task_success"           # 목표 달성
    NO_TRADE = "no_trade"                   # 최선이 '거래 안 함'인 경우 정답 인정
    SAFE_DECISION = "safe_decision"         # 안전한 의사결정 (불확실 시 자동 중단 등)
    EVIDENCE_PROVIDED = "evidence_provided" # 근거 링크/스냅샷 제공 가산점
    # 페널티 이벤트
    TASK_FAILURE = "task_failure"           # 목표 미달성
    COST_EXCESS = "cost_excess"             # 비용(토큰/API) 초과
    LATENCY_EXCESS = "latency_excess"       # 응답 지연 초과
    UNNECESSARY_TOOL_CALL = "unnecessary_tool_call"  # 불필요한 툴 호출
    SAFETY_VIOLATION = "safety_violation"   # 안전 정책 위반
    RULE_VIOLATION = "rule_violation"       # 트레이딩 규칙 위반 (포지션 한도 등)
    FALSE_CONFIDENCE = "false_confidence"   # 근거 없는 확신 (금융 답변)
    # 트레이딩 전용
    TRADE_PROFIT = "trade_profit"           # 거래 수익
    TRADE_LOSS = "trade_loss"               # 거래 손실
    MDD_INCREASE = "mdd_increase"           # 최대낙폭 증가
    SLIPPAGE_FEE = "slippage_fee"           # 슬리피지+수수료 발생


class SafetyViolationType(Enum):
    """안전 위반 유형"""
    PROMPT_INJECTION = "prompt_injection"           # 프롬프트 인젝션 의심
    UNAUTHORIZED_FILE_ACCESS = "unauthorized_file_access"  # 권한 밖 파일 접근
    UNAUTHORIZED_COMMAND = "unauthorized_command"   # 권한 밖 명령 실행 시도
    PII_LEAK = "pii_leak"                           # 개인정보 유출 패턴
    KEY_LEAK = "key_leak"                           # API 키/시크릿 유출
    FALSE_FINANCIAL_CLAIM = "false_financial_claim" # 금융 허위 정보
    POSITION_LIMIT_BREACH = "position_limit_breach" # 포지션 한도 초과
    STOP_LOSS_SKIP = "stop_loss_skip"               # 손절 규칙 무시
    FREQUENCY_VIOLATION = "frequency_violation"     # 거래 빈도 제한 위반


class AgentAction(Enum):
    """에이전트 행동 분류"""
    TOOL_CALL = "tool_call"
    LLM_INFERENCE = "llm_inference"
    ORDER_PLACEMENT = "order_placement"
    DATA_FETCH = "data_fetch"
    REPORT_GENERATION = "report_generation"
    SIGNAL_GENERATION = "signal_generation"
    RISK_CHECK = "risk_check"
    NO_OP = "no_op"


# ---------------------------------------------------------------------------
# 데이터 클래스 정의
# ---------------------------------------------------------------------------

@dataclass
class RewardEvent:
    """개별 보상 이벤트"""
    event_id: str
    agent_id: str
    session_id: str
    event_type: RewardEventType
    timestamp: datetime
    # 선택 필드
    action: Optional[AgentAction] = None
    safety_violation: Optional[SafetyViolationType] = None
    raw_score: float = 0.0          # 이 이벤트만의 원점수
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RewardScore:
    """에이전트 세션 보상 점수"""
    session_id: str
    agent_id: str
    timestamp: datetime
    # 3-Layer 점수
    online_reward: float = 0.0          # 온라인(실시간) 보상 합계
    offline_reward: float = 0.0         # 오프라인(배치) 품질 점수
    guardrail_penalty: float = 0.0      # 가드레일 페널티 (항상 ≤ 0)
    total_reward: float = field(init=False)
    # 세부 항목
    task_success_score: float = 0.0
    cost_penalty: float = 0.0
    latency_penalty: float = 0.0
    safety_penalty: float = 0.0
    trading_reward: float = 0.0         # 트레이딩 전용 리스크 조정 보상
    # 이벤트 통계
    total_events: int = 0
    violation_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.total_reward = (
            self.online_reward
            + self.offline_reward
            + self.guardrail_penalty
        )


@dataclass
class AgentSession:
    """에이전트 세션 정보 (배치 평가 입력)"""
    session_id: str
    agent_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    events: List[RewardEvent] = field(default_factory=list)
    # 결과
    success: Optional[bool] = None          # 세션 성공 여부
    user_feedback: Optional[float] = None   # 사용자 피드백 (-1 ~ +1)
    tool_calls: int = 0
    unnecessary_tool_calls: int = 0
    policy_violations: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_event(self, event: RewardEvent) -> None:
        """이벤트 추가"""
        self.events.append(event)
        self.tool_calls += 1 if event.action == AgentAction.TOOL_CALL else 0
        if event.event_type == RewardEventType.SAFETY_VIOLATION:
            self.policy_violations += 1
        if event.event_type == RewardEventType.UNNECESSARY_TOOL_CALL:
            self.unnecessary_tool_calls += 1

    @property
    def duration_seconds(self) -> Optional[float]:
        """세션 소요 시간(초)"""
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


@dataclass
class BatchEvalResult:
    """배치 평가 결과"""
    eval_id: str
    evaluated_at: datetime
    session_count: int
    avg_total_reward: float = 0.0
    avg_online_reward: float = 0.0
    avg_offline_reward: float = 0.0
    avg_guardrail_penalty: float = 0.0
    top_session_id: Optional[str] = None    # 최고 점수 세션
    bottom_session_id: Optional[str] = None # 최저 점수 세션
    violation_rate: float = 0.0             # 전체 세션 중 위반 비율
    scores: List[RewardScore] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradingRewardConfig:
    """트레이딩 봇 전용 보상 설정"""
    # 보상 계수
    alpha: float = 1.0          # 리스크 조정 수익 가중치
    beta: float = 2.0           # MDD 증가 페널티 가중치 (강하게)
    gamma: float = 5.0          # 규칙 위반 페널티 가중치 (매우 강하게)
    delta: float = 0.5          # 슬리피지+수수료 페널티 가중치
    # 한도
    max_mdd_threshold: float = 0.10     # 최대 허용 MDD (10%)
    max_position_ratio: float = 0.20    # 최대 포지션 비율 (20%)
    min_sharpe_ratio: float = 0.5       # 최소 샤프 비율
    # 보상 클리핑
    max_reward: float = 100.0
    min_reward: float = -100.0


# ---------------------------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------------------------

DEFAULT_REWARD_CONFIG: Dict[str, Any] = {
    # 온라인 보상 계수
    "task_success_reward": 10.0,
    "task_failure_penalty": -5.0,
    "no_trade_reward": 2.0,
    "safe_decision_reward": 3.0,
    "evidence_reward": 1.0,
    # 비용/지연 페널티
    "cost_penalty_per_unit": -0.1,
    "latency_penalty_per_second": -0.2,
    "unnecessary_tool_penalty": -1.0,
    # 안전 페널티 (강도별)
    "safety_violation_penalty": {
        "prompt_injection": -50.0,
        "unauthorized_file_access": -30.0,
        "unauthorized_command": -30.0,
        "pii_leak": -50.0,
        "key_leak": -50.0,
        "false_financial_claim": -20.0,
        "position_limit_breach": -25.0,
        "stop_loss_skip": -25.0,
        "frequency_violation": -10.0,
    },
    "false_confidence_penalty": -5.0,
    # 오프라인 배치 평가 가중치
    "accuracy_weight": 0.4,
    "reproducibility_weight": 0.2,
    "tool_use_weight": 0.2,
    "policy_compliance_weight": 0.2,
    # 보상 클리핑
    "max_online_reward": 50.0,
    "min_online_reward": -100.0,
}

DEFAULT_TRADING_REWARD_CONFIG = TradingRewardConfig()

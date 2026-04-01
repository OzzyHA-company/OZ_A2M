"""
TradingAgents Integration - LLM 에이전트와 Reward System 연동

TauricResearch/TradingAgents (45.6k stars) 연동
7개 AI 에이전트 앙상블 결과를 Reward System에 통합

Features:
- 7개 에이전트 투표 집계
- Confidence Score 계산
- Reward Multiplier 적용
- 에이전트별 성과 추적
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from collections import Counter
import sys
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AgentVote:
    """개별 에이전트 투표"""
    agent_name: str
    decision: str  # buy, sell, hold
    confidence: float  # 0.0 ~ 1.0
    reasoning: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class ConsensusResult:
    """합의 결과"""
    signal: str  # buy, sell, hold
    confidence: float  # 0.0 ~ 1.0
    strength: str  # strong, moderate, weak, neutral
    votes: Dict[str, AgentVote]
    agreement_ratio: float  # 동의 비율
    dissent_agents: List[str]  # 반대한 에이전트
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

    def to_reward_multiplier(self) -> float:
        """
        Confidence를 Reward Multiplier로 변환

        0.0 ~ 1.0 -> 0.5 ~ 1.5
        """
        # 기본 변환: 0.5 ~ 1.5
        base_multiplier = 0.5 + self.confidence

        # 강도 별 추가 볼너스
        strength_bonus = {
            'strong': 0.2,
            'moderate': 0.1,
            'weak': 0.0,
            'neutral': -0.1,
        }.get(self.strength, 0.0)

        # 합의율 별 추가 볼너스
        agreement_bonus = (self.agreement_ratio - 0.5) * 0.2

        multiplier = base_multiplier + strength_bonus + agreement_bonus
        return max(0.5, min(1.5, multiplier))


class TradingAgentsRewardBridge:
    """
    TradingAgents와 Reward System 연결 브릿지

    FinRL_DeepSeek 방식 적용:
    LLM 신뢰도 -> Reward Scale Factor
    """

    # 7개 에이전트 기본 설정
    DEFAULT_AGENTS = [
        "technical_analyst",
        "fundamental_analyst",
        "sentiment_analyst",
        "risk_manager",
        "market_strategist",
        "quantitative_analyst",
        "macro_analyst",
    ]

    def __init__(
        self,
        bot_id: str,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
    ):
        self.bot_id = bot_id
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port

        self.agent_history: Dict[str, List[AgentVote]] = {
            agent: [] for agent in self.DEFAULT_AGENTS
        }
        self.consensus_history: List[ConsensusResult] = []

        self._callback: Optional[Callable] = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def register_callback(self, callback: Callable[[ConsensusResult], None]):
        """합의 결과 콜백 등록"""
        self._callback = callback

    def submit_vote(self, vote: AgentVote) -> None:
        """에이전트 투표 제출"""
        if vote.agent_name not in self.agent_history:
            self.agent_history[vote.agent_name] = []

        self.agent_history[vote.agent_name].append(vote)

        # 최근 100개 유지
        if len(self.agent_history[vote.agent_name]) > 100:
            self.agent_history[vote.agent_name] = self.agent_history[vote.agent_name][-100:]

        self.logger.debug(f"Vote from {vote.agent_name}: {vote.decision} ({vote.confidence:.2f})")

    def calculate_consensus(self) -> Optional[ConsensusResult]:
        """
        7개 에이전트 투표로 합의 계산

        Returns:
            ConsensusResult or None: 투표가 충분하지 않으면 None
        """
        # 현재 라운드 투표 수집
        current_votes: Dict[str, AgentVote] = {}

        for agent_name, votes in self.agent_history.items():
            if votes:
                # 가장 최근 투표 사용
                current_votes[agent_name] = votes[-1]

        if len(current_votes) < 4:  # 최소 4개 에이전트 필요
            return None

        # 다수결 계산
        decisions = [v.decision for v in current_votes.values()]
        decision_counts = Counter(decisions)
        majority_decision = decision_counts.most_common(1)[0][0]

        # 신뢰도 계산
        total_confidence = sum(v.confidence for v in current_votes.values())
        avg_confidence = total_confidence / len(current_votes)

        # 합의율 계산
        majority_count = decision_counts[majority_decision]
        agreement_ratio = majority_count / len(current_votes)

        # 반대 에이전트
        dissent_agents = [
            name for name, vote in current_votes.items()
            if vote.decision != majority_decision
        ]

        # 강도 결정
        if agreement_ratio >= 0.85 and avg_confidence >= 0.7:
            strength = "strong"
        elif agreement_ratio >= 0.7 and avg_confidence >= 0.5:
            strength = "moderate"
        elif agreement_ratio >= 0.5:
            strength = "weak"
        else:
            strength = "neutral"

        result = ConsensusResult(
            signal=majority_decision,
            confidence=round(avg_confidence, 4),
            strength=strength,
            votes=current_votes,
            agreement_ratio=round(agreement_ratio, 4),
            dissent_agents=dissent_agents,
        )

        self.consensus_history.append(result)
        if len(self.consensus_history) > 1000:
            self.consensus_history = self.consensus_history[-1000:]

        # 콜백 호출
        if self._callback:
            self._callback(result)

        self.logger.info(
            f"Consensus: {result.signal} ({result.strength}) "
            f"conf={result.confidence:.2f} agreement={result.agreement_ratio:.2%}"
        )

        return result

    def get_agent_performance(self, agent_name: str) -> Dict[str, Any]:
        """개별 에이전트 성과 분석"""
        votes = self.agent_history.get(agent_name, [])

        if not votes:
            return {"agent": agent_name, "votes": 0}

        decisions = Counter(v.decision for v in votes)
        avg_confidence = sum(v.confidence for v in votes) / len(votes)

        return {
            "agent": agent_name,
            "total_votes": len(votes),
            "decisions": dict(decisions),
            "avg_confidence": round(avg_confidence, 4),
            "latest_vote": votes[-1].decision if votes else None,
        }

    def get_all_agents_performance(self) -> Dict[str, Any]:
        """모든 에이전트 성과"""
        return {
            agent: self.get_agent_performance(agent)
            for agent in self.DEFAULT_AGENTS
        }

    def get_consensus_accuracy(self, actual_outcome: str) -> float:
        """
        합의 정확도 계산

        Args:
            actual_outcome: 실제 결과 (buy/sell/hold의 결과)

        Returns:
            float: 정확도 (0.0 ~ 1.0)
        """
        if not self.consensus_history:
            return 0.0

        # 최근 50개 합의만 검사
        recent = self.consensus_history[-50:]

        correct = sum(
            1 for c in recent
            if (c.signal == "buy" and actual_outcome == "up") or
               (c.signal == "sell" and actual_outcome == "down") or
               (c.signal == "hold" and actual_outcome == "sideways")
        )

        return correct / len(recent) if recent else 0.0

    async def publish_to_reward_system(self, result: ConsensusResult) -> None:
        """Reward System에 결과 발행"""
        try:
            import aiomqtt

            async with aiomqtt.Client(
                hostname=self.mqtt_host,
                port=self.mqtt_port,
            ) as client:
                await client.publish(
                    f"oz/a2m/bots/{self.bot_id}/signal",
                    json.dumps({
                        "timestamp": datetime.utcnow().isoformat(),
                        "signal": result.signal,
                        "llm_confidence": result.confidence,
                        "signal_strength": result.strength,
                        "agreement_ratio": result.agreement_ratio,
                        "votes": {
                            name: {
                                "decision": v.decision,
                                "confidence": v.confidence,
                            }
                            for name, v in result.votes.items()
                        },
                        "reward_multiplier": result.to_reward_multiplier(),
                    }),
                    qos=1,
                )

                self.logger.debug(f"Published consensus to Reward System")

        except Exception as e:
            self.logger.error(f"Failed to publish: {e}")

    def to_dict(self) -> Dict[str, Any]:
        """상태 직렬화"""
        return {
            "bot_id": self.bot_id,
            "agents": self.get_all_agents_performance(),
            "latest_consensus": self.consensus_history[-1].__dict__ if self.consensus_history else None,
            "total_consensus_count": len(self.consensus_history),
        }


class MultiBotTradingAgentsBridge:
    """다중 봇 TradingAgents 관리"""

    def __init__(self):
        self.bridges: Dict[str, TradingAgentsRewardBridge] = {}

    def get_bridge(self, bot_id: str) -> TradingAgentsRewardBridge:
        """봇별 브릿지 조회 또는 생성"""
        if bot_id not in self.bridges:
            self.bridges[bot_id] = TradingAgentsRewardBridge(bot_id)
        return self.bridges[bot_id]

    def submit_vote(self, bot_id: str, vote: AgentVote) -> None:
        """특정 봇에 투표 제출"""
        bridge = self.get_bridge(bot_id)
        bridge.submit_vote(vote)

    def calculate_all_consensus(self) -> Dict[str, Optional[ConsensusResult]]:
        """모든 봇 합의 계산"""
        return {
            bot_id: bridge.calculate_consensus()
            for bot_id, bridge in self.bridges.items()
        }

    def get_overall_stats(self) -> Dict[str, Any]:
        """전체 통계"""
        return {
            "total_bridges": len(self.bridges),
            "bots": {
                bot_id: bridge.to_dict()
                for bot_id, bridge in self.bridges.items()
            }
        }


# 편의 함수
def create_agent_vote(
    agent_name: str,
    decision: str,
    confidence: float,
    reasoning: Optional[str] = None,
) -> AgentVote:
    """AgentVote 편의 생성"""
    return AgentVote(
        agent_name=agent_name,
        decision=decision,
        confidence=confidence,
        reasoning=reasoning,
    )


def calculate_reward_multiplier(
    confidence: float,
    agreement_ratio: float,
    strength: str,
) -> float:
    """신뢰도로부터 보상 배율 계산"""
    base = 0.5 + confidence
    strength_bonus = {
        'strong': 0.2,
        'moderate': 0.1,
        'weak': 0.0,
        'neutral': -0.1,
    }.get(strength, 0.0)
    agreement_bonus = (agreement_ratio - 0.5) * 0.2

    return max(0.5, min(1.5, base + strength_bonus + agreement_bonus))

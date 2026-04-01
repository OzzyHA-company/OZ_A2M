"""
Episode Memory - AlphaLoop 방식 자기개선 루프

매주 실행:
1. 지난 주 모든 봇의 "에피소드 메모리" 저장
   (어떤 시장 상황에서, 어떤 행동을, 어떤 결과)

2. "잘 된 에피소드" vs "못 된 에피소드" 자동 레이블링
   기준: reward_score 상위 30% = 성공, 하위 30% = 실패

3. 성공 에피소드 → 프롬프트/파라미터 강화 (preference로 저장)
   실패 에피소드 → 회피 패턴으로 학습

4. TradingAgents의 LLM에 이 preference 주입
   (LoRA 또는 시스템 프롬프트 업데이트)

결과: 매주 봇이 자동으로 더 똑똑해짐
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import numpy as np

logger = logging.getLogger(__name__)


class EpisodeOutcome(Enum):
    """에피소드 결과 분류"""
    SUCCESS = "success"      # 상위 30%
    NEUTRAL = "neutral"      # 중위 40%
    FAILURE = "failure"      # 하위 30%


@dataclass
class MarketContext:
    """시장 상황 컨텍스트"""
    timestamp: datetime
    symbol: str
    timeframe: str

    # 기술적 지표
    price: float
    volume_24h: float
    volatility_atr: float
    rsi: Optional[float] = None
    macd: Optional[float] = None

    # 시장 상태
    trend: str = "sideways"  # uptrend, downtrend, sideways
    market_regime: str = "normal"  # bull, bear, crab, volatile

    # 외부 요인
    funding_rate: Optional[float] = None
    fear_greed_index: Optional[int] = None
    news_sentiment: Optional[float] = None  # -1.0 ~ 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp.isoformat(),
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'price': self.price,
            'volume_24h': self.volume_24h,
            'volatility_atr': self.volatility_atr,
            'rsi': self.rsi,
            'macd': self.macd,
            'trend': self.trend,
            'market_regime': self.market_regime,
            'funding_rate': self.funding_rate,
            'fear_greed_index': self.fear_greed_index,
            'news_sentiment': self.news_sentiment,
        }


@dataclass
class BotAction:
    """봇 행동 기록"""
    action_type: str  # enter_long, enter_short, exit, hold, modify
    position_size: float
    leverage: float = 1.0
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: float = 0.5  # 봇의 결신신

    def to_dict(self) -> Dict[str, Any]:
        return {
            'action_type': self.action_type,
            'position_size': self.position_size,
            'leverage': self.leverage,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'confidence': self.confidence,
        }


@dataclass
class EpisodeResult:
    """에피소드 결과"""
    pnl: float
    pnl_pct: float
    holding_period_minutes: float
    max_favorable_excursion: float  # 최대 유리 변동
    max_adverse_excursion: float    # 최대 불리 변동
    sl_hit: bool = False
    tp_hit: bool = False

    # 보상 점수
    reward_score: float = 0.0
    sharpe_contribution: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'holding_period_minutes': self.holding_period_minutes,
            'max_favorable_excursion': self.max_favorable_excursion,
            'max_adverse_excursion': self.max_adverse_excursion,
            'sl_hit': self.sl_hit,
            'tp_hit': self.tp_hit,
            'reward_score': self.reward_score,
            'sharpe_contribution': self.sharpe_contribution,
        }


@dataclass
class Episode:
    """
    에피소드 (경험 단위)

    시장 상황 + 봇 행동 + 결과 = 학습 데이터
    """
    episode_id: str
    bot_id: str
    bot_name: str

    context: MarketContext
    action: BotAction
    result: EpisodeResult

    created_at: datetime = field(default_factory=datetime.utcnow)
    outcome: EpisodeOutcome = EpisodeOutcome.NEUTRAL

    # 학습용 메타데이터
    embedding: Optional[List[float]] = None  # 벡터 임베딩 (유사도 검색용)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'episode_id': self.episode_id,
            'bot_id': self.bot_id,
            'bot_name': self.bot_name,
            'context': self.context.to_dict(),
            'action': self.action.to_dict(),
            'result': self.result.to_dict(),
            'created_at': self.created_at.isoformat(),
            'outcome': self.outcome.value,
            'tags': self.tags,
        }


@dataclass
class PreferencePair:
    """선호도 쌍 (RLHF 학습용)"""
    preferred_episode: Episode   # 성공 에피소드
    rejected_episode: Episode    # 실패 에피소드

    # 선호도 강도
    preference_strength: float = 1.0  # 0.0 ~ 2.0
    context_similarity: float = 0.0   # 두 에피소드의 컨텍스트 유사도

    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'preferred': self.preferred_episode.to_dict(),
            'rejected': self.rejected_episode.to_dict(),
            'preference_strength': self.preference_strength,
            'context_similarity': self.context_similarity,
            'created_at': self.created_at.isoformat(),
        }


class EpisodeMemory:
    """
    에피소드 메모리 관리자

    AlphaLoop 방식 자기개선 루프 핵심
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        max_episodes_per_bot: int = 1000,
    ):
        self.storage_path = storage_path or "data/episode_memory.json"
        self.max_episodes_per_bot = max_episodes_per_bot

        self.episodes: Dict[str, List[Episode]] = {}  # bot_id -> episodes
        self.preferences: List[PreferencePair] = []

        self.logger = logging.getLogger(self.__class__.__name__)

    def add_episode(self, episode: Episode) -> None:
        """에피소드 추가"""
        bot_id = episode.bot_id

        if bot_id not in self.episodes:
            self.episodes[bot_id] = []

        self.episodes[bot_id].append(episode)

        # 최대 개수 유지
        if len(self.episodes[bot_id]) > self.max_episodes_per_bot:
            self.episodes[bot_id] = self.episodes[bot_id][-self.max_episodes_per_bot:]

        self.logger.debug(f"Added episode for {bot_id}, total: {len(self.episodes[bot_id])}")

    def create_episode(
        self,
        bot_id: str,
        bot_name: str,
        context: MarketContext,
        action: BotAction,
        result: EpisodeResult,
    ) -> Episode:
        """새 에피소드 생성 및 저장"""
        import uuid

        episode = Episode(
            episode_id=str(uuid.uuid4())[:8],
            bot_id=bot_id,
            bot_name=bot_name,
            context=context,
            action=action,
            result=result,
        )

        self.add_episode(episode)
        return episode

    def label_episodes(self, bot_id: str) -> Dict[str, int]:
        """
        에피소드 자동 레이블링

        상위 30% = SUCCESS
        하위 30% = FAILURE
        중위 40% = NEUTRAL
        """
        if bot_id not in self.episodes or not self.episodes[bot_id]:
            return {'success': 0, 'neutral': 0, 'failure': 0}

        episodes = self.episodes[bot_id]

        # 점수 기준 정렬
        episodes.sort(key=lambda e: e.result.reward_score, reverse=True)

        n = len(episodes)
        top_30 = int(n * 0.3)
        bottom_30 = int(n * 0.3)

        counts = {'success': 0, 'neutral': 0, 'failure': 0}

        for i, episode in enumerate(episodes):
            if i < top_30:
                episode.outcome = EpisodeOutcome.SUCCESS
                counts['success'] += 1
            elif i >= n - bottom_30:
                episode.outcome = EpisodeOutcome.FAILURE
                counts['failure'] += 1
            else:
                episode.outcome = EpisodeOutcome.NEUTRAL
                counts['neutral'] += 1

        self.logger.info(f"Labeled {n} episodes for {bot_id}: {counts}")
        return counts

    def generate_preferences(self, bot_id: str) -> List[PreferencePair]:
        """
        선호도 쌍 생성

        비슷한 컨텍스트에서 성공 vs 실패 비교
        """
        if bot_id not in self.episodes:
            return []

        # 레이블링
        self.label_episodes(bot_id)

        episodes = self.episodes[bot_id]
        success_episodes = [e for e in episodes if e.outcome == EpisodeOutcome.SUCCESS]
        failure_episodes = [e for e in episodes if e.outcome == EpisodeOutcome.FAILURE]

        if not success_episodes or not failure_episodes:
            return []

        preferences = []

        # 성공/실패 쌍 생성
        for success in success_episodes[:50]:  # 상위 50개
            # 가장 유사한 실패 에피소드 찾기
            best_match = None
            best_similarity = -1

            for failure in failure_episodes:
                similarity = self._calculate_context_similarity(success.context, failure.context)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = failure

            if best_match and best_similarity > 0.5:  # 50% 이상 유사도
                preference = PreferencePair(
                    preferred_episode=success,
                    rejected_episode=best_match,
                    context_similarity=best_similarity,
                    preference_strength=1.0 + (success.result.reward_score - best_match.result.reward_score) / 100,
                )
                preferences.append(preference)

        self.preferences.extend(preferences)
        self.logger.info(f"Generated {len(preferences)} preferences for {bot_id}")

        return preferences

    def _calculate_context_similarity(
        self,
        ctx1: MarketContext,
        ctx2: MarketContext
    ) -> float:
        """컨텍스트 유사도 계산"""
        # 같은 심볼/타임프레임
        if ctx1.symbol != ctx2.symbol or ctx1.timeframe != ctx2.timeframe:
            return 0.0

        similarities = []

        # 가격 유사도 (±5% 범위)
        price_diff = abs(ctx1.price - ctx2.price) / ctx1.price
        similarities.append(max(0, 1 - price_diff / 0.05))

        # 변동성 유사도
        vol_diff = abs(ctx1.volatility_atr - ctx2.volatility_atr) / max(ctx1.volatility_atr, 1e-10)
        similarities.append(max(0, 1 - vol_diff))

        # RSI 유사도
        if ctx1.rsi and ctx2.rsi:
            rsi_diff = abs(ctx1.rsi - ctx2.rsi) / 100
            similarities.append(1 - rsi_diff)

        # 트렌드 동일성
        similarities.append(1.0 if ctx1.trend == ctx2.trend else 0.0)

        # 시장 레짐 동일성
        similarities.append(1.0 if ctx1.market_regime == ctx2.market_regime else 0.0)

        return np.mean(similarities)

    def get_success_patterns(self, bot_id: str, top_n: int = 10) -> List[Dict[str, Any]]:
        """성공 패턴 추출"""
        if bot_id not in self.episodes:
            return []

        success_episodes = [
            e for e in self.episodes[bot_id]
            if e.outcome == EpisodeOutcome.SUCCESS
        ]

        if not success_episodes:
            return []

        # 컨텍스트 특징 집계
        patterns = {}

        for ep in success_episodes:
            key = f"{ep.context.trend}_{ep.context.market_regime}_{ep.action.action_type}"
            if key not in patterns:
                patterns[key] = {
                    'count': 0,
                    'avg_pnl': 0,
                    'avg_score': 0,
                    'examples': [],
                }
            patterns[key]['count'] += 1
            patterns[key]['avg_pnl'] += ep.result.pnl
            patterns[key]['avg_score'] += ep.result.reward_score
            patterns[key]['examples'].append(ep.to_dict())

        # 평균 계산 및 정렬
        for key in patterns:
            count = patterns[key]['count']
            patterns[key]['avg_pnl'] /= count
            patterns[key]['avg_score'] /= count

        # 상위 패턴 반환
        sorted_patterns = sorted(
            patterns.items(),
            key=lambda x: x[1]['avg_score'],
            reverse=True
        )

        return [
            {
                'pattern': key,
                **data,
                'examples': data['examples'][:3],  # 예시 3개만
            }
            for key, data in sorted_patterns[:top_n]
        ]

    def get_failure_patterns(self, bot_id: str, top_n: int = 10) -> List[Dict[str, Any]]:
        """실패 패턴 추출 (회피 학습용)"""
        if bot_id not in self.episodes:
            return []

        failure_episodes = [
            e for e in self.episodes[bot_id]
            if e.outcome == EpisodeOutcome.FAILURE
        ]

        if not failure_episodes:
            return []

        patterns = {}

        for ep in failure_episodes:
            key = f"{ep.context.trend}_{ep.context.market_regime}_{ep.action.action_type}"
            if key not in patterns:
                patterns[key] = {
                    'count': 0,
                    'avg_loss': 0,
                    'avg_score': 0,
                }
            patterns[key]['count'] += 1
            patterns[key]['avg_loss'] += ep.result.pnl
            patterns[key]['avg_score'] += ep.result.reward_score

        for key in patterns:
            count = patterns[key]['count']
            patterns[key]['avg_loss'] /= count
            patterns[key]['avg_score'] /= count

        sorted_patterns = sorted(
            patterns.items(),
            key=lambda x: x[1]['avg_loss'],  # 손실 큰 순
        )

        return [
            {'pattern': key, **data}
            for key, data in sorted_patterns[:top_n]
        ]

    def generate_improvement_prompt(self, bot_id: str) -> Optional[str]:
        """
        LLM용 개선 프롬프트 생성

        TradingAgents에 주입할 시스템 프롬프트 업데이트용
        """
        success_patterns = self.get_success_patterns(bot_id, 5)
        failure_patterns = self.get_failure_patterns(bot_id, 5)

        if not success_patterns:
            return None

        prompt = f"""# Trading Strategy Improvement Guide for {bot_id}

## Successful Patterns (DO MORE):
"""
        for i, p in enumerate(success_patterns, 1):
            prompt += f"""
{i}. Pattern: {p['pattern']}
   - Success Rate: {p['count']} times
   - Avg PnL: ${p['avg_pnl']:.2f}
   - Avg Score: {p['avg_score']:.2f}
"""

        prompt += """
## Failure Patterns (AVOID):
"""
        for i, p in enumerate(failure_patterns, 1):
            prompt += f"""
{i}. Pattern: {p['pattern']}
   - Failure Count: {p['count']} times
   - Avg Loss: ${p['avg_loss']:.2f}
"""

        prompt += """
## Guidelines:
- Prioritize actions that match successful patterns
- Avoid or reduce position size for failure patterns
- In uncertain conditions, wait for clearer signals
"""

        return prompt

    def weekly_learning_cycle(self) -> Dict[str, Any]:
        """
        주간 학습 사이클 실행

        모든 봇에 대해:
        1. 에피소드 레이블링
        2. 선호도 쌍 생성
        3. 성공/실패 패턴 추출
        4. 개선 프롬프트 생성
        """
        results = {
            'timestamp': datetime.utcnow().isoformat(),
            'bots_processed': 0,
            'total_episodes': 0,
            'preferences_generated': 0,
            'prompts': {},
        }

        for bot_id in self.episodes:
            # 레이블링
            label_counts = self.label_episodes(bot_id)
            results['total_episodes'] += sum(label_counts.values())

            # 선호도 생성
            prefs = self.generate_preferences(bot_id)
            results['preferences_generated'] += len(prefs)

            # 프롬프트 생성
            prompt = self.generate_improvement_prompt(bot_id)
            if prompt:
                results['prompts'][bot_id] = prompt

            results['bots_processed'] += 1

        self.logger.info(
            f"Weekly learning complete: {results['bots_processed']} bots, "
            f"{results['preferences_generated']} preferences"
        )

        return results

    def save(self) -> None:
        """상태 저장"""
        import os
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

        data = {
            'timestamp': datetime.utcnow().isoformat(),
            'episodes': {
                bot_id: [e.to_dict() for e in episodes]
                for bot_id, episodes in self.episodes.items()
            },
            'preferences': [p.to_dict() for p in self.preferences[-1000:]],  # 최근 1000개
        }

        with open(self.storage_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    def load(self) -> None:
        """상태 로드"""
        import os
        if not os.path.exists(self.storage_path):
            return

        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)

            # 에피소드 복원
            for bot_id, episode_list in data.get('episodes', {}).items():
                self.episodes[bot_id] = []
                for ep_data in episode_list:
                    # 간단한 복원 (전체 필드는 생략 가능)
                    pass  # 복잡한 구조는 재생성 권장

            self.logger.info(f"Loaded episode memory (simplified)")

        except Exception as e:
            self.logger.error(f"Failed to load episode memory: {e}")

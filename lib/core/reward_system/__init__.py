"""
OZ_A2M Reward System
수익 극대화형 RPG + FinRL 기반 보상 시스템

Core Components:
- RewardCalculator: FinRL 기반 보상 계산 (Sharpe, Sortino, Calmar)
- RPGSystem: 레벨/등급/HP 게이미피케이션
- BotClassifier: 봇 유형별 최적 보상 함수 선택
- CapitalAllocator: 자본 배분 최적화 (Ensemble Strategy)
- EpisodeMemory: AlphaLoop 방식 자기개선 루프
- BotWrapper: 봇 통합 래퍼/데코레이터
- RewardService: 통합 서비스

References:
- AI4Finance-Foundation/FinRL (14.6k stars)
- AI4Finance-Foundation/FinRL-Trading (2.9k stars)
- TauricResearch/TradingAgents (45.6k stars)
"""

from .reward_calculator import RewardCalculator, RewardType, TradeRecord, RewardResult
from .rpg_system import RPGSystem, BotGrade, BotLevel, BotRPGState, BotHP
from .bot_classifier import BotClassifier, BotType, BotProfile, DEFAULT_BOT_CONFIGS
from .capital_allocator import CapitalAllocator, CapitalAllocation, CapitalStatus
from .episode_memory import EpisodeMemory, Episode, MarketContext, BotAction, EpisodeResult
from .bot_wrapper import (
    RewardSystemClient,
    RewardAwareBot,
    TradingAgentsBridge,
    TradeResult,
    SignalResult,
    reward_aware,
    create_trade_result,
    create_signal_result,
)

__all__ = [
    # Core
    'RewardCalculator',
    'RewardType',
    'TradeRecord',
    'RewardResult',
    # RPG
    'RPGSystem',
    'BotGrade',
    'BotLevel',
    'BotRPGState',
    'BotHP',
    # Classifier
    'BotClassifier',
    'BotType',
    'BotProfile',
    'DEFAULT_BOT_CONFIGS',
    # Capital
    'CapitalAllocator',
    'CapitalAllocation',
    'CapitalStatus',
    # Episode
    'EpisodeMemory',
    'Episode',
    'MarketContext',
    'BotAction',
    'EpisodeResult',
    # Wrapper
    'RewardSystemClient',
    'RewardAwareBot',
    'TradingAgentsBridge',
    'TradeResult',
    'SignalResult',
    'reward_aware',
    'create_trade_result',
    'create_signal_result',
]

__version__ = "1.0.0"

"""
OZ_A2M Reward System
수익 극대화형 RPG + FinRL 기반 보상 시스템

Core Components:
- RewardCalculator: FinRL 기반 보상 계산 (Sharpe, Sortino, Calmar)
- RPGSystem: 레벨/등급/HP 게이미피케이션
- BotClassifier: 봇 유형별 최적 보상 함수 선택
- CapitalAllocator: 자본 배분 최적화 (Ensemble Strategy)

References:
- AI4Finance-Foundation/FinRL (14.6k stars)
- AI4Finance-Foundation/FinRL-Trading (2.9k stars)
- TauricResearch/TradingAgents (45.6k stars)
"""

from .reward_calculator import RewardCalculator, RewardType
from .rpg_system import RPGSystem, BotGrade, BotLevel
from .bot_classifier import BotClassifier, BotType
from .capital_allocator import CapitalAllocator
from .episode_memory import EpisodeMemory, Episode

__all__ = [
    'RewardCalculator',
    'RewardType',
    'RPGSystem',
    'BotGrade',
    'BotLevel',
    'BotClassifier',
    'BotType',
    'CapitalAllocator',
    'EpisodeMemory',
    'Episode',
]

__version__ = "1.0.0"

"""
Bot Classifier - 봇 유형별 최적 보상 함수 선택

OZ_A2M 봇 유형:
1. 안정봇 (Stability Bots)
   - Grid, DCA, Funding Rate
   - Reward: Sortino Ratio (하방 변동성만 페널티)

2. 도파민봇 (Dopamine Bots)
   - Scalper, Pump.fun Sniper, GMGN Copy
   - Reward: Calmar Ratio (연수익/최대낙폭)
   - 특징: 수익 즉시 출금

3. 차익거래봇 (Arbitrage Bots)
   - Triangular Arb, Market Maker, Hyperliquid
   - Reward: (수익-거래비용)/기회비용

4. AI분석봇 (AI Analysis Bots)
   - IBKR Forecast, Polymarket
   - Reward: LLM 예측 정확도 × 기대수익
"""

from enum import Enum, auto
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

from .reward_calculator import RewardType

logger = logging.getLogger(__name__)


class BotType(Enum):
    """봇 유형 분류"""
    STABILITY = "stability"      # 안정봇
    DOPAMINE = "dopamine"        # 도파민봇
    ARBITRAGE = "arbitrage"      # 차익거래봇
    AI_ANALYSIS = "ai_analysis"  # AI 분석봇
    UNKNOWN = "unknown"


@dataclass
class BotProfile:
    """봇 프로필 정보"""
    bot_id: str
    bot_name: str
    bot_type: BotType
    exchange: str
    symbols: List[str]
    timeframes: List[str]
    capital_usd: float
    max_leverage: float = 1.0
    risk_level: str = "medium"  # low, medium, high
    expected_holding_time: str = "medium"  # short, medium, long


class BotClassifier:
    """
    봇 분류기

    봇 이름/ID 기반 자동 분류
    봇 유형별 최적 보상 함수 매핑
    """

    # 봇 이름 패턴으로 유형 분류
    TYPE_PATTERNS = {
        BotType.STABILITY: [
            "grid", "dca", "funding", "accumul",
            "dollar", "cost", "average", "steady"
        ],
        BotType.DOPAMINE: [
            "scalp", "sniper", "pump", "copy", "moon",
            "ape", "degen", "quick", "fast", "flash"
        ],
        BotType.ARBITRAGE: [
            "arb", "triangular", "mm", "market_maker",
            "spread", "basis", "perp", "futures",
            "hyperliquid"
        ],
        BotType.AI_ANALYSIS: [
            "forecast", "predict", "ai_", "ml_", "llm",
            "sentiment", "news", "poly", "market", "intel"
        ],
    }

    # 봇 유형별 기본 설정
    TYPE_CONFIGS = {
        BotType.STABILITY: {
            "reward_type": RewardType.SORTINO,
            "hp_loss_on_loss": -5.0,      # 안정봇은 적은 HP 페널티
            "hp_gain_on_win": 8.0,        # 승리시 더 많은 회복
            "grade_threshold": 50.0,      # 등급 상향 임계값
            "capital_realloc_factor": 0.8,  # 자본 재배분 민감도
        },
        BotType.DOPAMINE: {
            "reward_type": RewardType.CALMAR,
            "hp_loss_on_loss": -10.0,     # 도파민봉은 큰 HP 페널티
            "hp_gain_on_win": 12.0,       # 하지만 승리시 큰 보상
            "grade_threshold": 60.0,      # 등급 상향이 어려움
            "capital_realloc_factor": 1.2,  # 자본 재배분 높은 민감도
        },
        BotType.ARBITRAGE: {
            "reward_type": RewardType.CUSTOM_ARB,
            "hp_loss_on_loss": -8.0,
            "hp_gain_on_win": 6.0,
            "grade_threshold": 55.0,
            "capital_realloc_factor": 1.0,
        },
        BotType.AI_ANALYSIS: {
            "reward_type": RewardType.CUSTOM_AI,
            "hp_loss_on_loss": -6.0,
            "hp_gain_on_win": 7.0,
            "grade_threshold": 52.0,
            "capital_realloc_factor": 0.9,
        },
    }

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._profiles: Dict[str, BotProfile] = {}

    def classify(self, bot_id: str, bot_name: Optional[str] = None) -> BotType:
        """
        봇 이름/ID로 유형 분류

        Args:
            bot_id: 봇 ID
            bot_name: 봇 이름 (선택)

        Returns:
            BotType: 분류된 봇 유형
        """
        search_text = f"{bot_id} {bot_name or ''}".lower()

        for bot_type, patterns in self.TYPE_PATTERNS.items():
            for pattern in patterns:
                if pattern in search_text:
                    return bot_type

        return BotType.UNKNOWN

    def get_reward_type(self, bot_type: BotType) -> RewardType:
        """봇 유형별 최적 보상 함수"""
        config = self.TYPE_CONFIGS.get(bot_type, self.TYPE_CONFIGS[BotType.STABILITY])
        return config["reward_type"]

    def get_hp_config(self, bot_type: BotType) -> Dict[str, float]:
        """봇 유형별 HP 설정"""
        config = self.TYPE_CONFIGS.get(bot_type, self.TYPE_CONFIGS[BotType.STABILITY])
        return {
            "loss_penalty": config["hp_loss_on_loss"],
            "win_bonus": config["hp_gain_on_win"],
        }

    def create_profile(
        self,
        bot_id: str,
        bot_name: str,
        exchange: str,
        symbols: List[str],
        capital_usd: float,
        **kwargs
    ) -> BotProfile:
        """봇 프로필 생성"""
        bot_type = self.classify(bot_id, bot_name)

        profile = BotProfile(
            bot_id=bot_id,
            bot_name=bot_name,
            bot_type=bot_type,
            exchange=exchange,
            symbols=symbols,
            timeframes=kwargs.get("timeframes", ["1h"]),
            capital_usd=capital_usd,
            max_leverage=kwargs.get("max_leverage", 1.0),
            risk_level=kwargs.get("risk_level", "medium"),
            expected_holding_time=kwargs.get("expected_holding_time", "medium"),
        )

        self._profiles[bot_id] = profile
        self.logger.info(f"Created profile for {bot_id}: {bot_type.value}")

        return profile

    def get_profile(self, bot_id: str) -> Optional[BotProfile]:
        """봇 프로필 조회"""
        return self._profiles.get(bot_id)

    def auto_classify_all(
        self,
        bot_configs: List[Dict[str, any]]
    ) -> Dict[str, BotProfile]:
        """
        설정 목록으로 자동 분류

        Args:
            bot_configs: [{bot_id, name, exchange, symbols, capital_usd}, ...]

        Returns:
            Dict[str, BotProfile]: 분류된 프로필
        """
        profiles = {}

        for config in bot_configs:
            profile = self.create_profile(
                bot_id=config["bot_id"],
                bot_name=config.get("name", config["bot_id"]),
                exchange=config.get("exchange", "unknown"),
                symbols=config.get("symbols", []),
                capital_usd=config.get("capital_usd", 0),
                timeframes=config.get("timeframes", ["1h"]),
                max_leverage=config.get("max_leverage", 1.0),
                risk_level=config.get("risk_level", "medium"),
            )
            profiles[config["bot_id"]] = profile

        return profiles

    def get_type_summary(self) -> Dict[str, List[str]]:
        """유형별 봇 목록 요약"""
        summary = {bt.value: [] for bt in BotType}

        for bot_id, profile in self._profiles.items():
            summary[profile.bot_type.value].append(bot_id)

        return summary


# OZ_A2M 11봇 기본 설정
DEFAULT_BOT_CONFIGS = [
    {
        "bot_id": "grid_bot",
        "name": "Binance Grid",
        "exchange": "binance",
        "symbols": ["BTC/USDT"],
        "capital_usd": 11.0,
        "type": BotType.STABILITY,
    },
    {
        "bot_id": "dca_bot",
        "name": "Binance DCA",
        "exchange": "binance",
        "symbols": ["BTC/USDT"],
        "capital_usd": 14.0,
        "type": BotType.STABILITY,
    },
    {
        "bot_id": "triarb_bot",
        "name": "Triangular Arb",
        "exchange": "binance",
        "symbols": ["BTC/ETH/BNB"],
        "capital_usd": 10.35,
        "type": BotType.ARBITRAGE,
    },
    {
        "bot_id": "funding_bot",
        "name": "Funding Rate",
        "exchange": "binance+bybit",
        "symbols": ["BTC/USDT", "ETH/USDT"],
        "capital_usd": 8.0,
        "type": BotType.STABILITY,
    },
    {
        "bot_id": "scalper_bot",
        "name": "Bybit Scalper",
        "exchange": "bybit",
        "symbols": ["SOL/USDT"],
        "capital_usd": 7.94,
        "type": BotType.DOPAMINE,
    },
    {
        "bot_id": "hyperliquid_bot",
        "name": "Hyperliquid MM",
        "exchange": "hyperliquid",
        "symbols": ["SOL-PERP"],
        "capital_usd": 6.19,
        "type": BotType.ARBITRAGE,
    },
    {
        "bot_id": "ibkr_bot",
        "name": "IBKR Forecast",
        "exchange": "interactive_brokers",
        "symbols": ["AAPL", "MSFT"],
        "capital_usd": 10.0,
        "type": BotType.AI_ANALYSIS,
    },
    {
        "bot_id": "polymarket_bot",
        "name": "Polymarket AI",
        "exchange": "polymarket",
        "symbols": ["MULTI"],
        "capital_usd": 19.84,
        "type": BotType.AI_ANALYSIS,
    },
    {
        "bot_id": "pump_sniper",
        "name": "Pump.fun Sniper",
        "exchange": "solana",
        "symbols": ["NEW_TOKENS"],
        "capital_usd": 6.19,
        "type": BotType.DOPAMINE,
    },
    {
        "bot_id": "gmgn_copy",
        "name": "GMGN Copy",
        "exchange": "solana",
        "symbols": ["SMART_MONEY"],
        "capital_usd": 6.18,
        "type": BotType.DOPAMINE,
    },
]

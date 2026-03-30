"""
Test: Hyperliquid MM Bot + IBKR Forecast Trader Bot
STEP 12: OZ_A2M 완결판
"""

import pytest
import asyncio
from unittest.mock import Mock
from datetime import datetime

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from department_7.src.bot.hyperliquid_bot import (
    HyperliquidMarketMakerBot, HLPosition, HLTrade, HyperliquidStatus
)
from department_7.src.bot.ibkr_forecast_bot import (
    IBKRForecastTraderBot, IBKRPosition, IBKRTrade, IBKRStatus
)
from department_7.src.bot.unified_bot_manager import (
    UnifiedBotManager, BotConfig, BotType, get_bot_manager, reset_bot_manager
)


class TestHyperliquidBot:
    """Hyperliquid MM Bot 테스트"""

    def test_hyperliquid_bot_initialization(self):
        """Hyperliquid 봇 초기화 테스트"""
        bot = HyperliquidMarketMakerBot(
            bot_id="hyperliquid_test_001",
            symbol="SOL-PERP",
            capital=20.0,
            base_spread_bps=10.0,
            mock_mode=True,
            telegram_alerts=False
        )

        assert bot.bot_id == "hyperliquid_test_001"
        assert bot.symbol == "SOL-PERP"
        assert bot.capital == 20.0
        assert bot.base_spread_bps == 10.0
        assert bot.mock_mode == True
        assert bot.status == HyperliquidStatus.IDLE

    def test_hyperliquid_mock_mode(self):
        """Mock 모드 테스트"""
        bot = HyperliquidMarketMakerBot(
            bot_id="hyperliquid_mock",
            capital=20.0,
            mock_mode=True,
            telegram_alerts=False
        )

        assert bot.mock_mode == True
        assert bot._mock_price == 150.0
        assert bot._mock_balance["USDC"] == 20.0

    def test_hyperliquid_status(self):
        """상태 조회 테스트"""
        bot = HyperliquidMarketMakerBot(
            bot_id="hyperliquid_test",
            capital=20.0,
            mock_mode=True,
            telegram_alerts=False
        )

        status = bot.get_status()

        assert status["bot_id"] == "hyperliquid_test"
        assert status["bot_type"] == "hyperliquid_mm"
        assert status["capital"] == 20.0
        assert status["mock_mode"] == True


class TestIBKRForecastBot:
    """IBKR Forecast Bot 테스트"""

    def test_ibkr_bot_initialization(self):
        """IBKR 봇 초기화 테스트"""
        bot = IBKRForecastTraderBot(
            bot_id="ibkr_test_001",
            symbols=["AAPL", "MSFT"],
            capital=10.0,
            forecast_threshold=0.7,
            mock_mode=True,
            telegram_alerts=False
        )

        assert bot.bot_id == "ibkr_test_001"
        assert bot.symbols == ["AAPL", "MSFT"]
        assert bot.capital == 10.0
        assert bot.forecast_threshold == 0.7
        assert bot.mock_mode == True
        assert bot.status == IBKRStatus.IDLE

    def test_ibkr_mock_data(self):
        """Mock 데이터 테스트"""
        bot = IBKRForecastTraderBot(
            symbols=["AAPL", "MSFT"],
            capital=10.0,
            mock_mode=True,
            telegram_alerts=False
        )

        assert "AAPL" in bot.market_data
        assert "MSFT" in bot.market_data
        assert "price" in bot.market_data["AAPL"]

    def test_ibkr_position_creation(self):
        """IBKR 포지션 생성 테스트"""
        position = IBKRPosition(
            symbol="AAPL",
            side="long",
            quantity=10,
            avg_cost=150.0,
            unrealized_pnl=0.0
        )

        assert position.symbol == "AAPL"
        assert position.quantity == 10
        assert position.avg_cost == 150.0

    def test_ibkr_status(self):
        """상태 조회 테스트"""
        bot = IBKRForecastTraderBot(
            bot_id="ibkr_test",
            capital=10.0,
            mock_mode=True,
            telegram_alerts=False
        )

        status = bot.get_status()

        assert status["bot_id"] == "ibkr_test"
        assert status["bot_type"] == "ibkr_forecast"
        assert status["capital"] == 10.0
        assert status["mock_mode"] == True


class TestUnifiedBotManagerRegistration:
    """UnifiedBotManager 등록 테스트"""

    def setup_method(self):
        """각 테스트 전 실행"""
        reset_bot_manager()

    def test_register_hyperliquid_bot(self):
        """Hyperliquid 봇 등록 테스트"""
        manager = get_bot_manager()

        config = BotConfig(
            bot_id="hyperliquid_mm_001",
            bot_type=BotType.MARKET_MAKER,
            exchange="hyperliquid",
            symbol="SOL-PERP",
            capital=20.0,
            sandbox=False
        )

        mock_bot = Mock()
        result = manager.register_bot(config, mock_bot)

        assert result == True
        assert "hyperliquid_mm_001" in manager._bots

    def test_register_ibkr_bot(self):
        """IBKR 봇 등록 테스트"""
        manager = get_bot_manager()

        config = BotConfig(
            bot_id="ibkr_forecast_001",
            bot_type=BotType.FORECAST,
            exchange="ibkr",
            symbol="AAPL,MSFT,GOOGL",
            capital=10.0,
            sandbox=False
        )

        mock_bot = Mock()
        result = manager.register_bot(config, mock_bot)

        assert result == True
        assert "ibkr_forecast_001" in manager._bots


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

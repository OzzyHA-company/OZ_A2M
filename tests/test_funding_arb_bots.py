"""
Test: Funding Rate Bot + Triangular Arbitrage Bot
STEP 11: OZ_A2M 완결판

테스트 항목:
- FundingRateBot 초기화
- TriangularArbBot 초기화
- UnifiedBotManager 등록
"""

import pytest
import asyncio
import os
from unittest.mock import Mock, patch
from datetime import datetime

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from department_7.src.bot.funding_rate_bot import (
    FundingRateBot, FundingRate, FundingTrade, FundingStatus
)
from department_7.src.bot.triangular_arb_bot import (
    TriangularArbBot, ArbOpportunity, ArbTrade, ArbStatus
)
from department_7.src.bot.unified_bot_manager import (
    UnifiedBotManager, BotConfig, BotType, get_bot_manager, reset_bot_manager
)


class TestFundingRateBot:
    """Funding Rate Bot 테스트"""

    def test_funding_bot_initialization(self):
        """펀딩 봇 초기화 테스트"""
        bot = FundingRateBot(
            bot_id="funding_test_001",
            capital=20.0,
            min_funding_rate=0.0001,
            funding_interval_hours=8,
            sandbox=True,
            telegram_alerts=False
        )

        assert bot.bot_id == "funding_test_001"
        assert bot.capital == 20.0
        assert bot.min_funding_rate == 0.0001
        assert bot.funding_interval_hours == 8
        assert bot.status == FundingStatus.IDLE

    def test_funding_rate_creation(self):
        """펀딩 레이트 객체 생성 테스트"""
        rate = FundingRate(
            exchange="binance",
            symbol="BTC/USDT",
            funding_rate=0.0001,
            funding_time=datetime.utcnow(),
            next_funding_time=datetime.utcnow()
        )

        assert rate.exchange == "binance"
        assert rate.symbol == "BTC/USDT"
        assert rate.funding_rate == 0.0001

    def test_funding_opportunity_analysis(self):
        """펀딩 기회 분석 테스트"""
        bot = FundingRateBot(
            capital=20.0,
            min_funding_rate=0.0001,
            sandbox=True,
            telegram_alerts=False
        )

        # Mock funding rates
        bot.funding_rates = {
            "binance:BTC/USDT": FundingRate(
                exchange="binance",
                symbol="BTC/USDT",
                funding_rate=0.0002,
                funding_time=datetime.utcnow(),
                next_funding_time=datetime.utcnow()
            )
        }

        opportunities = bot._analyze_opportunities()

        assert len(opportunities) == 1
        assert opportunities[0]["symbol"] == "BTC/USDT"
        assert opportunities[0]["funding_rate"] == 0.0002

    def test_funding_status(self):
        """펀딩 봇 상태 조회 테스트"""
        bot = FundingRateBot(
            bot_id="funding_test",
            capital=20.0,
            sandbox=True,
            telegram_alerts=False
        )

        status = bot.get_status()

        assert status["bot_id"] == "funding_test"
        assert status["bot_type"] == "funding_rate"
        assert status["capital"] == 20.0


class TestTriangularArbBot:
    """Triangular Arbitrage Bot 테스트"""

    def test_arb_bot_initialization(self):
        """아비트라지 봇 초기화 테스트"""
        bot = TriangularArbBot(
            bot_id="triarb_test_001",
            exchange_id="binance",
            capital=20.0,
            min_profit_pct=0.001,
            base_currency="BTC",
            arb_path=["ETH", "BNB"],
            sandbox=True,
            telegram_alerts=False
        )

        assert bot.bot_id == "triarb_test_001"
        assert bot.exchange_id == "binance"
        assert bot.capital == 20.0
        assert bot.min_profit_pct == 0.001
        assert bot.base_currency == "BTC"
        assert bot.arb_path == ["ETH", "BNB"]
        assert bot.status == ArbStatus.IDLE

    def test_arb_path_building(self):
        """아비트라지 경로 생성 테스트"""
        bot = TriangularArbBot(
            base_currency="BTC",
            arb_path=["ETH", "BNB"],
            capital=20.0,
            sandbox=True,
            telegram_alerts=False
        )

        assert bot.full_path == ["BTC", "ETH", "BNB", "BTC"]
        assert bot.symbols == ["BTC/ETH", "ETH/BNB", "BNB/BTC"]

    def test_arb_opportunity_creation(self):
        """아비트라지 기회 생성 테스트"""
        opportunity = ArbOpportunity(
            path=["BTC", "ETH", "BNB", "BTC"],
            symbols=["BTC/ETH", "ETH/BNB", "BNB/BTC"],
            profit_pct=0.002,
            amount=20.0,
            timestamp=datetime.utcnow()
        )

        assert opportunity.profit_pct == 0.002
        assert opportunity.path == ["BTC", "ETH", "BNB", "BTC"]

    def test_arbitrage_calculation(self):
        """아비트라지 수익률 계산 테스트"""
        bot = TriangularArbBot(
            base_currency="BTC",
            arb_path=["ETH", "BNB"],
            capital=20.0,
            sandbox=True,
            telegram_alerts=False
        )

        # Mock tickers
        # BTC -> ETH: 1 BTC = 15 ETH (ETH/BTC = 15)
        # ETH -> BNB: 1 ETH = 5 BNB (BNB/ETH = 5)
        # BNB -> BTC: 1 BNB = 0.01333 BTC (BTC/BNB = 0.01333)
        bot.tickers = {
            "BTC/ETH": {"ask": 15.0},
            "ETH/BNB": {"ask": 5.0},
            "BNB/BTC": {"ask": 0.01333}
        }

        opportunity = bot._analyze_arbitrage()

        # 1 * 15 * 5 * 0.01333 = 0.99975 (약 0.025% 손실)
        assert opportunity is None  # 수수료 고려 시 손실

    def test_arb_status(self):
        """아비트라지 봇 상태 조회 테스트"""
        bot = TriangularArbBot(
            bot_id="triarb_test",
            capital=20.0,
            sandbox=True,
            telegram_alerts=False
        )

        status = bot.get_status()

        assert status["bot_id"] == "triarb_test"
        assert status["bot_type"] == "triangular_arb"
        assert status["capital"] == 20.0


class TestUnifiedBotManagerRegistration:
    """UnifiedBotManager 등록 테스트"""

    def setup_method(self):
        """각 테스트 전 실행"""
        reset_bot_manager()

    def test_register_funding_bot(self):
        """펀딩 봇 등록 테스트"""
        manager = get_bot_manager()

        config = BotConfig(
            bot_id="funding_binance_bybit_001",
            bot_type=BotType.FUNDING_RATE,
            exchange="binance",
            symbol="BTC/USDT",
            capital=20.0,
            sandbox=False
        )

        mock_bot = Mock()
        result = manager.register_bot(config, mock_bot)

        assert result == True
        assert "funding_binance_bybit_001" in manager._bots
        assert manager._bot_infos["funding_binance_bybit_001"].bot_type == BotType.FUNDING_RATE

    def test_register_arb_bot(self):
        """아비트라지 봇 등록 테스트"""
        manager = get_bot_manager()

        config = BotConfig(
            bot_id="triarb_binance_001",
            bot_type=BotType.TRIANGULAR_ARB,
            exchange="binance",
            symbol="BTC/ETH/BNB",
            capital=20.0,
            sandbox=False
        )

        mock_bot = Mock()
        result = manager.register_bot(config, mock_bot)

        assert result == True
        assert "triarb_binance_001" in manager._bots
        assert manager._bot_infos["triarb_binance_001"].bot_type == BotType.TRIANGULAR_ARB


class TestEnvironmentVariables:
    """환경변수 테스트"""

    def test_api_keys_configured(self):
        """API 키 설정 여부 테스트"""
        keys_to_check = [
            "BINANCE_API_KEY",
            "BINANCE_API_SECRET",
            "BYBIT_API_KEY",
            "BYBIT_API_SECRET",
        ]

        missing = [k for k in keys_to_check if not os.environ.get(k)]
        print(f"\nMissing API keys: {missing}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

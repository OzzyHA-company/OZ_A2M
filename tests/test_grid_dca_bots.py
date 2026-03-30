"""
Test: Binance Grid Bot + DCA Bot
STEP 10: OZ_A2M 완결판

테스트 항목:
- BinanceGridBot 초기화 및 그리드 계산
- BinanceDCABot 초기화 및 DCA 로직
- UnifiedBotManager 등록
"""

import pytest
import asyncio
import os
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from department_7.src.bot.grid_bot import (
    BinanceGridBot, GridLevel, GridTrade, GridStatus
)
from department_7.src.bot.dca_bot import (
    BinanceDCABot, DCAPosition, DCATrade, DCAStatus
)
from department_7.src.bot.unified_bot_manager import (
    UnifiedBotManager, BotConfig, BotType, get_bot_manager, reset_bot_manager
)


class TestBinanceGridBot:
    """Binance Grid Bot 테스트"""

    def test_grid_bot_initialization(self):
        """그리드봇 초기화 테스트"""
        bot = BinanceGridBot(
            bot_id="grid_test_001",
            symbol="BTC/USDT",
            exchange_id="binance",
            capital=11.0,
            grid_count=20,
            grid_spacing_pct=0.005,
            sandbox=True,
            telegram_alerts=False
        )

        assert bot.bot_id == "grid_test_001"
        assert bot.symbol == "BTC/USDT"
        assert bot.capital == 11.0
        assert bot.grid_count == 20
        assert bot.grid_spacing_pct == 0.005
        assert bot.status == GridStatus.IDLE

    def test_grid_range_calculation(self):
        """그리드 범위 계산 테스트"""
        bot = BinanceGridBot(
            bot_id="grid_test",
            capital=11.0,
            grid_count=20,
            grid_spacing_pct=0.005,
            sandbox=True,
            telegram_alerts=False
        )

        # Mock current price
        bot.current_price = 50000.0
        bot._calculate_grid_range()

        assert bot.grid_range_low > 0
        assert bot.grid_range_high > bot.grid_range_low
        assert len(bot.grid_levels) == 20

    def test_grid_levels_created(self):
        """그리드 레벨 생성 테스트"""
        bot = BinanceGridBot(
            bot_id="grid_test",
            capital=11.0,
            grid_count=10,
            sandbox=True,
            telegram_alerts=False
        )

        bot.current_price = 100.0
        bot._calculate_grid_range()

        assert len(bot.grid_levels) == 10
        assert 0 in bot.grid_levels
        assert 9 in bot.grid_levels

    def test_order_amount_calculation(self):
        """주문 수량 계산 테스트"""
        bot = BinanceGridBot(
            bot_id="grid_test",
            capital=11.0,
            grid_count=10,
            sandbox=True,
            telegram_alerts=False
        )

        bot.current_price = 50000.0
        amount = bot._calculate_order_amount()

        expected = (11.0 / 10) / 50000.0
        assert amount == pytest.approx(expected, rel=1e-6)

    def test_grid_status(self):
        """그리드 상태 조회 테스트"""
        bot = BinanceGridBot(
            bot_id="grid_test",
            capital=11.0,
            sandbox=True,
            telegram_alerts=False
        )

        status = bot.get_status()

        assert status["bot_id"] == "grid_test"
        assert status["bot_type"] == "grid"
        assert status["capital"] == 11.0
        assert status["status"] == "idle"


class TestBinanceDCABot:
    """Binance DCA Bot 테스트"""

    def test_dca_bot_initialization(self):
        """DCA 봇 초기화 테스트"""
        bot = BinanceDCABot(
            bot_id="dca_test_001",
            symbol="BTC/USDT",
            exchange_id="binance",
            capital=14.0,
            dca_drop_pct=0.02,
            take_profit_pct=0.03,
            sandbox=True,
            telegram_alerts=False
        )

        assert bot.bot_id == "dca_test_001"
        assert bot.symbol == "BTC/USDT"
        assert bot.capital == 14.0
        assert bot.dca_drop_pct == 0.02
        assert bot.take_profit_pct == 0.03
        assert bot.status == DCAStatus.IDLE
        assert bot.position is None

    def test_dca_position_creation(self):
        """DCA 포지션 생성 테스트"""
        position = DCAPosition(
            entry_price=50000.0,
            amount=0.001,
            timestamp=datetime.utcnow(),
            dca_count=1
        )

        assert position.entry_price == 50000.0
        assert position.amount == 0.001
        assert position.dca_count == 1
        assert position.total_cost == 50.0

    def test_dca_position_average_price(self):
        """DCA 평균 단가 계산 테스트"""
        # 첫 매수: 0.001 BTC @ $50,000
        position = DCAPosition(
            entry_price=50000.0,
            amount=0.001,
            timestamp=datetime.utcnow(),
            dca_count=1
        )

        # DCA 추가 매수: 0.001 BTC @ $48,000
        total_cost = (position.entry_price * position.amount) + (48000.0 * 0.001)
        total_amount = position.amount + 0.001
        position.entry_price = total_cost / total_amount
        position.amount = total_amount
        position.dca_count = 2

        # 평균 단가 확인
        expected_avg = (50.0 + 48.0) / 0.002  # $49,000
        assert position.entry_price == pytest.approx(expected_avg, rel=1e-6)

    def test_dca_condition_calculation(self):
        """DCA 조건 계산 테스트"""
        bot = BinanceDCABot(
            bot_id="dca_test",
            dca_drop_pct=0.02,
            capital=14.0,
            sandbox=True,
            telegram_alerts=False
        )

        bot.last_dca_price = 50000.0
        bot.current_price = 49000.0  # 2% 하락

        drop_pct = (bot.last_dca_price - bot.current_price) / bot.last_dca_price

        assert drop_pct == pytest.approx(0.02, rel=1e-6)
        assert drop_pct >= bot.dca_drop_pct

    def test_take_profit_condition(self):
        """익절 조건 테스트"""
        bot = BinanceDCABot(
            bot_id="dca_test",
            take_profit_pct=0.03,
            capital=14.0,
            sandbox=True,
            telegram_alerts=False
        )

        bot.position = DCAPosition(
            entry_price=50000.0,
            amount=0.001,
            timestamp=datetime.utcnow()
        )
        bot.current_price = 51500.0  # 3% 상승

        gain_pct = (bot.current_price - bot.position.entry_price) / bot.position.entry_price

        assert gain_pct == pytest.approx(0.03, rel=1e-6)
        assert gain_pct >= bot.take_profit_pct

    def test_dca_status(self):
        """DCA 상태 조회 테스트"""
        bot = BinanceDCABot(
            bot_id="dca_test",
            capital=14.0,
            sandbox=True,
            telegram_alerts=False
        )

        status = bot.get_status()

        assert status["bot_id"] == "dca_test"
        assert status["bot_type"] == "dca"
        assert status["capital"] == 14.0
        assert status["status"] == "idle"
        assert status["dca_drop_pct"] == 0.02
        assert status["take_profit_pct"] == 0.03


class TestUnifiedBotManagerRegistration:
    """UnifiedBotManager 등록 테스트"""

    def setup_method(self):
        """각 테스트 전 실행"""
        reset_bot_manager()

    def test_register_grid_bot(self):
        """그리드봇 등록 테스트"""
        manager = get_bot_manager()

        config = BotConfig(
            bot_id="grid_binance_001",
            bot_type=BotType.GRID,
            exchange="binance",
            symbol="BTC/USDT",
            capital=11.0,
            sandbox=False
        )

        mock_bot = Mock()
        result = manager.register_bot(config, mock_bot)

        assert result == True
        assert "grid_binance_001" in manager._bots
        assert manager._bot_infos["grid_binance_001"].bot_type == BotType.GRID

    def test_register_dca_bot(self):
        """DCA봇 등록 테스트"""
        manager = get_bot_manager()

        config = BotConfig(
            bot_id="dca_binance_001",
            bot_type=BotType.DCA,
            exchange="binance",
            symbol="BTC/USDT",
            capital=14.0,
            sandbox=False
        )

        mock_bot = Mock()
        result = manager.register_bot(config, mock_bot)

        assert result == True
        assert "dca_binance_001" in manager._bots
        assert manager._bot_infos["dca_binance_001"].bot_type == BotType.DCA

    def test_get_bots_summary(self):
        """봇 요약 정보 테스트"""
        manager = get_bot_manager()

        # 여러 봇 등록
        bots = [
            ("grid_binance_001", BotType.GRID, 11.0),
            ("dca_binance_001", BotType.DCA, 14.0),
        ]

        for bot_id, bot_type, capital in bots:
            config = BotConfig(
                bot_id=bot_id,
                bot_type=bot_type,
                exchange="binance",
                symbol="BTC/USDT",
                capital=capital,
                sandbox=False
            )
            mock_bot = Mock()
            manager.register_bot(config, mock_bot)

        summary = manager.get_summary()

        assert summary["total_bots"] == 2
        assert summary["total_capital"] == 25.0  # 11 + 14


class TestEnvironmentVariables:
    """환경변수 테스트"""

    def test_binance_api_keys_present(self):
        """Binance API 키 존재 여부 테스트"""
        required_keys = [
            "BINANCE_API_KEY",
            "BINANCE_API_SECRET",
        ]

        missing_keys = [key for key in required_keys if not os.environ.get(key)]
        print(f"\nMissing Binance environment variables: {missing_keys}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

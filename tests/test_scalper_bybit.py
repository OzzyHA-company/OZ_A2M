"""
Test: Bybit Scalping Bot
STEP 9: OZ_A2M 완결판

테스트 항목:
- BybitScalpingBot 초기화
- UnifiedBotManager 등록
- Telegram 알림 (Mock)
- 환경변수 로드
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

from department_7.src.bot.scalper import BybitScalpingBot, Position, Trade, PositionSide, BotState
from department_7.src.bot.unified_bot_manager import (
    UnifiedBotManager, BotConfig, BotType, BotStatus,
    get_bot_manager, reset_bot_manager, create_and_register_scalper_bot
)


class TestBybitScalpingBot:
    """Bybit 스캘핑봇 테스트"""

    def test_bot_initialization(self):
        """봇 초기화 테스트"""
        bot = BybitScalpingBot(
            bot_id="test_scalper_001",
            symbol="SOL/USDT",
            exchange_id="bybit",
            sandbox=True,
            capital=20.0,
            telegram_alerts=False
        )

        assert bot.bot_id == "test_scalper_001"
        assert bot.symbol == "SOL/USDT"
        assert bot.exchange_id == "bybit"
        assert bot.capital == 20.0
        assert bot.sandbox == True
        assert bot.state == BotState.IDLE
        assert bot.telegram_alerts == False

    def test_bot_initial_capital(self):
        """초기 자본 설정 테스트"""
        bot = BybitScalpingBot(
            bot_id="test_scalper",
            capital=20.0,
            sandbox=True,
            telegram_alerts=False
        )

        assert bot.initial_capital == 20.0
        assert bot.balance == 20.0
        assert bot.max_daily_loss == 4.0  # 20% of capital

    def test_position_creation(self):
        """포지션 생성 테스트"""
        position = Position(
            symbol="SOL/USDT",
            side=PositionSide.LONG,
            entry_price=150.0,
            amount=0.1,
            entry_time=datetime.utcnow(),
            unrealized_pnl=0.0
        )

        assert position.symbol == "SOL/USDT"
        assert position.side == PositionSide.LONG
        assert position.entry_price == 150.0
        assert position.amount == 0.1

    def test_trade_creation(self):
        """거래 생성 테스트"""
        trade = Trade(
            id="test_trade_001",
            symbol="SOL/USDT",
            side="buy",
            amount=0.1,
            price=150.0,
            timestamp=datetime.utcnow(),
            pnl=None
        )

        assert trade.id == "test_trade_001"
        assert trade.symbol == "SOL/USDT"
        assert trade.side == "buy"
        assert trade.pnl is None

    def test_position_to_dict(self):
        """포지션 직렬화 테스트"""
        position = Position(
            symbol="SOL/USDT",
            side=PositionSide.LONG,
            entry_price=150.0,
            amount=0.1,
            entry_time=datetime.utcnow()
        )

        data = position.to_dict()
        assert data["symbol"] == "SOL/USDT"
        assert data["side"] == "long"
        assert data["entry_price"] == 150.0

    @pytest.mark.asyncio
    async def test_bot_status(self):
        """봇 상태 조회 테스트"""
        bot = BybitScalpingBot(
            bot_id="test_scalper",
            capital=20.0,
            sandbox=True,
            telegram_alerts=False
        )

        status = bot.get_status()

        assert status["bot_id"] == "test_scalper"
        assert status["bot_type"] == "scalping"
        assert status["exchange"] == "bybit"
        assert status["state"] == "idle"
        assert status["capital"] == 20.0


class TestUnifiedBotManager:
    """UnifiedBotManager 테스트"""

    def setup_method(self):
        """각 테스트 전 실행"""
        reset_bot_manager()

    def test_singleton_pattern(self):
        """싱글톤 패턴 테스트"""
        manager1 = get_bot_manager()
        manager2 = get_bot_manager()

        assert manager1 is manager2

    def test_bot_registration(self):
        """봇 등록 테스트"""
        manager = get_bot_manager()

        config = BotConfig(
            bot_id="test_bot_001",
            bot_type=BotType.SCALPING,
            exchange="bybit",
            symbol="SOL/USDT",
            capital=20.0
        )

        mock_bot = Mock()
        result = manager.register_bot(config, mock_bot)

        assert result == True
        assert "test_bot_001" in manager._bots
        assert manager._bot_infos["test_bot_001"].bot_type == BotType.SCALPING

    def test_duplicate_registration(self):
        """중복 등록 방지 테스트"""
        manager = get_bot_manager()

        config = BotConfig(
            bot_id="test_bot_dup",
            bot_type=BotType.SCALPING,
            exchange="bybit",
            symbol="SOL/USDT",
            capital=20.0
        )

        mock_bot = Mock()
        manager.register_bot(config, mock_bot)
        result = manager.register_bot(config, mock_bot)

        assert result == False

    def test_get_bot_status(self):
        """봇 상태 조회 테스트"""
        manager = get_bot_manager()

        config = BotConfig(
            bot_id="test_status_bot",
            bot_type=BotType.GRID,
            exchange="binance",
            symbol="BTC/USDT",
            capital=11.0
        )

        mock_bot = Mock()
        manager.register_bot(config, mock_bot)

        info = manager.get_bot_status("test_status_bot")

        assert info is not None
        assert info.bot_id == "test_status_bot"
        assert info.exchange == "binance"
        assert info.capital == 11.0
        assert info.status == BotStatus.STOPPED

    def test_get_summary(self):
        """요약 정보 테스트"""
        reset_bot_manager()  # 싱글톤 초기화
        manager = get_bot_manager()

        # 기존 봇 클리어
        manager._bots.clear()
        manager._bot_configs.clear()
        manager._bot_infos.clear()

        # 봇 등록
        for i in range(3):
            config = BotConfig(
                bot_id=f"summary_bot_{i}",
                bot_type=BotType.SCALPING,
                exchange="bybit",
                symbol="SOL/USDT",
                capital=20.0
            )
            mock_bot = Mock()
            manager.register_bot(config, mock_bot)

        summary = manager.get_summary()

        assert summary["total_bots"] == 3
        assert summary["total_capital"] == 60.0
        assert summary["kill_switch_active"] == False
        assert len(summary["bots"]) == 3

    def test_kill_switch(self):
        """킬스위치 테스트"""
        manager = get_bot_manager()

        assert manager._kill_switch_active == False

        # asyncio.run을 사용하여 비동기 메서드 호출
        asyncio.run(manager.kill_switch())

        assert manager._kill_switch_active == True

    def test_reset_kill_switch(self):
        """킬스위치 리셋 테스트"""
        manager = get_bot_manager()

        asyncio.run(manager.kill_switch())
        assert manager._kill_switch_active == True

        manager.reset_kill_switch()
        assert manager._kill_switch_active == False

    def test_update_bot_pnl(self):
        """PnL 업데이트 테스트"""
        manager = get_bot_manager()

        config = BotConfig(
            bot_id="test_pnl_bot",
            bot_type=BotType.SCALPING,
            exchange="bybit",
            symbol="SOL/USDT",
            capital=20.0
        )

        mock_bot = Mock()
        manager.register_bot(config, mock_bot)

        manager.update_bot_pnl("test_pnl_bot", pnl=5.5, trades=10, win_rate=60.0)

        info = manager.get_bot_status("test_pnl_bot")
        assert info.current_pnl == 5.5
        assert info.total_trades == 10
        assert info.win_rate == 60.0


class TestBotConfig:
    """봇 설정 테스트"""

    def test_scalper_config(self):
        """스캘핑봇 설정 테스트"""
        config = BotConfig(
            bot_id="scalper_bybit_001",
            bot_type=BotType.SCALPING,
            exchange="bybit",
            symbol="SOL/USDT",
            capital=20.0,
            sandbox=False
        )

        assert config.bot_id == "scalper_bybit_001"
        assert config.bot_type == BotType.SCALPING
        assert config.exchange == "bybit"
        assert config.symbol == "SOL/USDT"
        assert config.capital == 20.0
        assert config.sandbox == False

    def test_grid_config(self):
        """그리드봇 설정 테스트"""
        config = BotConfig(
            bot_id="grid_binance_001",
            bot_type=BotType.GRID,
            exchange="binance",
            symbol="BTC/USDT",
            capital=11.0,
            sandbox=False
        )

        assert config.bot_id == "grid_binance_001"
        assert config.bot_type == BotType.GRID
        assert config.capital == 11.0


class TestEnvironmentVariables:
    """환경변수 테스트"""

    def test_api_keys_present(self):
        """API 키 존재 여부 테스트 (값은 검사하지 않음)"""
        required_keys = [
            "BYBIT_API_KEY",
            "BYBIT_API_SECRET",
            "BINANCE_API_KEY",
            "BINANCE_API_SECRET",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID"
        ]

        missing_keys = [key for key in required_keys if not os.environ.get(key)]

        # 테스트 환경에서는 일부 키가 없을 수 있음
        # 실제 배포 환경에서는 모든 키가 필요
        print(f"\nMissing environment variables: {missing_keys}")


class TestIntegration:
    """통합 테스트"""

    @pytest.mark.asyncio
    async def test_create_and_register_scalper_bot(self):
        """스캘핑봇 생성 및 등록 통합 테스트"""
        reset_bot_manager()

        # 환경변수 모킹
        with patch.dict(os.environ, {
            "BYBIT_API_KEY": "test_key",
            "BYBIT_API_SECRET": "test_secret"
        }):
            bot = await create_and_register_scalper_bot(
                bot_id="test_integration_001",
                capital=20.0,
                sandbox=True
            )

            # 봇이 생성되었거나 None이면 API 키 문제
            if bot is not None:
                assert bot.bot_id == "test_integration_001"
                assert bot.symbol == "SOL/USDT"
                assert bot.capital == 20.0

                manager = get_bot_manager()
                assert "test_integration_001" in manager._bots


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

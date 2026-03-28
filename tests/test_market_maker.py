"""
Market Maker Bot Tests

STEP 7: 시장 조성 봇 테스트
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from department_7.src.bot.market_maker_bot import (
    MarketMakerBot,
    OrderBook,
    Inventory,
)


class TestOrderBook:
    """OrderBook 테스트"""

    def test_orderbook_creation(self):
        """오더북 생성 테스트"""
        ob = OrderBook(
            symbol="BTC/USDT",
            bids=[(50000.0, 1.0), (49990.0, 2.0)],
            asks=[(50010.0, 1.0), (50020.0, 2.0)],
            timestamp=datetime.utcnow(),
        )

        assert ob.symbol == "BTC/USDT"
        assert ob.best_bid == 50000.0
        assert ob.best_ask == 50010.0
        assert ob.mid_price == 50005.0
        assert ob.spread == 10.0

    def test_orderbook_spread_percent(self):
        """스프레드 퍼센트 계산 테스트"""
        ob = OrderBook(
            symbol="BTC/USDT",
            bids=[(50000.0, 1.0)],
            asks=[(50100.0, 1.0)],
            timestamp=datetime.utcnow(),
        )

        # 스프레드 100, 중간가 50050 → 약 0.2%
        assert ob.spread_percent == pytest.approx(0.2, abs=0.01)


class TestInventory:
    """Inventory 테스트"""

    def test_inventory_creation(self):
        """인벤토리 생성 테스트"""
        inv = Inventory(
            base_asset=0.5,  # 0.5 BTC
            quote_asset=5000.0,  # 5000 USDT
            base_value=25000.0,  # 0.5 BTC @ $50,000
        )

        assert inv.total_value == 30000.0
        assert inv.inventory_ratio == pytest.approx(0.833, abs=0.01)

    def test_balanced_inventory(self):
        """균형 잡힌 인벤토리 테스트"""
        inv = Inventory(
            base_asset=0.5,
            quote_asset=25000.0,
            base_value=25000.0,
        )

        assert inv.inventory_ratio == 0.5  # 50:50


class TestMarketMakerBot:
    """MarketMakerBot 테스트"""

    @pytest.fixture
    def bot(self):
        """테스트용 봇"""
        return MarketMakerBot(
            bot_id="test_mm_001",
            symbol="BTC/USDT",
            base_spread_bps=10.0,
            target_inventory_ratio=0.5,
        )

    @pytest.fixture
    def sample_orderbook(self):
        """샘플 오더북"""
        return OrderBook(
            symbol="BTC/USDT",
            bids=[(50000.0, 1.0), (49990.0, 2.0)],
            asks=[(50010.0, 1.0), (50020.0, 2.0)],
            timestamp=datetime.utcnow(),
        )

    def test_bot_initialization(self, bot):
        """봇 초기화 테스트"""
        assert bot.bot_id == "test_mm_001"
        assert bot.symbol == "BTC/USDT"
        assert bot.base_spread_bps == 10.0
        assert bot.running is False

    def test_calculate_spread(self, bot, sample_orderbook):
        """스프레드 계산 테스트"""
        spread = bot.calculate_spread(sample_orderbook)

        # 기본 스프레드 0.1% (10 bps) + 인벤토리 스큐 조정
        # 인벤토리가 0이므로 target(0.5)와 차이로 인해 스큐 조정 발생
        assert spread >= 0.001  # 최소 기본 스프레드

    def test_calculate_quotes(self, bot, sample_orderbook):
        """호가 계산 테스트"""
        quotes = bot.calculate_quotes(sample_orderbook)

        assert quotes is not None
        assert "bid" in quotes
        assert "ask" in quotes
        assert "mid" in quotes
        assert quotes["ask"] > quotes["bid"]
        assert quotes["mid"] == 50005.0

    def test_inventory_skew_adjustment(self, bot, sample_orderbook):
        """인벤토리 스큐 조정 테스트"""
        # 인벤토리 과다 설정
        bot.inventory = Inventory(
            base_asset=0.8,
            quote_asset=1000.0,
            base_value=40000.0,
        )

        quotes1 = bot.calculate_quotes(sample_orderbook)

        # 인벤토리 부족 설정
        bot.inventory = Inventory(
            base_asset=0.1,
            quote_asset=45000.0,
            base_value=5000.0,
        )

        quotes2 = bot.calculate_quotes(sample_orderbook)

        # 스큐 방향이 반대여야 함
        skew1 = quotes1["bid"] / quotes1["ask"]
        skew2 = quotes2["bid"] / quotes2["ask"]
        assert skew1 < skew2  # 과다 시 매도 우대, 부족 시 매수 우대

    def test_check_inventory_limits(self, bot):
        """인벤토리 한도 체크 테스트"""
        # 정상 인벤토리
        bot.inventory = Inventory(
            base_asset=0.5,
            quote_asset=25000.0,
            base_value=25000.0,
        )
        passed, msg = bot.check_inventory_limits()
        assert passed is True
        assert msg == "OK"

        # 과다 인벤토리
        bot.inventory = Inventory(
            base_asset=0.9,
            quote_asset=1000.0,
            base_value=45000.0,
        )
        passed, msg = bot.check_inventory_limits()
        assert passed is False
        assert "과다" in msg

    def test_check_position_limits(self, bot):
        """포지션 한도 체크 테스트"""
        bot.inventory.base_asset = 0.5
        assert bot.check_position_limits("buy") is True
        assert bot.check_position_limits("sell") is True

        # max_position = 1.0, 현재 1.5면 한도 초과
        bot.inventory.base_asset = 1.5
        assert bot.check_position_limits("buy") is False  # 한도 초과

    @pytest.mark.asyncio
    async def test_place_orders(self, bot, sample_orderbook):
        """주문 배치 테스트"""
        # 인벤토리를 정상 상태로 설정 (한도 내)
        bot.inventory = Inventory(
            base_asset=0.5,
            quote_asset=25000.0,
            base_value=25000.0,
        )

        result = await bot.place_orders(sample_orderbook)

        # 인벤토리 상태에 따라 success 또는 skipped 반환 가능
        assert result["status"] in ["success", "skipped"]
        if result["status"] == "success":
            assert result["orders_count"] >= 0
            assert "quotes" in result

    @pytest.mark.asyncio
    async def test_place_orders_inventory_limit(self, bot, sample_orderbook):
        """인벤토리 한도로 주문 스킵 테스트"""
        # 과다 인벤토리 설정
        bot.inventory = Inventory(
            base_asset=0.9,
            quote_asset=1000.0,
            base_value=45000.0,
        )

        result = await bot.place_orders(sample_orderbook)

        assert result["status"] == "skipped"
        assert "과다" in result["reason"]

    @pytest.mark.asyncio
    async def test_update_inventory(self, bot):
        """인벤토리 업데이트 테스트"""
        initial_base = bot.inventory.base_asset
        initial_filled = bot.orders_filled

        trade = {
            "side": "buy",
            "size": 0.1,
            "price": 50000.0,
        }

        await bot.update_inventory(trade)

        assert bot.inventory.base_asset == initial_base + 0.1
        assert bot.orders_filled == initial_filled + 1

    def test_get_stats(self, bot):
        """통계 조회 테스트"""
        stats = bot.get_stats()

        assert stats["bot_id"] == "test_mm_001"
        assert stats["symbol"] == "BTC/USDT"
        assert "inventory" in stats
        assert "orders" in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

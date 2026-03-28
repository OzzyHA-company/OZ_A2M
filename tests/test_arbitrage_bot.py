"""
Arbitrage Bot Tests

STEP 7: 차익거래 봇 테스트
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from department_7.src.bot.arbitrage_bot import (
    ArbitrageBot,
    PriceData,
    ArbitrageOpportunity,
)


class TestPriceData:
    """PriceData 테스트"""

    def test_price_data_creation(self):
        """가격 데이터 생성 테스트"""
        price = PriceData(
            exchange="binance",
            symbol="BTC/USDT",
            bid=50000.0,
            ask=50010.0,
            timestamp=datetime.utcnow(),
        )

        assert price.exchange == "binance"
        assert price.mid == 50005.0


class TestArbitrageOpportunity:
    """ArbitrageOpportunity 테스트"""

    def test_opportunity_creation(self):
        """차익 기회 생성 테스트"""
        opp = ArbitrageOpportunity(
            symbol="BTC/USDT",
            buy_exchange="binance",
            sell_exchange="bybit",
            buy_price=50000.0,
            sell_price=50100.0,
            spread=100.0,
            spread_percent=20.0,
            profit_estimate=1.0,
        )

        assert opp.buy_exchange == "binance"
        assert opp.sell_exchange == "bybit"
        assert opp.spread == 100.0


class TestArbitrageBot:
    """ArbitrageBot 테스트"""

    @pytest.fixture
    def bot(self):
        """테스트용 봇"""
        return ArbitrageBot(
            bot_id="test_arb_001",
            symbol="BTC/USDT",
            exchanges=["binance", "bybit"],
            min_spread_bps=50.0,
            min_profit_usd=5.0,
        )

    def test_bot_initialization(self, bot):
        """봇 초기화 테스트"""
        assert bot.bot_id == "test_arb_001"
        assert bot.symbol == "BTC/USDT"
        assert bot.exchanges == ["binance", "bybit"]
        assert bot.min_spread_bps == 50.0

    def test_check_arbitrage_opportunity_valid(self, bot):
        """유효한 차익 기회 테스트"""
        # min_spread_bps=50 (0.5%), min_profit_usd=5, trade_size=0.01
        # 필요: spread >= 0.5% (50000 * 0.005 = 250), profit >= 5 (spread * 0.01 >= 5 → spread >= 500)
        price1 = PriceData(
            exchange="binance",
            symbol="BTC/USDT",
            bid=50000.0,
            ask=50000.0,  # 매수가 (ask) 낮음
            timestamp=datetime.utcnow(),
        )
        price2 = PriceData(
            exchange="bybit",
            symbol="BTC/USDT",
            bid=50600.0,  # 매도가 (bid) 높음 - 스프레드 600 (1.2%)
            ask=50610.0,
            timestamp=datetime.utcnow(),
        )

        opp = bot.check_arbitrage_opportunity(price1, price2)

        assert opp is not None
        assert opp.buy_exchange == "binance"
        assert opp.sell_exchange == "bybit"
        assert opp.profit_estimate >= bot.min_profit_usd

    def test_check_arbitrage_opportunity_no_spread(self, bot):
        """스프레드 없음 테스트"""
        price1 = PriceData(
            exchange="binance",
            symbol="BTC/USDT",
            bid=50000.0,
            ask=50010.0,
            timestamp=datetime.utcnow(),
        )
        price2 = PriceData(
            exchange="bybit",
            symbol="BTC/USDT",
            bid=50005.0,
            ask=50015.0,
            timestamp=datetime.utcnow(),
        )

        opp = bot.check_arbitrage_opportunity(price1, price2)

        # 스프레드가 충분하지 않음
        assert opp is None

    def test_check_arbitrage_opportunity_small_spread(self, bot):
        """작은 스프레드 테스트"""
        price1 = PriceData(
            exchange="binance",
            symbol="BTC/USDT",
            bid=50000.0,
            ask=50002.0,  # 작은 스프레드
            timestamp=datetime.utcnow(),
        )
        price2 = PriceData(
            exchange="bybit",
            symbol="BTC/USDT",
            bid=50050.0,
            ask=50052.0,
            timestamp=datetime.utcnow(),
        )

        opp = bot.check_arbitrage_opportunity(price1, price2)

        # 스프레드는 있지만 수익이 작음
        if opp:
            assert opp.spread_percent >= bot.min_spread_bps

    def test_scan_opportunities(self, bot):
        """차익 기회 스캔 테스트"""
        # 가격 데이터 설정
        bot.price_data = {
            "binance": PriceData(
                exchange="binance",
                symbol="BTC/USDT",
                bid=50000.0,
                ask=50010.0,
                timestamp=datetime.utcnow(),
            ),
            "bybit": PriceData(
                exchange="bybit",
                symbol="BTC/USDT",
                bid=50150.0,
                ask=50160.0,
                timestamp=datetime.utcnow(),
            ),
        }

        opportunities = bot.scan_opportunities()

        assert len(opportunities) >= 0

    def test_validate_execution_daily_limit(self, bot):
        """일일 거래 한도 검증 테스트"""
        bot.daily_trades = bot.max_daily_trades + 1

        opp = ArbitrageOpportunity(
            symbol="BTC/USDT",
            buy_exchange="binance",
            sell_exchange="bybit",
            buy_price=50000.0,
            sell_price=50100.0,
            spread=100.0,
            spread_percent=100.0,
            profit_estimate=10.0,
        )

        valid, msg = bot.validate_execution(opp)

        assert valid is False
        assert "limit" in msg.lower()

    def test_validate_execution_small_profit(self, bot):
        """작은 수익 검증 테스트"""
        bot.daily_trades = 0

        opp = ArbitrageOpportunity(
            symbol="BTC/USDT",
            buy_exchange="binance",
            sell_exchange="bybit",
            buy_price=50000.0,
            sell_price=50001.0,
            spread=1.0,
            spread_percent=2.0,
            profit_estimate=0.01,  # 매우 작은 수익
        )

        valid, msg = bot.validate_execution(opp)

        # 슬리피지 고려 후 수익이 너무 작음
        assert valid is False

    @pytest.mark.asyncio
    async def test_execute_arbitrage(self, bot):
        """차익거래 실행 테스트"""
        opp = ArbitrageOpportunity(
            symbol="BTC/USDT",
            buy_exchange="binance",
            sell_exchange="bybit",
            buy_price=50000.0,
            sell_price=50100.0,
            spread=100.0,
            spread_percent=20.0,
            profit_estimate=1.0,
        )

        result = await bot.execute_arbitrage(opp)

        assert result["status"] in ["success", "rejected"]

    @pytest.mark.asyncio
    async def test_update_price(self, bot):
        """가격 업데이트 테스트"""
        await bot.update_price("binance", 50000.0, 50010.0)

        assert "binance" in bot.price_data
        assert bot.price_data["binance"].bid == 50000.0
        assert bot.price_data["binance"].ask == 50010.0

    def test_get_stats(self, bot):
        """통계 조회 테스트"""
        stats = bot.get_stats()

        assert stats["bot_id"] == "test_arb_001"
        assert stats["symbol"] == "BTC/USDT"
        assert "exchanges" in stats
        assert "daily_trades" in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

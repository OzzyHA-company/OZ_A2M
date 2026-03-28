"""
트렌드 팔로워 봇 테스트

STEP 3: Trend Following 봇 + WebSocket 브릿지
"""

import pytest
import json
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch

from department_7.src.bot.trend_follower import (
    TrendFollowerBot,
    TradeSignal,
    Position,
    EMA_FAST,
    EMA_SLOW
)


class TestTrendFollowerBot:
    """TrendFollowerBot 기본 테스트"""

    @pytest.fixture
    def bot(self):
        """테스트용 봇 인스턴스"""
        bot = TrendFollowerBot()
        bot.bot_id = 'test_trend_bot'
        bot.symbol = 'BTC/USDT'
        bot.timeframe = '15m'
        bot.mqtt_client = Mock()
        return bot

    def test_bot_initialization(self, bot):
        """봇 초기화 테스트"""
        assert bot.bot_id == 'test_trend_bot'
        assert bot.symbol == 'BTC/USDT'
        assert bot.timeframe == '15m'
        assert bot.position is None
        assert bot.running is False

    def test_calculate_ema(self, bot):
        """EMA 계산 테스트"""
        prices = [100.0] * 10 + [110.0] * 10 + [120.0] * 10

        ema20 = bot.calculate_ema(prices, 20)
        ema50 = bot.calculate_ema(prices, 50)

        assert ema20 > 100.0
        assert ema50 > 100.0
        assert ema20 != ema50

    def test_calculate_macd(self, bot):
        """MACD 계산 테스트"""
        # 상승 추세 데이터
        prices = [100.0 + i * 2 for i in range(30)]

        macd, signal, histogram = bot.calculate_macd(prices)

        assert isinstance(macd, float)
        assert isinstance(signal, float)
        assert isinstance(histogram, float)

    def test_analyze_trend_neutral(self, bot):
        """중립 추세 분석 테스트"""
        # 충분하지 않은 데이터
        trend = bot.analyze_trend()
        assert trend['direction'] == 'NEUTRAL'
        assert trend['strength'] == 0.0

    def test_analyze_trend_up(self, bot):
        """상승 추세 분석 테스트"""
        # 상승 추세 데이터 생성 (EMA_FAST > EMA_SLOW)
        for i in range(60):
            # EMA50을 넘는 데이터
            price = 50000.0 + i * 100
            bot.price_history.append(price)

        trend = bot.analyze_trend()

        assert 'direction' in trend
        assert 'ema_fast' in trend
        assert 'ema_slow' in trend
        assert 'macd' in trend
        assert 'histogram' in trend

    def test_should_enter_long(self, bot):
        """LONG 진입 조건 테스트"""
        # 상승 추세 조건
        trend = {
            'direction': 'UP',
            'strength': 0.5,
            'histogram': 0.5
        }
        assert bot.should_enter_long(trend) is True

        # 약한 추세
        trend['strength'] = 0.1
        assert bot.should_enter_long(trend) is False

        # MACD 음수
        trend['strength'] = 0.5
        trend['histogram'] = -0.5
        assert bot.should_enter_long(trend) is False

    def test_should_enter_short(self, bot):
        """SHORT 진입 조건 테스트"""
        # 하띗 추세 조건
        trend = {
            'direction': 'DOWN',
            'strength': 0.5,
            'histogram': -0.5
        }
        assert bot.should_enter_short(trend) is True

        # MACD 양수
        trend['histogram'] = 0.5
        assert bot.should_enter_short(trend) is False

    def test_should_close_position_long(self, bot):
        """LONG 포지션 청산 조건 테스트"""
        bot.position = Position(
            symbol='BTC/USDT',
            entry_price=50000.0,
            quantity=0.1,
            side='LONG',
            stop_loss=49000.0,
            take_profit=53000.0,
            entry_time=datetime.now().isoformat()
        )

        # 추세 반전
        trend = {'direction': 'DOWN', 'histogram': 0.0}
        assert bot.should_close_position(trend) is True

        # 상승 추세 유지
        trend['direction'] = 'UP'
        assert bot.should_close_position(trend) is False

    def test_enter_position_long(self, bot):
        """LONG 포지션 진입 테스트"""
        trend = {
            'direction': 'UP',
            'ema_fast': 51000.0,
            'ema_slow': 50000.0,
            'histogram': 0.5
        }

        bot.enter_position('LONG', 50000.0, trend)

        assert bot.position is not None
        assert bot.position.side == 'LONG'
        assert bot.position.entry_price == 50000.0
        assert bot.position.stop_loss < 50000.0
        assert bot.position.take_profit > 50000.0

    def test_close_position(self, bot):
        """포지션 청산 테스트"""
        bot.position = Position(
            symbol='BTC/USDT',
            entry_price=50000.0,
            quantity=0.1,
            side='LONG',
            stop_loss=49000.0,
            take_profit=53000.0,
            entry_time=datetime.now().isoformat()
        )

        trend = {
            'direction': 'DOWN',
            'ema_fast': 49000.0,
            'histogram': -0.5
        }

        bot.close_position(51000.0, trend)

        assert bot.position is None

    def test_update_position_pnl_long(self, bot):
        """LONG 포지션 PnL 업데이트 테스트"""
        bot.position = Position(
            symbol='BTC/USDT',
            entry_price=50000.0,
            quantity=0.1,
            side='LONG',
            stop_loss=49000.0,
            take_profit=53000.0,
            entry_time=datetime.now().isoformat()
        )

        bot.update_position_pnl(51000.0)

        assert bot.position.unrealized_pnl == 100.0  # (51000 - 50000) * 0.1

    def test_update_position_pnl_short(self, bot):
        """SHORT 포지션 PnL 업데이트 테스트"""
        bot.position = Position(
            symbol='BTC/USDT',
            entry_price=50000.0,
            quantity=0.1,
            side='SHORT',
            stop_loss=51000.0,
            take_profit=47000.0,
            entry_time=datetime.now().isoformat()
        )

        bot.update_position_pnl(49000.0)

        assert bot.position.unrealized_pnl == 100.0  # (50000 - 49000) * 0.1


class TestTradeSignal:
    """TradeSignal 데이터클스 테스트"""

    def test_trade_signal_creation(self):
        """TradeSignal 생성 테스트"""
        signal = TradeSignal(
            bot_id='test_bot',
            symbol='BTC/USDT',
            action='BUY',
            price=50000.0,
            quantity=0.1,
            timestamp=datetime.now().isoformat(),
            stop_loss=49000.0,
            take_profit=53000.0,
            reason='EMA crossover'
        )

        assert signal.bot_id == 'test_bot'
        assert signal.action == 'BUY'
        assert signal.price == 50000.0

    def test_trade_signal_to_dict(self):
        """TradeSignal 직렬화 테스트"""
        signal = TradeSignal(
            bot_id='test_bot',
            symbol='BTC/USDT',
            action='BUY',
            price=50000.0,
            quantity=0.1,
            timestamp='2024-03-28T10:00:00',
            reason='Test'
        )

        data = signal.to_dict()
        assert data['bot_id'] == 'test_bot'
        assert data['action'] == 'BUY'
        assert data['price'] == 50000.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Department 2: Verification Center Tests
정보검증분석센터 테스트
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock

from department_2.src.noise_filter import (
    NoiseFilter,
    SignalVerifier,
    SignalQuality,
    FilterResult,
)


class TestNoiseFilter:
    """NoiseFilter 테스트"""

    @pytest.fixture
    def noise_filter(self):
        """테스트용 노이즈 필터"""
        return NoiseFilter(
            rsi_period=14,
            rsi_overbought=70.0,
            rsi_oversold=30.0,
        )

    def test_calculate_rsi_neutral(self, noise_filter):
        """RSI 중립값 테스트"""
        # 상승/하띰이 반복되는 가격 (RSI ≈ 50)
        prices = [100.0] * 15
        rsi = noise_filter.calculate_rsi(prices)
        assert 0 <= rsi <= 100

    def test_calculate_rsi_uptrend(self, noise_filter):
        """RSI 상승 추세 테스트"""
        # 계속 상승하는 가격
        prices = [100.0 + i * 2 for i in range(20)]
        rsi = noise_filter.calculate_rsi(prices)
        assert rsi > 50  # 상승 추세는 RSI > 50

    def test_calculate_rsi_downtrend(self, noise_filter):
        """RSI 하띜 추세 테스트"""
        # 계속 하락하는 가격
        prices = [100.0 - i * 2 for i in range(20)]
        rsi = noise_filter.calculate_rsi(prices)
        assert rsi < 50  # 하띜 추세는 RSI < 50

    def test_calculate_bollinger_bands(self, noise_filter):
        """볼린저 밴드 계산 테스트"""
        prices = [100.0 + i for i in range(20)]
        bb = noise_filter.calculate_bollinger_bands(prices)

        assert "upper" in bb
        assert "middle" in bb
        assert "lower" in bb
        assert bb["upper"] > bb["middle"] > bb["lower"]

    def test_filter_signal_valid_buy(self, noise_filter):
        """유효한 매수 신호 테스트"""
        signal = {
            "action": "BUY",
            "symbol": "BTC/USDT",
            "price": 50000.0,
        }
        # RSI 50에 가까운 가격 (중립)
        prices = [50000.0 + (i % 3 - 1) * 100 for i in range(20)]

        result = noise_filter.filter_signal(signal, prices, volume=5000.0)

        assert result.is_valid is True
        assert result.quality in [SignalQuality.EXCELLENT, SignalQuality.GOOD]
        assert result.confidence > 0.0

    def test_filter_signal_rsi_overbought_rejection(self, noise_filter):
        """RSI 과매수 매수 신호 거부 테스트"""
        signal = {
            "action": "BUY",
            "symbol": "BTC/USDT",
            "price": 50000.0,
        }
        # 계속 상승하는 가격 (과매수)
        prices = [50000.0 + i * 100 for i in range(20)]

        result = noise_filter.filter_signal(signal, prices, volume=5000.0)

        # 과매수 구간에서 매수는 위험
        assert result.is_valid is False or result.quality in [
            SignalQuality.POOR, SignalQuality.REJECT
        ]

    def test_filter_signal_low_volume(self, noise_filter):
        """낮은 거래량 테스트"""
        signal = {
            "action": "BUY",
            "symbol": "BTC/USDT",
            "price": 50000.0,
        }
        prices = [50000.0] * 20

        result = noise_filter.filter_signal(signal, prices, volume=100.0)

        # 거래량 부족으로 거부
        assert result.is_valid is False
        assert "거래량" in result.rejection_reason or "volume" in result.rejection_reason.lower()

    def test_batch_filter(self, noise_filter):
        """배치 필터링 테스트"""
        signals = [
            {"action": "BUY", "symbol": "BTC/USDT", "price": 50000.0},
            {"action": "SELL", "symbol": "ETH/USDT", "price": 3000.0},
        ]
        price_histories = {
            "BTC/USDT": [50000.0 + (i % 3 - 1) * 50 for i in range(20)],
            "ETH/USDT": [3000.0 + (i % 3 - 1) * 10 for i in range(20)],
        }
        volumes = {"BTC/USDT": 5000.0, "ETH/USDT": 3000.0}

        results = noise_filter.batch_filter(signals, price_histories, volumes)

        assert len(results) == 2


class TestSignalVerifier:
    """SignalVerifier 테스트"""

    @pytest.fixture
    def verifier(self):
        """테스트용 검증기"""
        return SignalVerifier(
            cooldown_seconds=60.0,
            max_duplicate_age_seconds=300.0,
        )

    def test_verify_signal_valid(self, verifier):
        """유효한 신호 검증 테스트"""
        signal = {
            "signal_id": "sig_001",
            "symbol": "BTC/USDT",
            "action": "BUY",
            "price": 50000.0,
            "source": "trend_bot",
        }

        result = verifier.verify_signal(signal)

        assert result.is_valid is True
        assert result.quality == SignalQuality.GOOD
        assert result.confidence == 0.9

    def test_verify_signal_duplicate_cooldown(self, verifier):
        """중복 신호 쿨다운 테스트"""
        signal = {
            "signal_id": "sig_001",
            "symbol": "BTC/USDT",
            "action": "BUY",
            "price": 50000.0,
            "source": "trend_bot",
        }

        # 첫 번째 검증
        result1 = verifier.verify_signal(signal)
        assert result1.is_valid is True

        # 즉시 두 번째 검증 (쿨다운)
        result2 = verifier.verify_signal(signal)
        assert result2.is_valid is False
        assert "쿨다운" in result2.rejection_reason

    def test_verify_signal_no_source(self, verifier):
        """소스 없는 신호 테스트"""
        signal = {
            "signal_id": "sig_001",
            "symbol": "BTC/USDT",
            "action": "BUY",
            "price": 50000.0,
            # source 없음
        }

        result = verifier.verify_signal(signal)

        assert result.is_valid is False
        assert "소스" in result.rejection_reason

    def test_verify_signal_invalid_price(self, verifier):
        """유효하지 않은 가격 테스트"""
        signal = {
            "signal_id": "sig_001",
            "symbol": "BTC/USDT",
            "action": "BUY",
            "price": -100.0,  # 음수 가격
            "source": "trend_bot",
        }

        result = verifier.verify_signal(signal)

        assert result.is_valid is False
        assert "가격" in result.rejection_reason

    def test_get_stats(self, verifier):
        """통계 조회 테스트"""
        stats = verifier.get_stats()

        assert "recent_signals_count" in stats
        assert "history_count" in stats
        assert stats["cooldown_seconds"] == 60.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

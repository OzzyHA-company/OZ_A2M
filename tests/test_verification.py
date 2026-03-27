#!/usr/bin/env python3
"""
OZ_A2M 제2부서: 정보검증분석센터 테스트

이 테스트 모듈은 정보검증분석센터의 모든 기능을 검증합니다.
- NoiseFilter: 이상치 탐지 및 스묘딩
- IndicatorEngine: 기술적 지표 계산
- SignalGenerator: 매매 신호 생성
- VerificationPipeline: 9-step 검증
- VerificationCenter: 통합 테스트
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

from occore.verification import (
    # Classes
    NoiseFilter,
    IndicatorEngine,
    SignalGenerator,
    VerificationPipeline,
    VerificationCenter,
    # Dataclasses
    TradingSignal,
    FilteredData,
    VerificationResult,
    IndicatorValues,
    VerificationStep,
    # Enums
    SignalType,
    SignalDirection,
    VerificationStatus,
    # Singleton getters
    get_noise_filter,
    get_indicator_engine,
    get_signal_generator,
    get_verification_center,
)


class TestNoiseFilter(unittest.TestCase):
    """노이즈 필터 테스트"""

    def setUp(self):
        self.filter = NoiseFilter()

    def test_zscore_outlier_detection(self):
        """Z-score 이상치 탐지 테스트"""
        prices = [Decimal('100')] * 10 + [Decimal('200')]  # 마지막 값은 이상치
        outliers = self.filter.detect_outliers_zscore(prices, threshold=2.0)
        self.assertEqual(len(outliers), 1)
        self.assertEqual(outliers[0], 10)

    def test_iqr_outlier_detection(self):
        """IQR 이상치 탐지 테스트"""
        prices = [Decimal('100')] * 15 + [Decimal('200')]
        outliers = self.filter.detect_outliers_iqr(prices)
        self.assertEqual(len(outliers), 1)
        self.assertEqual(outliers[0], 15)

    def test_kalman_smoothing(self):
        """Kalman 필터 스묘딩 테스트"""
        # 노이즈가 있는 데이터
        prices = [
            Decimal('100'), Decimal('102'), Decimal('98'),
            Decimal('150'),  # 스파이크
            Decimal('101'), Decimal('99')
        ]
        smoothed = self.filter.kalman_filter(prices)
        # 스묘딩 후 스파이크가 줄어들었는지 확인
        self.assertLess(abs(float(smoothed[3]) - 100), 30)
        self.assertEqual(len(smoothed), len(prices))

    def test_ema_smoothing(self):
        """EMA 스묘딩 테스트"""
        prices = [Decimal('100'), Decimal('110'), Decimal('105')]
        smoothed = self.filter.ema_smoothing(prices, span=2)
        self.assertEqual(len(smoothed), len(prices))
        # EMA는 첫 값을 유지하거나 평활화됨
        self.assertAlmostEqual(float(smoothed[0]), 100.0)

    def test_median_filter(self):
        """중간값 필터 테스트"""
        prices = [
            Decimal('100'), Decimal('101'), Decimal('150'),  # 스파이크
            Decimal('102'), Decimal('100')
        ]
        filtered = self.filter.median_filter(prices, window=3)
        # 스파이크가 중간값으로 대첵되었는지 확인
        self.assertLess(float(filtered[2]), 150)

    def test_filter_price_data(self):
        """가격 데이터 필터링 통합 테스트"""
        symbol = "BTC-USDT"
        price = Decimal('50000')
        timestamp = datetime.now()
        history = [Decimal('49000'), Decimal('49500'), Decimal('50000')]

        result = self.filter.filter_price_data(symbol, price, timestamp, history)

        self.assertIsInstance(result, FilteredData)
        self.assertEqual(result.symbol, symbol)
        self.assertEqual(result.original_price, price)
        self.assertIsInstance(result.filtered_price, Decimal)
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)


class TestIndicatorEngine(unittest.TestCase):
    """기술적 지표 엔진 테스트"""

    def setUp(self):
        self.engine = IndicatorEngine()
        # 테스트용 가격 데이터 (상승 추세)
        self.prices = [Decimal(str(p)) for p in [
            100, 102, 101, 105, 103, 107, 106, 110, 108, 112,
            111, 115, 113, 117, 116, 120, 118, 122, 121, 125,
            124, 128, 126, 130, 129, 133, 132, 136, 135, 139
        ]]
        self.volumes = [Decimal(str(v)) for v in [
            1000, 1100, 1050, 1200, 1150, 1300, 1250, 1400, 1350, 1500,
            1450, 1600, 1550, 1700, 1650, 1800, 1750, 1900, 1850, 2000,
            1950, 2100, 2050, 2200, 2150, 2300, 2250, 2400, 2350, 2500
        ]]

    def test_sma_calculation(self):
        """SMA 계산 테스트"""
        prices_float = [float(p) for p in self.prices]
        sma = self.engine.calculate_sma(prices_float, period=20)
        self.assertIsNotNone(sma)
        self.assertGreater(sma, 0)

    def test_ema_calculation(self):
        """EMA 계산 테스트"""
        prices_float = [float(p) for p in self.prices]
        ema = self.engine.calculate_ema(prices_float, period=12)
        self.assertIsNotNone(ema)
        self.assertGreater(ema, 0)

    def test_rsi_calculation(self):
        """RSI 계산 테스트"""
        prices_float = [float(p) for p in self.prices]
        rsi = self.engine.calculate_rsi(prices_float, period=14)
        self.assertIsNotNone(rsi)
        self.assertGreaterEqual(rsi, 0)
        self.assertLessEqual(rsi, 100)

    def test_bollinger_bands_calculation(self):
        """볼린저 밴드 계산 테스트"""
        prices_float = [float(p) for p in self.prices]
        upper = self.engine._calculate_bollinger_upper(prices_float)
        middle = self.engine._calculate_bollinger_middle(prices_float)
        lower = self.engine._calculate_bollinger_lower(prices_float)

        self.assertIsNotNone(upper)
        self.assertIsNotNone(middle)
        self.assertIsNotNone(lower)
        self.assertGreater(upper, middle)
        self.assertGreater(middle, lower)

    def test_atr_calculation(self):
        """ATR 계산 테스트"""
        prices_float = [float(p) for p in self.prices]
        atr = self.engine.calculate_atr(prices_float, period=14)
        self.assertIsNotNone(atr)
        self.assertGreater(atr, 0)

    def test_calculate_all_indicators(self):
        """전체 지표 계산 테스트"""
        indicators = self.engine.calculate(
            symbol="BTC-USDT",
            prices=self.prices,
            volumes=self.volumes
        )

        self.assertIsInstance(indicators, IndicatorValues)
        self.assertEqual(indicators.symbol, "BTC-USDT")
        self.assertIsNotNone(indicators.sma_20)
        self.assertIsNotNone(indicators.rsi_14)
        self.assertIsNotNone(indicators.macd)


class TestSignalGenerator(unittest.TestCase):
    """신호 생성기 테스트"""

    def setUp(self):
        self.generator = SignalGenerator()
        self.symbol = "BTC-USDT"
        self.price_history = [Decimal(str(p)) for p in [
            100, 102, 101, 105, 103, 107, 106, 110, 108, 112,
            111, 115, 113, 117, 116, 120, 118, 122, 121, 125,
            124, 128, 126, 130, 129, 133, 132, 136, 135, 139
        ]]

    def test_momentum_signal_generation(self):
        """모멘텀 신호 생성 테스트"""
        indicators = IndicatorValues(
            symbol=self.symbol,
            timestamp=datetime.now(),
            rsi_14=65.0,  # 상승 모멘텀
            macd=1.5,
            macd_signal=0.5,
            sma_20=120.0
        )
        current_price = Decimal('130')

        signal = self.generator.generate_momentum_signal(
            symbol=self.symbol,
            current_price=current_price,
            indicators=indicators,
            price_history=self.price_history,
            volume=Decimal('2000'),
            volume_sma=1500.0
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.signal_type, SignalType.MOMENTUM)
        self.assertIn(signal.direction, [SignalDirection.LONG, SignalDirection.NEUTRAL])
        self.assertGreater(signal.confidence, 0)
        self.assertIsNotNone(signal.stop_loss)
        self.assertIsNotNone(signal.take_profit)

    def test_breakout_signal_generation(self):
        """돌파 신호 생성 테스트"""
        indicators = IndicatorValues(
            symbol=self.symbol,
            timestamp=datetime.now(),
            bb_upper=135.0,
            rsi_14=55.0,
            atr_14=3.0
        )
        current_price = Decimal('140')  # 돌파

        signal = self.generator.generate_breakout_signal(
            symbol=self.symbol,
            current_price=current_price,
            indicators=indicators,
            price_history=self.price_history
        )

        if signal:  # 돌파 조건이 충족되면
            self.assertEqual(signal.signal_type, SignalType.BREAKOUT)
            self.assertEqual(signal.direction, SignalDirection.LONG)

    def test_mean_reversion_signal_generation(self):
        """평균회귀 신호 생성 테스트"""
        indicators = IndicatorValues(
            symbol=self.symbol,
            timestamp=datetime.now(),
            rsi_14=25.0,  # 과매도
            bb_lower=100.0,
            sma_20=120.0
        )
        current_price = Decimal('110')  # 평균 아래

        signal = self.generator.generate_mean_reversion_signal(
            symbol=self.symbol,
            current_price=current_price,
            indicators=indicators,
            price_history=self.price_history
        )

        if signal:  # 과매도 조건이 충족되면
            self.assertEqual(signal.signal_type, SignalType.MEAN_REVERSION)
            self.assertEqual(signal.direction, SignalDirection.LONG)

    def test_signal_generation_with_all_types(self):
        """전체 신호 유형 생성 테스트"""
        indicators = IndicatorValues(
            symbol=self.symbol,
            timestamp=datetime.now(),
            rsi_14=60.0,
            macd=1.0,
            macd_signal=0.5,
            sma_20=125.0,
            bb_upper=140.0,
            bb_lower=110.0,
            atr_14=2.5
        )
        current_price = Decimal('130')

        signals = self.generator.generate(
            symbol=self.symbol,
            current_price=current_price,
            indicators=indicators,
            price_history=self.price_history,
            volume=Decimal('2000'),
            volume_sma=1500.0
        )

        self.assertIsInstance(signals, list)
        # 신호는 중복 제거되어 반환됨


class TestVerificationPipeline(unittest.TestCase):
    """검증 파이프라인 테스트"""

    def setUp(self):
        self.pipeline = VerificationPipeline()
        self.signal = TradingSignal(
            id="TEST-001",
            symbol="BTC-USDT",
            signal_type=SignalType.MOMENTUM,
            direction=SignalDirection.LONG,
            timestamp=datetime.now(),
            confidence=0.8,
            entry_price=Decimal('50000'),
            stop_loss=Decimal('48500'),
            take_profit=Decimal('53000'),
            position_size=0.1,
            indicators={}
        )
        self.filtered_data = FilteredData(
            symbol="BTC-USDT",
            timestamp=datetime.now(),
            original_price=Decimal('50000'),
            filtered_price=Decimal('50000'),
            confidence=1.0
        )
        self.indicators = IndicatorValues(
            symbol="BTC-USDT",
            timestamp=datetime.now(),
            rsi_14=55.0,
            macd=1.0,
            macd_signal=0.5,
            sma_20=49000.0,
            atr_14=500.0
        )

    def test_data_freshness_step(self):
        """Step 1: 데이터 신선도 검증 테스트"""
        step = self.pipeline._verify_data_freshness(self.signal, self.filtered_data)

        self.assertEqual(step.step_number, 1)
        self.assertEqual(step.name, "Data Freshness")
        self.assertIn(step.status, [VerificationStatus.PASSED, VerificationStatus.WARNING])
        self.assertGreaterEqual(step.score, 0.0)
        self.assertLessEqual(step.score, 1.0)

    def test_price_consistency_step(self):
        """Step 2: 가격 일관성 검증 테스트"""
        exchange_prices = {
            "binance": Decimal('50000'),
            "coinbase": Decimal('50010'),
            "kraken": Decimal('49995')
        }
        step = self.pipeline._verify_price_consistency(
            self.signal, self.filtered_data, exchange_prices
        )

        self.assertEqual(step.step_number, 2)
        self.assertGreaterEqual(step.score, 0.0)

    def test_volatility_step(self):
        """Step 4: 변동성 검증 테스트"""
        step = self.pipeline._verify_volatility(self.signal, self.indicators)

        self.assertEqual(step.step_number, 4)
        self.assertIn(step.status, [VerificationStatus.PASSED, VerificationStatus.WARNING])

    def test_trend_confirmation_step(self):
        """Step 6: 추세 확인 테스트"""
        step = self.pipeline._verify_trend(self.signal, self.indicators)

        self.assertEqual(step.step_number, 6)
        self.assertGreaterEqual(step.score, 0.0)

    def test_momentum_validation_step(self):
        """Step 7: 모멘텀 검증 테스트"""
        step = self.pipeline._verify_momentum(self.signal, self.indicators)

        self.assertEqual(step.step_number, 7)
        self.assertGreaterEqual(step.score, 0.0)

    def test_risk_assessment_step(self):
        """Step 9: 리스크 검증 테스트"""
        step = self.pipeline._verify_risk(self.signal, Decimal('100000'))

        self.assertEqual(step.step_number, 9)
        self.assertIn(step.status, [VerificationStatus.PASSED, VerificationStatus.WARNING])

    def test_full_9step_verification(self):
        """전체 9-step 검증 테스트"""
        result = self.pipeline.execute(
            signal=self.signal,
            filtered_data=self.filtered_data,
            indicators=self.indicators
        )

        self.assertIsInstance(result, VerificationResult)
        self.assertEqual(result.signal_id, self.signal.id)
        self.assertEqual(result.symbol, self.signal.symbol)
        self.assertEqual(len(result.steps), 9)
        self.assertGreaterEqual(result.overall_score, 0.0)
        self.assertLessEqual(result.overall_score, 1.0)
        self.assertIn(result.status, [
            VerificationStatus.PASSED,
            VerificationStatus.WARNING,
            VerificationStatus.FAILED
        ])


class TestVerificationCenter(unittest.TestCase):
    """검증 센터 통합 테스트"""

    def setUp(self):
        self.center = VerificationCenter()

    def test_singleton_pattern(self):
        """싱글톤 패턴 테스트"""
        center1 = get_verification_center()
        center2 = get_verification_center()
        self.assertIs(center1, center2)

    def test_price_history_update(self):
        """가격 히스토리 업데이트 테스트"""
        symbol = "BTC-USDT"
        price = Decimal('50000')

        self.center._update_price_history(symbol, price)

        self.assertIn(symbol, self.center._price_history)
        self.assertEqual(len(self.center._price_history[symbol]), 1)
        self.assertEqual(self.center._price_history[symbol][0], price)

    def test_process_data(self):
        """단일 데이터 처리 테스트"""
        # 먼저 히스토리 축적
        for i in range(25):
            price = Decimal('50000') + Decimal(str(i * 100))
            self.center._update_price_history("BTC-USDT", price)

        signals = self.center.process_data(
            symbol="BTC-USDT",
            price=Decimal('52500'),
            timestamp=datetime.now(),
            volume=Decimal('1000')
        )

        self.assertIsInstance(signals, list)
        # 신호가 생성되었는지 확인 (시장 상황에 따라 0개 이상)

    def test_get_verified_signals(self):
        """검증된 신호 조회 테스트"""
        signals = self.center.get_verified_signals()
        self.assertIsInstance(signals, list)

    def test_get_statistics(self):
        """통계 조회 테스트"""
        stats = self.center.get_statistics()

        self.assertIn('total_signals_generated', stats)
        self.assertIn('total_signals_passed', stats)
        self.assertIn('total_data_processed', stats)
        self.assertIn('monitored_symbols', stats)


class TestIntegration(unittest.TestCase):
    """통합 테스트"""

    def test_end_to_end_signal_flow(self):
        """End-to-end 신호 생성 및 검증 흐름 테스트"""
        center = VerificationCenter()

        # 충분한 히스토리 데이터 생성
        base_price = 50000
        for i in range(30):
            price = Decimal(str(base_price + i * 200))
            volume = Decimal(str(1000 + i * 50))
            center._update_price_history("BTC-USDT", price)
            center._update_volume_history("BTC-USDT", volume)

        # 데이터 처리
        signals = center.process_data(
            symbol="BTC-USDT",
            price=Decimal('56000'),
            timestamp=datetime.now(),
            volume=Decimal('2500')
        )

        # 검증
        self.assertIsInstance(signals, list)

        # 통계 확인
        stats = center.get_statistics()
        self.assertGreaterEqual(stats['total_data_processed'], 1)


if __name__ == '__main__':
    print("=" * 60)
    print("OZ_A2M 제2부서: 정보검증분석센터 테스트")
    print("=" * 60)
    unittest.main(verbosity=2)

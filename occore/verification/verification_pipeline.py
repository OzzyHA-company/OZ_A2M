"""
OZ_A2M 제2부서: 정보검증분석센터 - 검증 파이프라인

이 모듈은 9단계 검증 프로세스를 구현합니다.
각 단계는 특정 검증 기준을 평가하고 결과를 종합하여 최종 검증 점수를 산출합니다.

9-Step Verification Process:
1. Data Freshness (10%)
2. Price Consistency (15%)
3. Volume Validation (10%)
4. Volatility Check (10%)
5. Liquidity Assessment (10%)
6. Trend Confirmation (15%)
7. Momentum Validation (10%)
8. Signal Quality (10%)
9. Risk Assessment (10%)
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any

from .models import (
    TradingSignal,
    FilteredData,
    IndicatorValues,
    VerificationStep,
    VerificationResult,
    VerificationStatus,
    DEFAULT_VERIFICATION_CONFIG
)


logger = logging.getLogger(__name__)


class VerificationPipeline:
    """9단계 검증 파이프라인

    각 단계별로 신호와 데이터를 검증하여 종합 점수를 산출합니다.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """VerificationPipeline 초기화

        Args:
            config: 검증 설정 딕셔너리
        """
        self.config = config or {}
        self._min_score = self.config.get(
            'min_overall_score', DEFAULT_VERIFICATION_CONFIG['min_overall_score']
        )
        self._step_weights = self.config.get(
            'step_weights', DEFAULT_VERIFICATION_CONFIG['step_weights']
        )

        # 개별 단계 설정
        self._freshness_threshold = self.config.get(
            'freshness_threshold_seconds',
            DEFAULT_VERIFICATION_CONFIG['freshness_threshold_seconds']
        )
        self._price_deviation_threshold = self.config.get(
            'price_deviation_threshold',
            DEFAULT_VERIFICATION_CONFIG['price_deviation_threshold']
        )
        self._min_volume_ratio = self.config.get(
            'min_volume_ratio', DEFAULT_VERIFICATION_CONFIG['min_volume_ratio']
        )
        self._max_atr_ratio = self.config.get(
            'max_atr_ratio', DEFAULT_VERIFICATION_CONFIG['max_atr_ratio']
        )
        self._max_spread_pct = self.config.get(
            'max_spread_pct', DEFAULT_VERIFICATION_CONFIG['max_spread_pct']
        )
        self._min_adx = self.config.get(
            'min_adx', DEFAULT_VERIFICATION_CONFIG['min_adx']
        )
        self._rsi_oversold = self.config.get(
            'rsi_oversold', DEFAULT_VERIFICATION_CONFIG['rsi_oversold']
        )
        self._rsi_overbought = self.config.get(
            'rsi_overbought', DEFAULT_VERIFICATION_CONFIG['rsi_overbought']
        )
        self._min_backtest_win_rate = self.config.get(
            'min_backtest_win_rate', DEFAULT_VERIFICATION_CONFIG['min_backtest_win_rate']
        )
        self._max_position_size = self.config.get(
            'max_position_size', DEFAULT_VERIFICATION_CONFIG['max_position_size']
        )

        logger.info("VerificationPipeline initialized")

    def execute(
        self,
        signal: TradingSignal,
        filtered_data: FilteredData,
        indicators: IndicatorValues,
        additional_data: Optional[Dict[str, Any]] = None
    ) -> VerificationResult:
        """전체 9단계 검증 실행

        Args:
            signal: 검증할 트레이딩 신호
            filtered_data: 필터링된 데이터
            indicators: 기술적 지표값들
            additional_data: 추가 검증 데이터

        Returns:
            VerificationResult: 검증 결과
        """
        steps = []
        overall_score = 0.0
        warnings = []
        recommendations = []

        additional_data = additional_data or {}

        # Step 1: Data Freshness
        step1 = self._verify_data_freshness(signal, filtered_data)
        steps.append(step1)
        overall_score += step1.score * self._step_weights[1]
        if step1.status == VerificationStatus.WARNING:
            warnings.append("데이터가 다소 오래되었습니다.")
        elif step1.status == VerificationStatus.FAILED:
            recommendations.append("실시간 데이터 수신을 확인하세요.")

        # Step 2: Price Consistency
        exchange_prices = additional_data.get('exchange_prices', {})
        step2 = self._verify_price_consistency(signal, filtered_data, exchange_prices)
        steps.append(step2)
        overall_score += step2.score * self._step_weights[2]
        if step2.status == VerificationStatus.WARNING:
            warnings.append("거래소 간 가격 편차가 있습니다.")

        # Step 3: Volume Validation
        avg_volume = additional_data.get('avg_volume')
        current_volume = additional_data.get('current_volume')
        step3 = self._verify_volume(signal, current_volume, avg_volume)
        steps.append(step3)
        overall_score += step3.score * self._step_weights[3]
        if step3.status == VerificationStatus.FAILED:
            recommendations.append("거래량이 부족합니다. 유동성을 확인하세요.")

        # Step 4: Volatility Check
        step4 = self._verify_volatility(signal, indicators)
        steps.append(step4)
        overall_score += step4.score * self._step_weights[4]
        if step4.status == VerificationStatus.WARNING:
            warnings.append("변동성이 높습니다.")

        # Step 5: Liquidity Assessment
        spread_pct = additional_data.get('spread_pct')
        depth = additional_data.get('depth')
        step5 = self._verify_liquidity(signal, spread_pct, depth)
        steps.append(step5)
        overall_score += step5.score * self._step_weights[5]
        if step5.status == VerificationStatus.FAILED:
            recommendations.append("유동성이 부족하여 슬리피지가 발생할 수 있습니다.")

        # Step 6: Trend Confirmation
        step6 = self._verify_trend(signal, indicators)
        steps.append(step6)
        overall_score += step6.score * self._step_weights[6]
        if step6.status == VerificationStatus.WARNING:
            warnings.append("추세가 불분명합니다.")

        # Step 7: Momentum Validation
        step7 = self._verify_momentum(signal, indicators)
        steps.append(step7)
        overall_score += step7.score * self._step_weights[7]

        # Step 8: Signal Quality
        backtest_win_rate = additional_data.get('backtest_win_rate')
        step8 = self._verify_signal_quality(signal, backtest_win_rate)
        steps.append(step8)
        overall_score += step8.score * self._step_weights[8]
        if step8.status == VerificationStatus.FAILED:
            recommendations.append("백테스트 결과가 좋지 않습니다. 전략을 재검토하세요.")

        # Step 9: Risk Assessment
        portfolio_value = additional_data.get('portfolio_value')
        step9 = self._verify_risk(signal, portfolio_value)
        steps.append(step9)
        overall_score += step9.score * self._step_weights[9]
        if step9.status == VerificationStatus.WARNING:
            warnings.append("리스크 수준이 높습니다.")

        # 최종 상태 결정
        if overall_score >= 0.75:
            status = VerificationStatus.PASSED
        elif overall_score >= 0.50:
            status = VerificationStatus.WARNING
        else:
            status = VerificationStatus.FAILED

        logger.info(
            f"Verification completed for {signal.symbol}: "
            f"score={overall_score:.2f}, status={status.value}"
        )

        return VerificationResult(
            signal_id=signal.id,
            symbol=signal.symbol,
            timestamp=datetime.now(),
            overall_score=overall_score,
            status=status,
            steps=steps,
            warnings=warnings,
            recommendations=recommendations
        )

    def _verify_data_freshness(
        self,
        signal: TradingSignal,
        filtered_data: FilteredData
    ) -> VerificationStep:
        """Step 1: 데이터 신선도 검증

        Args:
            signal: 트레이딩 신호
            filtered_data: 필터링된 데이터

        Returns:
            VerificationStep: 검증 단계 결과
        """
        now = datetime.now()
        data_age = (now - filtered_data.timestamp).total_seconds()

        if data_age <= self._freshness_threshold:
            score = 1.0 - (data_age / self._freshness_threshold) * 0.2
            status = VerificationStatus.PASSED
            message = f"데이터가 신선합니다 (수신 후 {data_age:.0f}초)"
        elif data_age <= self._freshness_threshold * 2:
            score = 0.6
            status = VerificationStatus.WARNING
            message = f"데이터가 다소 오래되었습니다 ({data_age:.0f}초)"
        else:
            score = 0.0
            status = VerificationStatus.FAILED
            message = f"데이터가 너무 오래되었습니다 ({data_age:.0f}초)"

        return VerificationStep(
            step_number=1,
            name="Data Freshness",
            status=status,
            score=score,
            message=message,
            details={'data_age_seconds': data_age}
        )

    def _verify_price_consistency(
        self,
        signal: TradingSignal,
        filtered_data: FilteredData,
        exchange_prices: Optional[Dict[str, Decimal]] = None
    ) -> VerificationStep:
        """Step 2: 거래소 간 가격 일관성 검증

        Args:
            signal: 트레이딩 신호
            filtered_data: 필터링된 데이터
            exchange_prices: 거래소별 가격

        Returns:
            VerificationStep: 검증 단계 결과
        """
        if not exchange_prices or len(exchange_prices) < 2:
            # 단일 거래소 데이터면 보통 점수 부여
            return VerificationStep(
                step_number=2,
                name="Price Consistency",
                status=VerificationStatus.PASSED,
                score=0.8,
                message="단일 거래소 데이터 (비교 불가)",
                details={'exchange_count': len(exchange_prices) if exchange_prices else 0}
            )

        prices = [float(p) for p in exchange_prices.values()]
        avg_price = sum(prices) / len(prices)
        max_deviation = max(abs(p - avg_price) for p in prices) / avg_price

        if max_deviation <= self._price_deviation_threshold:
            score = 1.0 - (max_deviation / self._price_deviation_threshold) * 0.2
            status = VerificationStatus.PASSED
            message = f"가격 일관성 양호 (편차: {max_deviation*100:.2f}%)"
        elif max_deviation <= self._price_deviation_threshold * 2:
            score = 0.6
            status = VerificationStatus.WARNING
            message = f"가격 편차가 다소 큽니다 ({max_deviation*100:.2f}%)"
        else:
            score = max(0.0, 1.0 - max_deviation * 10)
            status = VerificationStatus.FAILED
            message = f"가격 편차가 심각합니다 ({max_deviation*100:.2f}%)"

        return VerificationStep(
            step_number=2,
            name="Price Consistency",
            status=status,
            score=score,
            message=message,
            details={
                'max_deviation_pct': max_deviation * 100,
                'exchange_count': len(exchange_prices)
            }
        )

    def _verify_volume(
        self,
        signal: TradingSignal,
        current_volume: Optional[Decimal],
        avg_volume: Optional[Decimal]
    ) -> VerificationStep:
        """Step 3: 거래량 검증

        Args:
            signal: 트레이딩 신호
            current_volume: 현재 거래량
            avg_volume: 평균 거래량

        Returns:
            VerificationStep: 검증 단계 결과
        """
        if current_volume is None or avg_volume is None or avg_volume == 0:
            return VerificationStep(
                step_number=3,
                name="Volume Validation",
                status=VerificationStatus.WARNING,
                score=0.5,
                message="거래량 데이터 부족",
                details={}
            )

        volume_ratio = float(current_volume / avg_volume)

        if volume_ratio >= self._min_volume_ratio:
            score = min(1.0, volume_ratio)
            status = VerificationStatus.PASSED
            message = f"거래량 정상 (평균 대비 {volume_ratio*100:.0f}%)"
        elif volume_ratio >= self._min_volume_ratio * 0.5:
            score = 0.5
            status = VerificationStatus.WARNING
            message = f"거래량이 낮습니다 ({volume_ratio*100:.0f}%)"
        else:
            score = max(0.0, volume_ratio * 5)
            status = VerificationStatus.FAILED
            message = f"거래량이 매우 낮습니다 ({volume_ratio*100:.0f}%)"

        return VerificationStep(
            step_number=3,
            name="Volume Validation",
            status=status,
            score=score,
            message=message,
            details={'volume_ratio': volume_ratio}
        )

    def _verify_volatility(
        self,
        signal: TradingSignal,
        indicators: IndicatorValues
    ) -> VerificationStep:
        """Step 4: 변동성 검증

        Args:
            signal: 트레이딩 신호
            indicators: 기술적 지표값들

        Returns:
            VerificationStep: 검증 단계 결과
        """
        if not indicators.atr_14 or not signal.entry_price:
            return VerificationStep(
                step_number=4,
                name="Volatility Check",
                status=VerificationStatus.WARNING,
                score=0.5,
                message="변동성 데이터 부족",
                details={}
            )

        current_price = float(signal.entry_price)
        atr_ratio = indicators.atr_14 / current_price

        if atr_ratio <= self._max_atr_ratio:
            score = 1.0 - (atr_ratio / self._max_atr_ratio) * 0.3
            status = VerificationStatus.PASSED
            message = f"변동성 정상 (ATR: {atr_ratio*100:.2f}%)"
        elif atr_ratio <= self._max_atr_ratio * 2:
            score = 0.6
            status = VerificationStatus.WARNING
            message = f"변동성이 높습니다 (ATR: {atr_ratio*100:.2f}%)"
        else:
            score = max(0.0, 1.0 - atr_ratio * 10)
            status = VerificationStatus.FAILED
            message = f"변동성이 과도합니다 (ATR: {atr_ratio*100:.2f}%)"

        return VerificationStep(
            step_number=4,
            name="Volatility Check",
            status=status,
            score=score,
            message=message,
            details={'atr_ratio': atr_ratio, 'atr_14': indicators.atr_14}
        )

    def _verify_liquidity(
        self,
        signal: TradingSignal,
        spread_pct: Optional[float],
        depth: Optional[Decimal]
    ) -> VerificationStep:
        """Step 5: 유동성 검증

        Args:
            signal: 트레이딩 신호
            spread_pct: 스프레드 비율
            depth: 오더북 깊이

        Returns:
            VerificationStep: 검증 단계 결과
        """
        if spread_pct is None:
            return VerificationStep(
                step_number=5,
                name="Liquidity Assessment",
                status=VerificationStatus.WARNING,
                score=0.5,
                message="유동성 데이터 부족",
                details={}
            )

        if spread_pct <= self._max_spread_pct:
            score = 1.0 - (spread_pct / self._max_spread_pct) * 0.3
            status = VerificationStatus.PASSED
            message = f"유동성 양호 (스프레드: {spread_pct*100:.3f}%)"
        elif spread_pct <= self._max_spread_pct * 3:
            score = 0.6
            status = VerificationStatus.WARNING
            message = f"스프레드가 다소 큽니다 ({spread_pct*100:.3f}%)"
        else:
            score = max(0.0, 1.0 - spread_pct * 100)
            status = VerificationStatus.FAILED
            message = f"유동성이 매우 부족합니다 ({spread_pct*100:.3f}%)"

        return VerificationStep(
            step_number=5,
            name="Liquidity Assessment",
            status=status,
            score=score,
            message=message,
            details={'spread_pct': spread_pct, 'depth': float(depth) if depth else None}
        )

    def _verify_trend(
        self,
        signal: TradingSignal,
        indicators: IndicatorValues
    ) -> VerificationStep:
        """Step 6: 추세 확인

        Args:
            signal: 트레이딩 신호
            indicators: 기술적 지표값들

        Returns:
            VerificationStep: 검증 단계 결과
        """
        score = 0.0
        details = {}

        # 이동평균 정렬 확인
        if indicators.sma_20 and indicators.sma_50:
            ma_aligned = indicators.sma_20 > indicators.sma_50
            details['ma_aligned'] = ma_aligned
            if ma_aligned:
                score += 0.4

        # MACD 확인
        if indicators.macd and indicators.macd_signal:
            macd_bullish = indicators.macd > indicators.macd_signal
            details['macd_bullish'] = macd_bullish
            if macd_bullish:
                score += 0.3

        # 가격 vs EMA
        if indicators.ema_26 and signal.entry_price:
            price_above_ema = float(signal.entry_price) > indicators.ema_26
            details['price_above_ema26'] = price_above_ema
            if price_above_ema:
                score += 0.3

        if score >= 0.7:
            status = VerificationStatus.PASSED
            message = "추세가 명확합니다"
        elif score >= 0.4:
            status = VerificationStatus.WARNING
            message = "추세가 불분명합니다"
        else:
            status = VerificationStatus.FAILED
            message = "추세가 반대 방향입니다"

        return VerificationStep(
            step_number=6,
            name="Trend Confirmation",
            status=status,
            score=score,
            message=message,
            details=details
        )

    def _verify_momentum(
        self,
        signal: TradingSignal,
        indicators: IndicatorValues
    ) -> VerificationStep:
        """Step 7: 모멘텀 검증

        Args:
            signal: 트레이딩 신호
            indicators: 기술적 지표값들

        Returns:
            VerificationStep: 검증 단계 결과
        """
        score = 0.0
        details = {}

        # RSI 검증
        if indicators.rsi_14:
            rsi = indicators.rsi_14
            details['rsi_14'] = rsi

            if signal.direction.value == 'long':
                # 롱: RSI가 과매도에서 벗어나 상승 중
                if self._rsi_oversold < rsi < self._rsi_overbought:
                    score += 0.5
                elif rsi >= self._rsi_overbought:
                    score += 0.2  # 과매수지만 모멘텀 강함
            else:
                # 숏: RSI가 과매수에서 벗어나 하락 중
                if self._rsi_oversold < rsi < self._rsi_overbought:
                    score += 0.5
                elif rsi <= self._rsi_oversold:
                    score += 0.2  # 과매도지만 모멘텀 강함

        # MACD 히스토그램
        if indicators.macd_histogram:
            hist = indicators.macd_histogram
            details['macd_histogram'] = hist

            if signal.direction.value == 'long' and hist > 0:
                score += 0.5
            elif signal.direction.value == 'short' and hist < 0:
                score += 0.5

        if score >= 0.7:
            status = VerificationStatus.PASSED
            message = "모멘텀이 강합니다"
        elif score >= 0.4:
            status = VerificationStatus.WARNING
            message = "모멘텀이 약합니다"
        else:
            status = VerificationStatus.FAILED
            message = "모멘텀이 반대 방향입니다"

        return VerificationStep(
            step_number=7,
            name="Momentum Validation",
            status=status,
            score=score,
            message=message,
            details=details
        )

    def _verify_signal_quality(
        self,
        signal: TradingSignal,
        backtest_win_rate: Optional[float]
    ) -> VerificationStep:
        """Step 8: 신호 품질 검증

        Args:
            signal: 트레이딩 신호
            backtest_win_rate: 백테스트 승률

        Returns:
            VerificationStep: 검증 단계 결과
        """
        score = signal.confidence  # 기본값은 신호 자체의 신뢰도

        # 백테스트 결과가 있으면 반영
        if backtest_win_rate is not None:
            if backtest_win_rate >= self._min_backtest_win_rate:
                score = min(1.0, (score + backtest_win_rate) / 2)
            else:
                score = score * 0.7

        if score >= self._min_backtest_win_rate:
            status = VerificationStatus.PASSED
            message = f"신호 품질 양호 (신뢰도: {score*100:.1f}%)"
        elif score >= 0.5:
            status = VerificationStatus.WARNING
            message = f"신호 품질 보통 ({score*100:.1f}%)"
        else:
            status = VerificationStatus.FAILED
            message = f"신호 품질 낮음 ({score*100:.1f}%)"

        return VerificationStep(
            step_number=8,
            name="Signal Quality",
            status=status,
            score=score,
            message=message,
            details={
                'signal_confidence': signal.confidence,
                'backtest_win_rate': backtest_win_rate
            }
        )

    def _verify_risk(
        self,
        signal: TradingSignal,
        portfolio_value: Optional[Decimal]
    ) -> VerificationStep:
        """Step 9: 리스크 검증

        Args:
            signal: 트레이딩 신호
            portfolio_value: 포트폴리오 가치

        Returns:
            VerificationStep: 검증 단계 결과
        """
        score = 1.0
        details = {}

        # 포지션 크기 검증
        if signal.position_size > self._max_position_size:
            score -= 0.3
            details['position_size_warning'] = True

        # 손절가 설정 확인
        if signal.stop_loss is None:
            score -= 0.2
            details['no_stop_loss'] = True
        else:
            # 손절 범위가 적정한지 확인 (5% 이내 권장)
            if signal.entry_price:
                sl_pct = abs(float(signal.stop_loss - signal.entry_price) / float(signal.entry_price))
                details['stop_loss_pct'] = sl_pct * 100
                if sl_pct > 0.05:
                    score -= 0.1

        # 익절가 설정 확인
        if signal.take_profit is None:
            score -= 0.1
            details['no_take_profit'] = True
        else:
            # RR 비율 확인
            if signal.entry_price and signal.stop_loss:
                risk = abs(float(signal.entry_price - signal.stop_loss))
                reward = abs(float(signal.take_profit - signal.entry_price))
                if risk > 0:
                    rr_ratio = reward / risk
                    details['risk_reward_ratio'] = rr_ratio
                    if rr_ratio >= 2.0:
                        score = min(1.0, score + 0.1)
                    elif rr_ratio < 1.0:
                        score -= 0.2

        score = max(0.0, score)

        if score >= 0.8:
            status = VerificationStatus.PASSED
            message = "리스크 관리가 적절합니다"
        elif score >= 0.5:
            status = VerificationStatus.WARNING
            message = "리스크 수준에 주의가 필요합니다"
        else:
            status = VerificationStatus.FAILED
            message = "리스크 관리가 미흡합니다"

        return VerificationStep(
            step_number=9,
            name="Risk Assessment",
            status=status,
            score=score,
            message=message,
            details=details
        )

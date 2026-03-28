"""
OZ_A2M 제2부서: 정보검증분석센터 - 신호 생성기

이 모듈은 다양한 트레이딩 신호를 생성하는 기능을 제공합니다.
- 모멘텀 신호
- 돌파 신호
- 평균회귀 신호
"""

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Any

from .models import (
    TradingSignal,
    SignalType,
    SignalDirection,
    IndicatorValues,
    DEFAULT_SIGNAL_GENERATOR_CONFIG
)


logger = logging.getLogger(__name__)


class SignalGenerator:
    """트레이딩 신호 생성기

    제공 기능:
    - 모멘텀 신호 생성
    - 돌파 신호 생성
    - 평균회귀 신호 생성
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """SignalGenerator 초기화

        Args:
            config: 생성기 설정 딕셔너리
                - enabled_types: 활성화된 신호 유형 목록
                - min_confidence: 최소 신뢰도
                - max_signals_per_symbol: 심볼당 최대 신호 수
                - signal_expiry_minutes: 신호 만료 시간(분)
        """
        self.config = config or {}
        self._enabled_types = self.config.get(
            'enabled_types', DEFAULT_SIGNAL_GENERATOR_CONFIG['enabled_types']
        )
        self._min_confidence = self.config.get(
            'min_confidence', DEFAULT_SIGNAL_GENERATOR_CONFIG['min_confidence']
        )
        self._max_signals = self.config.get(
            'max_signals_per_symbol',
            DEFAULT_SIGNAL_GENERATOR_CONFIG['max_signals_per_symbol']
        )
        self._expiry_minutes = self.config.get(
            'signal_expiry_minutes',
            DEFAULT_SIGNAL_GENERATOR_CONFIG['signal_expiry_minutes']
        )

        # 생성된 신호 추적
        self._recent_signals: Dict[str, List[TradingSignal]] = {}

        logger.info(f"SignalGenerator initialized with types: {self._enabled_types}")

    def generate(
        self,
        symbol: str,
        current_price: Decimal,
        indicators: IndicatorValues,
        price_history: List[Decimal],
        volume: Optional[Decimal] = None,
        volume_sma: Optional[float] = None
    ) -> List[TradingSignal]:
        """모든 활성화된 신호 유형 생성

        Args:
            symbol: 거래 심볼
            current_price: 현재 가격
            indicators: 기술적 지표값들
            price_history: 가격 히스토리
            volume: 현재 거래량
            volume_sma: 거래량 이동평균

        Returns:
            List[TradingSignal]: 생성된 신호 목록
        """
        signals = []

        # 모멘텀 신호
        if 'momentum' in self._enabled_types:
            signal = self.generate_momentum_signal(
                symbol, current_price, indicators, price_history,
                volume, volume_sma
            )
            if signal:
                signals.append(signal)

        # 돌파 신호
        if 'breakout' in self._enabled_types:
            signal = self.generate_breakout_signal(
                symbol, current_price, indicators, price_history
            )
            if signal:
                signals.append(signal)

        # 평균회귀 신호
        if 'mean_reversion' in self._enabled_types:
            signal = self.generate_mean_reversion_signal(
                symbol, current_price, indicators, price_history
            )
            if signal:
                signals.append(signal)

        # 중복 신호 제거 및 정렬
        signals = self._deduplicate_signals(signals)
        signals = sorted(signals, key=lambda s: s.confidence, reverse=True)

        # 최대 신호 수 제한
        if len(signals) > self._max_signals:
            signals = signals[:self._max_signals]

        # 신호 저장
        self._recent_signals[symbol] = signals

        return signals

    def generate_momentum_signal(
        self,
        symbol: str,
        current_price: Decimal,
        indicators: IndicatorValues,
        price_history: List[Decimal],
        volume: Optional[Decimal] = None,
        volume_sma: Optional[float] = None
    ) -> Optional[TradingSignal]:
        """모멘텀 신호 생성

        진입 조건:
        1. RSI(14) > 50 (상승 모멘텀)
        2. MACD > Signal Line (골든크로스)
        3. 가격 > SMA(20) (단기 추세 상승)
        4. 거래량 > SMA(20) * 1.2 (거래량 급증)

        Args:
            symbol: 거래 심볼
            current_price: 현재 가격
            indicators: 기술적 지표값들
            price_history: 가격 히스토리
            volume: 현재 거래량
            volume_sma: 거래량 이동평균

        Returns:
            Optional[TradingSignal]: 생성된 신호 또는 None
        """
        conditions_met = 0
        total_conditions = 4
        signal_indicators = {}

        # 1. RSI 체크
        if indicators.rsi_14 and indicators.rsi_14 > 50:
            conditions_met += 1
            signal_indicators['rsi_14'] = indicators.rsi_14

        # 2. MACD 체크 (골든크로스)
        if indicators.macd and indicators.macd_signal:
            if indicators.macd > indicators.macd_signal:
                conditions_met += 1
                signal_indicators['macd'] = indicators.macd
                signal_indicators['macd_signal'] = indicators.macd_signal

        # 3. 가격 vs SMA 체크
        if indicators.sma_20:
            current_price_float = float(current_price)
            if current_price_float > indicators.sma_20:
                conditions_met += 1
                signal_indicators['sma_20'] = indicators.sma_20
                signal_indicators['price_above_sma20'] = True

        # 4. 거래량 체크
        if volume and volume_sma:
            volume_float = float(volume)
            if volume_float > volume_sma * 1.2:
                conditions_met += 1
                signal_indicators['volume_ratio'] = volume_float / volume_sma

        confidence = conditions_met / total_conditions

        if confidence >= self._min_confidence:
            # 진입/손절/익절 가격 계산
            entry_price = current_price
            stop_loss = current_price * Decimal('0.97')  # 3% 손절
            take_profit = current_price * Decimal('1.06')  # 6% 익절

            # 모멘텀 강도에 따른 포지션 크기 조정
            position_size = min(confidence * 0.2, 0.15)  # 최대 15%

            return TradingSignal(
                id=self._generate_signal_id(),
                symbol=symbol,
                signal_type=SignalType.MOMENTUM,
                direction=SignalDirection.LONG if confidence > 0.7 else SignalDirection.NEUTRAL,
                timestamp=datetime.now(),
                confidence=confidence,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_size=position_size,
                indicators=signal_indicators,
                expiration=datetime.now() + timedelta(minutes=self._expiry_minutes)
            )

        return None

    def generate_breakout_signal(
        self,
        symbol: str,
        current_price: Decimal,
        indicators: IndicatorValues,
        price_history: List[Decimal],
        lookback: int = 20
    ) -> Optional[TradingSignal]:
        """돌파 신호 생성

        진입 조건:
        1. 현재가 > 최근 N일 최고가 (resistance breakout)
        2. 거래량 > 평균 거래량 * 1.5
        3. ATR < threshold (너무 변동성이 크지 않음)
        4. Bollinger Bands 상단 돌파

        Args:
            symbol: 거래 심볼
            current_price: 현재 가격
            indicators: 기술적 지표값들
            price_history: 가격 히스토리
            lookback: 돌파 확인 기간

        Returns:
            Optional[TradingSignal]: 생성된 신호 또는 None
        """
        if len(price_history) < lookback + 1:
            return None

        current_price_float = float(current_price)
        recent_high = max([float(p) for p in price_history[-(lookback+1):-1]])

        # Breakout 조건: 현재가가 최근 고가보다 1% 이상 높음
        breakout_occurred = current_price_float > recent_high * 1.01

        if not breakout_occurred:
            return None

        conditions_met = 1  # 돌파는 충족
        signal_indicators = {
            'breakout_level': recent_high,
            'breakout_pct': (current_price_float / recent_high - 1) * 100
        }

        # Bollinger Bands 상단 돌파 확인
        if indicators.bb_upper:
            bb_breakout = current_price_float > indicators.bb_upper * 0.995
            if bb_breakout:
                conditions_met += 1
                signal_indicators['bb_upper'] = indicators.bb_upper

        # RSI 체크 (건전한 모멘텀)
        if indicators.rsi_14:
            if 40 < indicators.rsi_14 < 75:
                conditions_met += 1
                signal_indicators['rsi_14'] = indicators.rsi_14

        # ATR 체크 (과도한 변동성 방지)
        if indicators.atr_14:
            atr_ratio = indicators.atr_14 / current_price_float
            if atr_ratio < 0.03:  # 3% 미만
                conditions_met += 1
                signal_indicators['atr_14'] = indicators.atr_14

        total_conditions = 4
        confidence = conditions_met / total_conditions

        if confidence >= self._min_confidence:
            entry_price = current_price
            stop_loss = Decimal(str(recent_high * 0.98))  # 돌파 레벨 아래
            take_profit = current_price * Decimal('1.08')  # 8% 익절

            # 돌파 강도에 따른 포지션 크기
            position_size = min(confidence * 0.25, 0.2)  # 최대 20%

            return TradingSignal(
                id=self._generate_signal_id(),
                symbol=symbol,
                signal_type=SignalType.BREAKOUT,
                direction=SignalDirection.LONG,
                timestamp=datetime.now(),
                confidence=confidence,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_size=position_size,
                indicators=signal_indicators,
                expiration=datetime.now() + timedelta(minutes=self._expiry_minutes)
            )

        return None

    def generate_mean_reversion_signal(
        self,
        symbol: str,
        current_price: Decimal,
        indicators: IndicatorValues,
        price_history: List[Decimal]
    ) -> Optional[TradingSignal]:
        """평균회귀 신호 생성

        LONG 진입 조건:
        1. RSI(14) < 30 (과매도)
        2. 가격 < Bollinger Bands 하단
        3. 가격 < SMA(20) * 0.98 (2% 이상 이탈)

        SHORT 진입 조건:
        1. RSI(14) > 70 (과매수)
        2. 가격 > Bollinger Bands 상단
        3. 가격 > SMA(20) * 1.02

        Args:
            symbol: 거래 심볼
            current_price: 현재 가격
            indicators: 기술적 지표값들
            price_history: 가격 히스토리

        Returns:
            Optional[TradingSignal]: 생성된 신호 또는 None
        """
        current_price_float = float(current_price)

        # LONG 조건 체크
        long_conditions = []
        long_indicators = {}

        if indicators.rsi_14 and indicators.rsi_14 < 35:
            long_conditions.append(True)
            long_indicators['rsi_14'] = indicators.rsi_14
        else:
            long_conditions.append(False)

        if indicators.bb_lower and current_price_float < indicators.bb_lower * 1.01:
            long_conditions.append(True)
            long_indicators['bb_lower'] = indicators.bb_lower
        else:
            long_conditions.append(False)

        if indicators.sma_20 and current_price_float < indicators.sma_20 * 0.98:
            long_conditions.append(True)
            long_indicators['sma_20'] = indicators.sma_20
            long_indicators['price_vs_sma20_pct'] = (current_price_float / indicators.sma_20 - 1) * 100
        else:
            long_conditions.append(False)

        # SHORT 조건 체크
        short_conditions = []
        short_indicators = {}

        if indicators.rsi_14 and indicators.rsi_14 > 65:
            short_conditions.append(True)
            short_indicators['rsi_14'] = indicators.rsi_14
        else:
            short_conditions.append(False)

        if indicators.bb_upper and current_price_float > indicators.bb_upper * 0.99:
            short_conditions.append(True)
            short_indicators['bb_upper'] = indicators.bb_upper
        else:
            short_conditions.append(False)

        if indicators.sma_20 and current_price_float > indicators.sma_20 * 1.02:
            short_conditions.append(True)
            short_indicators['sma_20'] = indicators.sma_20
        else:
            short_conditions.append(False)

        long_score = sum(long_conditions) / len(long_conditions) if long_conditions else 0
        short_score = sum(short_conditions) / len(short_conditions) if short_conditions else 0

        if long_score > self._min_confidence and long_score > short_score:
            entry_price = current_price
            stop_loss = current_price * Decimal('0.95')  # 5% 손절 (평균회귀는 더 넓게)
            take_profit = Decimal(str(indicators.sma_20 or current_price_float * 1.03))

            return TradingSignal(
                id=self._generate_signal_id(),
                symbol=symbol,
                signal_type=SignalType.MEAN_REVERSION,
                direction=SignalDirection.LONG,
                timestamp=datetime.now(),
                confidence=long_score,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_size=min(long_score * 0.15, 0.1),  # 보수적 포지션
                indicators=long_indicators,
                expiration=datetime.now() + timedelta(minutes=self._expiry_minutes),
                metadata={'mean_reversion_target': float(take_profit)}
            )

        elif short_score > self._min_confidence:
            entry_price = current_price
            stop_loss = current_price * Decimal('1.05')  # 5% 손절
            take_profit = Decimal(str(indicators.sma_20 or current_price_float * 0.97))

            return TradingSignal(
                id=self._generate_signal_id(),
                symbol=symbol,
                signal_type=SignalType.MEAN_REVERSION,
                direction=SignalDirection.SHORT,
                timestamp=datetime.now(),
                confidence=short_score,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_size=min(short_score * 0.15, 0.1),
                indicators=short_indicators,
                expiration=datetime.now() + timedelta(minutes=self._expiry_minutes),
                metadata={'mean_reversion_target': float(take_profit)}
            )

        return None

    def _generate_signal_id(self) -> str:
        """고유 신호 ID 생성

        Returns:
            str: UUID 기반 신호 ID
        """
        return f"SIG-{uuid.uuid4().hex[:12].upper()}"

    def _deduplicate_signals(self, signals: List[TradingSignal]) -> List[TradingSignal]:
        """중복 신호 제거

        Args:
            signals: 신호 목록

        Returns:
            List[TradingSignal]: 중복 제거된 신호 목록
        """
        seen_types = set()
        unique_signals = []

        for signal in signals:
            if signal.signal_type not in seen_types:
                seen_types.add(signal.signal_type)
                unique_signals.append(signal)

        return unique_signals

    def get_recent_signals(self, symbol: Optional[str] = None) -> List[TradingSignal]:
        """최근 생성된 신호 조회

        Args:
            symbol: 특정 심볼 (None이면 모든 심볼)

        Returns:
            List[TradingSignal]: 신호 목록
        """
        if symbol:
            return self._recent_signals.get(symbol, [])

        all_signals = []
        for signals in self._recent_signals.values():
            all_signals.extend(signals)
        return all_signals

    def clear_signals(self, symbol: Optional[str] = None) -> None:
        """저장된 신호 초기화

        Args:
            symbol: 특정 심볼 (None이면 모든 심볼)
        """
        if symbol:
            self._recent_signals.pop(symbol, None)
        else:
            self._recent_signals.clear()


# 싱글톤 인스턴스
_signal_generator_instance: Optional[SignalGenerator] = None


def get_signal_generator(config: Optional[Dict[str, Any]] = None) -> SignalGenerator:
    """SignalGenerator 싱글톤 인스턴스 가져오기

    Args:
        config: 생성기 설정 (처음 생성 시에만 사용)

    Returns:
        SignalGenerator: 싱글톤 인스턴스
    """
    global _signal_generator_instance
    if _signal_generator_instance is None:
        _signal_generator_instance = SignalGenerator(config)
    return _signal_generator_instance


def init_signal_generator(config: Optional[Dict[str, Any]] = None) -> SignalGenerator:
    """SignalGenerator 명시적 초기화

    Args:
        config: 생성기 설정

    Returns:
        SignalGenerator: 새로 생성된 인스턴스
    """
    global _signal_generator_instance
    _signal_generator_instance = SignalGenerator(config)
    logger.info("SignalGenerator explicitly initialized")
    return _signal_generator_instance


# timedelta import for signal expiration
from datetime import timedelta

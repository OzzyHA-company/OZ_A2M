"""
OZ_A2M 제2부서: 정보검증분석센터 - 기술적 지표 엔진

이 모듈은 다양한 기술적 지표를 계산하는 기능을 제공합니다.
- 추세 지표: SMA, EMA
- 모멘텀 지표: RSI, MACD
- 변동성 지표: 볼린저 밴드, ATR
- 거래량 지표: OBV
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple

from .models import IndicatorValues


logger = logging.getLogger(__name__)


class IndicatorEngine:
    """기술적 지표 계산 엔진

    제공 기능:
    - SMA (단순이동평균)
    - EMA (지수이동평균)
    - RSI (상대강도지수)
    - MACD (이동평균수렴확산)
    - 볼린저 밴드
    - ATR (평균진폭)
    - OBV (On Balance Volume)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """IndicatorEngine 초기화

        Args:
            config: 엔진 설정 딕셔너리
        """
        self.config = config or {}
        self._cache_enabled = self.config.get('cache_indicators', True)
        self._cache: Dict[str, IndicatorValues] = {}

        logger.info("IndicatorEngine initialized")

    def calculate(
        self,
        symbol: str,
        prices: List[Decimal],
        volumes: Optional[List[Decimal]] = None
    ) -> IndicatorValues:
        """모든 기술적 지표 계산

        Args:
            symbol: 거래 심볼
            prices: 가격 리스트 (종가)
            volumes: 거래량 리스트 (선택사항)

        Returns:
            IndicatorValues: 계산된 모든 지표값
        """
        if not prices or len(prices) < 2:
            logger.warning(f"Insufficient price data for {symbol}")
            return IndicatorValues(symbol=symbol, timestamp=datetime.now())

        # 캐시 확인
        cache_key = f"{symbol}:{len(prices)}"
        if self._cache_enabled and cache_key in self._cache:
            return self._cache[cache_key]

        # 가격을 float로 변환
        price_floats = [float(p) for p in prices]

        # 지표 계산
        indicators = IndicatorValues(
            symbol=symbol,
            timestamp=datetime.now(),
            # Trend indicators
            sma_20=self.calculate_sma(price_floats, period=20),
            sma_50=self.calculate_sma(price_floats, period=50),
            ema_12=self.calculate_ema(price_floats, period=12),
            ema_26=self.calculate_ema(price_floats, period=26),
            # Momentum indicators
            rsi_14=self.calculate_rsi(price_floats, period=14),
            rsi_6=self.calculate_rsi(price_floats, period=6),
            # MACD
            macd=self._calculate_macd_line(price_floats),
            macd_signal=self._calculate_macd_signal(price_floats),
            # Volatility indicators
            bb_upper=self._calculate_bollinger_upper(price_floats),
            bb_middle=self._calculate_bollinger_middle(price_floats),
            bb_lower=self._calculate_bollinger_lower(price_floats),
            atr_14=self.calculate_atr(price_floats, period=14),
        )

        # MACD 히스토그램 계산
        if indicators.macd is not None and indicators.macd_signal is not None:
            indicators.macd_histogram = indicators.macd - indicators.macd_signal

        # 거래량 지표 계산
        if volumes and len(volumes) == len(prices):
            volume_floats = [float(v) for v in volumes]
            indicators.volume_sma = self.calculate_sma(volume_floats, period=20)
            indicators.obv = self.calculate_obv(price_floats, volume_floats)

        # 캐시 저장
        if self._cache_enabled:
            self._cache[cache_key] = indicators

        return indicators

    @staticmethod
    def calculate_sma(values: List[float], period: int) -> Optional[float]:
        """단순이동평균(SMA) 계산

        Args:
            values: 값 리스트
            period: 이동평균 기간

        Returns:
            Optional[float]: SMA 값 또는 None
        """
        if len(values) < period:
            return None

        recent_values = values[-period:]
        return sum(recent_values) / len(recent_values)

    @staticmethod
    def calculate_ema(values: List[float], period: int) -> Optional[float]:
        """지수이동평균(EMA) 계산

        Args:
            values: 값 리스트
            period: 이동평균 기간

        Returns:
            Optional[float]: EMA 값 또는 None
        """
        if len(values) < period:
            return None

        alpha = 2 / (period + 1)
        # 초기값은 SMA 사용
        ema = sum(values[:period]) / period

        for value in values[period:]:
            ema = alpha * value + (1 - alpha) * ema

        return ema

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
        """RSI (상대강도지수) 계산

        Args:
            prices: 가격 리스트
            period: RSI 기간 (기본 14)

        Returns:
            Optional[float]: RSI 값 (0-100) 또는 None
        """
        if len(prices) < period + 1:
            return None

        # 가격 변화 계산
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

        # 상승/하락 분리
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]

        # 초기 평균
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        if avg_loss == 0:
            return 100.0

        # 지수 이동평균 방식으로 RSI 계산
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def _calculate_macd_line(self, prices: List[float]) -> Optional[float]:
        """MACD 라인 계산

        Args:
            prices: 가격 리스트

        Returns:
            Optional[float]: MACD 값 또는 None
        """
        ema_12 = self.calculate_ema(prices, period=12)
        ema_26 = self.calculate_ema(prices, period=26)

        if ema_12 is None or ema_26 is None:
            return None

        return ema_12 - ema_26

    def _calculate_macd_signal(self, prices: List[float]) -> Optional[float]:
        """MACD 시그널 라인 계산

        Args:
            prices: 가격 리스트

        Returns:
            Optional[float]: MACD 시그널 값 또는 None
        """
        # MACD 라인 계산
        macd_values = []
        for i in range(26, len(prices) + 1):
            ema_12 = self.calculate_ema(prices[:i], period=12)
            ema_26 = self.calculate_ema(prices[:i], period=26)
            if ema_12 is not None and ema_26 is not None:
                macd_values.append(ema_12 - ema_26)

        if len(macd_values) < 9:
            return None

        # MACD의 9일 EMA가 시그널 라인
        return self.calculate_ema(macd_values, period=9)

    def _calculate_bollinger_middle(self, prices: List[float]) -> Optional[float]:
        """볼린저 밴드 중간선 (20일 SMA)

        Args:
            prices: 가격 리스트

        Returns:
            Optional[float]: 중간선 값 또는 None
        """
        return self.calculate_sma(prices, period=20)

    def _calculate_bollinger_upper(self, prices: List[float], num_std: float = 2.0) -> Optional[float]:
        """볼린저 밴드 상단

        Args:
            prices: 가격 리스트
            num_std: 표준편차 배수 (기본 2.0)

        Returns:
            Optional[float]: 상단 값 또는 None
        """
        if len(prices) < 20:
            return None

        sma = self.calculate_sma(prices, period=20)
        if sma is None:
            return None

        recent_prices = prices[-20:]
        variance = sum((p - sma) ** 2 for p in recent_prices) / len(recent_prices)
        std_dev = variance ** 0.5

        return sma + (num_std * std_dev)

    def _calculate_bollinger_lower(self, prices: List[float], num_std: float = 2.0) -> Optional[float]:
        """볼린저 밴드 하단

        Args:
            prices: 가격 리스트
            num_std: 표준편차 배수 (기본 2.0)

        Returns:
            Optional[float]: 하단 값 또는 None
        """
        if len(prices) < 20:
            return None

        sma = self.calculate_sma(prices, period=20)
        if sma is None:
            return None

        recent_prices = prices[-20:]
        variance = sum((p - sma) ** 2 for p in recent_prices) / len(recent_prices)
        std_dev = variance ** 0.5

        return sma - (num_std * std_dev)

    @staticmethod
    def calculate_atr(
        prices: List[float],
        period: int = 14,
        highs: Optional[List[float]] = None,
        lows: Optional[List[float]] = None
    ) -> Optional[float]:
        """ATR (Average True Range) 계산

        Args:
            prices: 종가 리스트
            period: ATR 기간 (기본 14)
            highs: 고가 리스트 (선택사항, 없으면 종가 사용)
            lows: 저가 리스트 (선택사항, 없으면 종가 사용)

        Returns:
            Optional[float]: ATR 값 또는 None
        """
        if len(prices) < period + 1:
            return None

        if highs is None:
            highs = prices
        if lows is None:
            lows = prices

        # True Range 계산
        true_ranges = []
        for i in range(1, len(prices)):
            high = highs[i]
            low = lows[i]
            prev_close = prices[i - 1]

            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)

            true_range = max(tr1, tr2, tr3)
            true_ranges.append(true_range)

        if len(true_ranges) < period:
            return None

        # ATR은 True Range의 이동평균
        return sum(true_ranges[-period:]) / period

    @staticmethod
    def calculate_obv(prices: List[float], volumes: List[float]) -> float:
        """OBV (On Balance Volume) 계산

        Args:
            prices: 가격 리스트
            volumes: 거래량 리스트

        Returns:
            float: OBV 값
        """
        if len(prices) != len(volumes) or len(prices) < 2:
            return 0.0

        obv = 0.0
        for i in range(1, len(prices)):
            if prices[i] > prices[i - 1]:
                obv += volumes[i]
            elif prices[i] < prices[i - 1]:
                obv -= volumes[i]
            # 같으면 변화 없음

        return obv

    @staticmethod
    def calculate_adx(
        prices: List[float],
        period: int = 14,
        highs: Optional[List[float]] = None,
        lows: Optional[List[float]] = None
    ) -> Optional[float]:
        """ADX (Average Directional Index) 계산

        Args:
            prices: 종가 리스트
            period: ADX 기간 (기본 14)
            highs: 고가 리스트
            lows: 저가 리스트

        Returns:
            Optional[float]: ADX 값 (0-100) 또는 None
        """
        if len(prices) < period * 2:
            return None

        if highs is None:
            highs = prices
        if lows is None:
            lows = prices

        # +DM과 -DM 계산
        plus_dm = []
        minus_dm = []
        tr_list = []

        for i in range(1, len(prices)):
            up_move = highs[i] - highs[i - 1]
            down_move = lows[i - 1] - lows[i]

            if up_move > down_move and up_move > 0:
                plus_dm.append(up_move)
            else:
                plus_dm.append(0)

            if down_move > up_move and down_move > 0:
                minus_dm.append(down_move)
            else:
                minus_dm.append(0)

            # True Range
            high = highs[i]
            low = lows[i]
            prev_close = prices[i - 1]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)

        if len(plus_dm) < period:
            return None

        # 평균 DM 및 TR
        avg_plus_dm = sum(plus_dm[:period]) / period
        avg_minus_dm = sum(minus_dm[:period]) / period
        avg_tr = sum(tr_list[:period]) / period

        # +DI와 -DI
        plus_di = (avg_plus_dm / avg_tr) * 100 if avg_tr != 0 else 0
        minus_di = (avg_minus_dm / avg_tr) * 100 if avg_tr != 0 else 0

        # DX
        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) != 0 else 0

        # ADX는 DX의 이동평균
        dx_values = [dx]
        for i in range(period, min(len(plus_dm), len(tr_list))):
            avg_plus_dm = (avg_plus_dm * (period - 1) + plus_dm[i]) / period
            avg_minus_dm = (avg_minus_dm * (period - 1) + minus_dm[i]) / period
            avg_tr = (avg_tr * (period - 1) + tr_list[i]) / period

            plus_di = (avg_plus_dm / avg_tr) * 100 if avg_tr != 0 else 0
            minus_di = (avg_minus_dm / avg_tr) * 100 if avg_tr != 0 else 0

            dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) != 0 else 0
            dx_values.append(dx)

        if len(dx_values) < period:
            return sum(dx_values) / len(dx_values)

        return sum(dx_values[-period:]) / period

    def clear_cache(self) -> None:
        """지표 캐시 초기화"""
        self._cache.clear()
        logger.debug("Indicator cache cleared")


# 싱글톤 인스턴스
_indicator_engine_instance: Optional[IndicatorEngine] = None


def get_indicator_engine(config: Optional[Dict[str, Any]] = None) -> IndicatorEngine:
    """IndicatorEngine 싱글톤 인스턴스 가져오기

    Args:
        config: 엔진 설정 (처음 생성 시에만 사용)

    Returns:
        IndicatorEngine: 싱글톤 인스턴스
    """
    global _indicator_engine_instance
    if _indicator_engine_instance is None:
        _indicator_engine_instance = IndicatorEngine(config)
    return _indicator_engine_instance


def init_indicator_engine(config: Optional[Dict[str, Any]] = None) -> IndicatorEngine:
    """IndicatorEngine 명시적 초기화

    Args:
        config: 엔진 설정

    Returns:
        IndicatorEngine: 새로 생성된 인스턴스
    """
    global _indicator_engine_instance
    _indicator_engine_instance = IndicatorEngine(config)
    logger.info("IndicatorEngine explicitly initialized")
    return _indicator_engine_instance

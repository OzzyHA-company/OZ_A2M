"""
OZ_A2M 제2부서: 정보검증분석센터 - 노이즈 필터

이 모듈은 시장 데이터에서 노이즈를 필터링하는 기능을 제공합니다.
- Z-score, IQR 기반 이상치 탐지
- Kalman 필터, EMA, 중간값 필터를 통한 데이터 스묘딩
"""

import logging
from decimal import Decimal
from typing import Dict, List, Optional, Any

from .models import FilteredData, DEFAULT_NOISE_FILTER_CONFIG


logger = logging.getLogger(__name__)


class NoiseFilter:
    """데이터 노이즈 필터링 클래스

    제공 기능:
    - Z-score 기반 이상치 탐지
    - IQR (Interquartile Range) 기반 이상치 탐지
    - Kalman 필터 스묘딩
    - EMA (지수이동평균) 스묘딩
    - 중간값 필터
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """NoiseFilter 초기화

        Args:
            config: 필터 설정 딕셔너리
                - outlier_method: 'zscore', 'iqr'
                - outlier_threshold: Z-score 임계값 (기본 3.0)
                - smoothing_method: 'ema', 'kalman', 'median', 'none'
                - ema_span: EMA 기간 (기본 10)
                - kalman_process_variance: 칼만 필터 프로세스 분산
                - kalman_measurement_variance: 칼만 필터 측정 분산
        """
        self.config = config or {}
        self._outlier_method = self.config.get(
            'outlier_method', DEFAULT_NOISE_FILTER_CONFIG['outlier_method']
        )
        self._outlier_threshold = self.config.get(
            'outlier_threshold', DEFAULT_NOISE_FILTER_CONFIG['outlier_threshold']
        )
        self._smoothing_method = self.config.get(
            'smoothing_method', DEFAULT_NOISE_FILTER_CONFIG['smoothing_method']
        )
        self._ema_span = self.config.get(
            'ema_span', DEFAULT_NOISE_FILTER_CONFIG['ema_span']
        )
        self._kalman_process_variance = self.config.get(
            'kalman_process_variance',
            DEFAULT_NOISE_FILTER_CONFIG['kalman_process_variance']
        )
        self._kalman_measurement_variance = self.config.get(
            'kalman_measurement_variance',
            DEFAULT_NOISE_FILTER_CONFIG['kalman_measurement_variance']
        )

        logger.info(f"NoiseFilter initialized with method: {self._smoothing_method}")

    def filter_price_data(
        self,
        symbol: str,
        price: Decimal,
        timestamp: Any,
        price_history: Optional[List[Decimal]] = None
    ) -> FilteredData:
        """가격 데이터 필터링

        Args:
            symbol: 거래 심볼
            price: 현재 가격
            timestamp: 타임스탬프
            price_history: 이전 가격 히스토리 (스묘딩에 사용)

        Returns:
            FilteredData: 필터링 결과
        """
        from datetime import datetime

        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except ValueError:
                timestamp = datetime.now()
        elif not isinstance(timestamp, datetime):
            timestamp = datetime.now()

        original_price = price
        is_outlier = False
        confidence = 1.0
        smoothing_applied = "none"

        # 이상치 탐지 (히스토리가 충분한 경우)
        if price_history and len(price_history) >= 5:
            if self._outlier_method == 'zscore':
                is_outlier = self._is_outlier_zscore(price, price_history)
            elif self._outlier_method == 'iqr':
                is_outlier = self._is_outlier_iqr(price, price_history)

            if is_outlier:
                confidence = 0.5
                logger.warning(f"Outlier detected for {symbol}: {price}")

        # 스묘딩 적용
        filtered_price = price
        if price_history and len(price_history) >= 3:
            if self._smoothing_method == 'ema':
                filtered_price = self._apply_ema(price, price_history)
                smoothing_applied = "ema"
            elif self._smoothing_method == 'kalman':
                filtered_price = self._apply_kalman(price, price_history)
                smoothing_applied = "kalman"
            elif self._smoothing_method == 'median':
                filtered_price = self._apply_median_filter(price, price_history)
                smoothing_applied = "median"

        # 신뢰도 조정 (스묘딩 적용 시 증가)
        if smoothing_applied != "none" and not is_outlier:
            confidence = min(1.0, confidence + 0.1)

        return FilteredData(
            symbol=symbol,
            timestamp=timestamp,
            original_price=original_price,
            filtered_price=filtered_price,
            confidence=confidence,
            is_outlier=is_outlier,
            smoothing_applied=smoothing_applied,
            metadata={
                'outlier_method': self._outlier_method,
                'smoothing_method': self._smoothing_method
            }
        )

    def _is_outlier_zscore(self, price: Decimal, price_history: List[Decimal]) -> bool:
        """Z-score 기반 이상치 확인

        Args:
            price: 확인할 가격
            price_history: 가격 히스토리

        Returns:
            bool: 이상치 여부
        """
        if len(price_history) < 5:
            return False

        values = [float(p) for p in price_history[-20:]]  # 최근 20개
        if not values:
            return False

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std_dev = variance ** 0.5

        if std_dev == 0:
            return False

        current_value = float(price)
        z_score = abs(current_value - mean) / std_dev

        return z_score > self._outlier_threshold

    def _is_outlier_iqr(self, price: Decimal, price_history: List[Decimal]) -> bool:
        """IQR 기반 이상치 확인

        Args:
            price: 확인할 가격
            price_history: 가격 히스토리

        Returns:
            bool: 이상치 여부
        """
        if len(price_history) < 5:
            return False

        values = sorted([float(p) for p in price_history[-20:]])
        n = len(values)

        if n < 4:
            return False

        q1_idx = n // 4
        q3_idx = 3 * n // 4
        q1 = values[q1_idx]
        q3 = values[q3_idx]
        iqr = q3 - q1

        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr

        current_value = float(price)
        return current_value < lower_bound or current_value > upper_bound

    def detect_outliers_zscore(
        self,
        prices: List[Decimal],
        threshold: Optional[float] = None
    ) -> List[int]:
        """Z-score 기반 이상치 인덱스 탐지

        Args:
            prices: 가격 리스트
            threshold: Z-score 임계값 (기본값: 설정값 사용)

        Returns:
            List[int]: 이상치 인덱스 리스트
        """
        if not prices or len(prices) < 2:
            return []

        threshold = threshold or self._outlier_threshold
        values = [float(p) for p in prices]

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std_dev = variance ** 0.5

        if std_dev == 0:
            return []

        outliers = []
        for i, value in enumerate(values):
            z_score = abs(value - mean) / std_dev
            if z_score > threshold:
                outliers.append(i)

        return outliers

    def detect_outliers_iqr(self, prices: List[Decimal]) -> List[int]:
        """IQR 기반 이상치 인덱스 탐지

        Args:
            prices: 가격 리스트

        Returns:
            List[int]: 이상치 인덱스 리스트
        """
        if not prices or len(prices) < 4:
            return []

        values = sorted([float(p) for p in prices])
        n = len(values)

        q1_idx = n // 4
        q3_idx = 3 * n // 4
        q1 = values[q1_idx]
        q3 = values[q3_idx]
        iqr = q3 - q1

        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr

        outliers = []
        for i, price in enumerate(prices):
            val = float(price)
            if val < lower_bound or val > upper_bound:
                outliers.append(i)

        return outliers

    def _apply_ema(self, current_price: Decimal, price_history: List[Decimal]) -> Decimal:
        """EMA 스묘딩 적용

        Args:
            current_price: 현재 가격
            price_history: 가격 히스토리

        Returns:
            Decimal: 스묘딩된 가격
        """
        if not price_history:
            return current_price

        alpha = 2 / (self._ema_span + 1)
        ema = float(price_history[-1])

        # 히스토리를 순회하며 EMA 계산
        for price in list(price_history[-self._ema_span:]) + [current_price]:
            ema = alpha * float(price) + (1 - alpha) * ema

        return Decimal(str(ema))

    def _apply_kalman(self, current_price: Decimal, price_history: List[Decimal]) -> Decimal:
        """Kalman 필터 스묘딩 적용

        Args:
            current_price: 현재 가격
            price_history: 가격 히스토리

        Returns:
            Decimal: 스묘딩된 가격
        """
        if not price_history:
            return current_price

        # 마지막으로 계산된 상태 사용 또는 초기화
        estimate = float(price_history[-1])
        error_estimate = 1.0

        # 최근 히스토리로 필터 업데이트
        for price in price_history[-10:]:
            measurement = float(price)

            # Prediction
            prediction_error = error_estimate + self._kalman_process_variance

            # Update
            kalman_gain = prediction_error / (
                prediction_error + self._kalman_measurement_variance
            )
            estimate = estimate + kalman_gain * (measurement - estimate)
            error_estimate = (1 - kalman_gain) * prediction_error

        # 현재 가격으로 최종 업데이트
        measurement = float(current_price)
        prediction_error = error_estimate + self._kalman_process_variance
        kalman_gain = prediction_error / (
            prediction_error + self._kalman_measurement_variance
        )
        estimate = estimate + kalman_gain * (measurement - estimate)

        return Decimal(str(estimate))

    def _apply_median_filter(
        self,
        current_price: Decimal,
        price_history: List[Decimal]
    ) -> Decimal:
        """중간값 필터 적용

        Args:
            current_price: 현재 가격
            price_history: 가격 히스토리

        Returns:
            Decimal: 필터링된 가격
        """
        window = 5
        recent_prices = list(price_history[-(window-1):]) + [current_price]

        if len(recent_prices) < 3:
            return current_price

        sorted_prices = sorted(recent_prices)
        median = sorted_prices[len(sorted_prices) // 2]

        return median

    def kalman_filter(
        self,
        prices: List[Decimal],
        process_variance: Optional[float] = None,
        measurement_variance: Optional[float] = None
    ) -> List[Decimal]:
        """Kalman 필터를 사용한 가격 스묘딩

        Args:
            prices: 가격 리스트
            process_variance: 프로세스 분산
            measurement_variance: 측정 분산

        Returns:
            List[Decimal]: 스묘딩된 가격 리스트
        """
        if not prices:
            return []

        process_variance = process_variance or self._kalman_process_variance
        measurement_variance = measurement_variance or self._kalman_measurement_variance

        filtered = []
        estimate = float(prices[0])
        error_estimate = 1.0

        for price in prices:
            measurement = float(price)

            # Prediction
            prediction_error = error_estimate + process_variance

            # Update
            kalman_gain = prediction_error / (prediction_error + measurement_variance)
            estimate = estimate + kalman_gain * (measurement - estimate)
            error_estimate = (1 - kalman_gain) * prediction_error

            filtered.append(Decimal(str(estimate)))

        return filtered

    def ema_smoothing(self, prices: List[Decimal], span: Optional[int] = None) -> List[Decimal]:
        """지수이동평균 스묘딩

        Args:
            prices: 가격 리스트
            span: EMA 기간

        Returns:
            List[Decimal]: 스묘딩된 가격 리스트
        """
        if not prices:
            return []

        span = span or self._ema_span
        if span <= 0:
            return prices

        alpha = Decimal(str(2 / (span + 1)))
        one_minus_alpha = Decimal('1') - alpha
        smoothed = [prices[0]]

        for price in prices[1:]:
            smoothed_value = alpha * price + one_minus_alpha * smoothed[-1]
            smoothed.append(smoothed_value)

        return smoothed

    def median_filter(self, prices: List[Decimal], window: int = 5) -> List[Decimal]:
        """중간값 필터 (spike 제거에 효과적)

        Args:
            prices: 가격 리스트
            window: 필터 윈도우 크기

        Returns:
            List[Decimal]: 필터링된 가격 리스트
        """
        if len(prices) < window:
            return prices

        filtered = []
        half_window = window // 2

        for i in range(len(prices)):
            start = max(0, i - half_window)
            end = min(len(prices), i + half_window + 1)
            window_values = sorted(prices[start:end])
            median = window_values[len(window_values) // 2]
            filtered.append(median)

        return filtered


# 싱글톤 인스턴스
_noise_filter_instance: Optional[NoiseFilter] = None


def get_noise_filter(config: Optional[Dict[str, Any]] = None) -> NoiseFilter:
    """NoiseFilter 싱글톤 인스턴스 가져오기

    Args:
        config: 필터 설정 (처음 생성 시에만 사용)

    Returns:
        NoiseFilter: 싱글톤 인스턴스
    """
    global _noise_filter_instance
    if _noise_filter_instance is None:
        _noise_filter_instance = NoiseFilter(config)
    return _noise_filter_instance


def init_noise_filter(config: Optional[Dict[str, Any]] = None) -> NoiseFilter:
    """NoiseFilter 명시적 초기화

    Args:
        config: 필터 설정

    Returns:
        NoiseFilter: 새로 생성된 인스턴스
    """
    global _noise_filter_instance
    _noise_filter_instance = NoiseFilter(config)
    logger.info("NoiseFilter explicitly initialized")
    return _noise_filter_instance

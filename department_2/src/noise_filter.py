"""
Noise Filter

RSI/볼린저밴드 기반 이상 신호 제거
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime

import numpy as np

logger = logging.getLogger(__name__)


class SignalQuality(Enum):
    """신호 품질 등급"""
    EXCELLENT = "excellent"      # 우수
    GOOD = "good"               # 양호
    MODERATE = "moderate"       # 보통
    POOR = "poor"               # 불량
    REJECT = "reject"           # 거부


@dataclass
class FilterResult:
    """필터링 결과"""
    is_valid: bool
    quality: SignalQuality
    confidence: float          # 0.0 ~ 1.0
    rejection_reason: Optional[str] = None
    indicators: Optional[Dict[str, Any]] = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()


class NoiseFilter:
    """
    노이즈 필터

    기술적 지표를 사용하여 신호 품질 평가
    - RSI: 과매수/과매도 감지
    - 볼린저 밴드: 변동성 기반 필터링
    - 거래량: 유동성 확인
    """

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        bb_period: int = 20,
        bb_std: float = 2.0,
        min_volume: float = 1000.0,
    ):
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.min_volume = min_volume

        logger.info(f"NoiseFilter initialized: RSI({rsi_period}), BB({bb_period})")

    def calculate_rsi(self, prices: List[float]) -> float:
        """
        RSI (Relative Strength Index) 계산

        Args:
            prices: 가격 목록

        Returns:
            RSI 값 (0~100)
        """
        if len(prices) < self.rsi_period + 1:
            return 50.0  # 중립값

        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-self.rsi_period:])
        avg_loss = np.mean(losses[-self.rsi_period:])

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

        return rsi

    def calculate_bollinger_bands(
        self,
        prices: List[float]
    ) -> Dict[str, float]:
        """
        볼린저 밴드 계산

        Args:
            prices: 가격 목록

        Returns:
            upper, middle, lower 밴드 값
        """
        if len(prices) < self.bb_period:
            mid = np.mean(prices) if prices else 0.0
            return {"upper": mid * 1.02, "middle": mid, "lower": mid * 0.98}

        recent_prices = prices[-self.bb_period:]
        sma = np.mean(recent_prices)
        std = np.std(recent_prices)

        return {
            "upper": sma + (self.bb_std * std),
            "middle": sma,
            "lower": sma - (self.bb_std * std),
        }

    def filter_signal(
        self,
        signal: Dict[str, Any],
        price_history: List[float],
        current_volume: float = 0.0,
    ) -> FilterResult:
        """
        신호 필터링

        Args:
            signal: 원본 신호
            price_history: 가격 히스토리
            current_volume: 현재 거래량

        Returns:
            FilterResult: 필터링 결과
        """
        indicators = {}
        rejection_reasons = []

        # 1. RSI 검사
        rsi = self.calculate_rsi(price_history)
        indicators["rsi"] = rsi

        action = signal.get("action", "").upper()

        # 매수 신호 + 과매수 = 위험
        if action == "BUY" and rsi > self.rsi_overbought:
            rejection_reasons.append(f"RSI 과매수: {rsi:.1f}")

        # 매도 신호 + 과매도 = 위험
        if action == "SELL" and rsi < self.rsi_oversold:
            rejection_reasons.append(f"RSI 과매도: {rsi:.1f}")

        # 2. 볼린저 밴드 검사
        bb = self.calculate_bollinger_bands(price_history)
        indicators["bollinger_bands"] = bb

        current_price = signal.get("price", price_history[-1] if price_history else 0)

        # 가격이 밴드 외부에 있으면 경고
        if current_price > bb["upper"]:
            indicators["bb_position"] = "above_upper"
            if action == "BUY":
                rejection_reasons.append("가격이 상단 밴드 이상")
        elif current_price < bb["lower"]:
            indicators["bb_position"] = "below_lower"
            if action == "SELL":
                rejection_reasons.append("가격이 하단 밴드 이하")
        else:
            indicators["bb_position"] = "within bands"

        # 3. 거래량 검사
        indicators["volume"] = current_volume
        if current_volume < self.min_volume:
            rejection_reasons.append(f"거래량 부족: {current_volume:.0f}")

        # 4. 품질 등급 결정
        if rejection_reasons:
            quality = SignalQuality.REJECT
            confidence = 0.0
            is_valid = False
        else:
            # RSI 기반 품질 평가
            rsi_quality = 1.0 - abs(rsi - 50) / 50  # 50에 가까울수록 좋음

            # 볼린저 밴드 기반 품질
            bb_range = bb["upper"] - bb["lower"]
            if bb_range > 0:
                bb_position = (current_price - bb["lower"]) / bb_range
                bb_quality = 1.0 - abs(bb_position - 0.5) * 2  # 중앙에 가까울수록 좋음
            else:
                bb_quality = 0.5

            # 종합 품질
            confidence = (rsi_quality * 0.4 + bb_quality * 0.4 +
                         min(current_volume / (self.min_volume * 10), 1.0) * 0.2)

            if confidence > 0.8:
                quality = SignalQuality.EXCELLENT
            elif confidence > 0.6:
                quality = SignalQuality.GOOD
            elif confidence > 0.4:
                quality = SignalQuality.MODERATE
            else:
                quality = SignalQuality.POOR

            is_valid = quality in [SignalQuality.EXCELLENT, SignalQuality.GOOD]

        return FilterResult(
            is_valid=is_valid,
            quality=quality,
            confidence=confidence,
            rejection_reason="; ".join(rejection_reasons) if rejection_reasons else None,
            indicators=indicators,
        )

    def batch_filter(
        self,
        signals: List[Dict[str, Any]],
        price_histories: Dict[str, List[float]],
        volumes: Dict[str, float],
    ) -> List[FilterResult]:
        """
        다중 신호 배치 필터링

        Args:
            signals: 신호 목록
            price_histories: 심볼별 가격 히스토리
            volumes: 심볼별 거래량

        Returns:
            필터링 결과 목록
        """
        results = []

        for signal in signals:
            symbol = signal.get("symbol", "")
            prices = price_histories.get(symbol, [])
            volume = volumes.get(symbol, 0.0)

            result = self.filter_signal(signal, prices, volume)
            results.append(result)

        return results


class SignalVerifier:
    """
    신호 검증기

    추가 검증 로직:
    - 중복 신호 감지
    - 시간 기반 쿨다운
    - 신호 소스 검증
    """

    def __init__(
        self,
        cooldown_seconds: float = 60.0,
        max_duplicate_age_seconds: float = 300.0,
    ):
        self.cooldown_seconds = cooldown_seconds
        self.max_duplicate_age_seconds = max_duplicate_age_seconds
        self._recent_signals: Dict[str, datetime] = {}
        self._signal_history: List[Dict[str, Any]] = []
        self._max_history = 1000

        logger.info(f"SignalVerifier initialized: cooldown={cooldown_seconds}s")

    def verify_signal(self, signal: Dict[str, Any]) -> FilterResult:
        """
        신호 검증

        Args:
            signal: 검증할 신호

        Returns:
            FilterResult: 검증 결과
        """
        signal_id = signal.get("signal_id", "")
        symbol = signal.get("symbol", "")
        action = signal.get("action", "")

        # 1. 중복 검사
        cache_key = f"{symbol}:{action}"
        now = datetime.utcnow()

        if cache_key in self._recent_signals:
            last_time = self._recent_signals[cache_key]
            elapsed = (now - last_time).total_seconds()

            if elapsed < self.cooldown_seconds:
                return FilterResult(
                    is_valid=False,
                    quality=SignalQuality.REJECT,
                    confidence=0.0,
                    rejection_reason=f"쿨다운 중: {elapsed:.0f}s/{self.cooldown_seconds}s",
                )

        # 2. 소스 검증
        source = signal.get("source", "")
        if not source:
            return FilterResult(
                is_valid=False,
                quality=SignalQuality.REJECT,
                confidence=0.0,
                rejection_reason="신호 소스 없음",
            )

        # 3. 가격 검증
        price = signal.get("price", 0)
        if price <= 0:
            return FilterResult(
                is_valid=False,
                quality=SignalQuality.REJECT,
                confidence=0.0,
                rejection_reason="유효하지 않은 가격",
            )

        # 검증 통과 - 히스토리에 추가
        self._recent_signals[cache_key] = now
        self._signal_history.append({
            "signal_id": signal_id,
            "symbol": symbol,
            "action": action,
            "timestamp": now.isoformat(),
        })

        # 히스토리 크기 관리
        if len(self._signal_history) > self._max_history:
            self._signal_history = self._signal_history[-self._max_history:]

        return FilterResult(
            is_valid=True,
            quality=SignalQuality.GOOD,
            confidence=0.9,
        )

    def get_stats(self) -> Dict[str, Any]:
        """검증 통계 조회"""
        return {
            "recent_signals_count": len(self._recent_signals),
            "history_count": len(self._signal_history),
            "cooldown_seconds": self.cooldown_seconds,
        }

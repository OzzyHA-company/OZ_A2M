"""
OZ_A2M 제2부서: 정보검증분석센터 (Verification & Analysis Center)

기능:
- 데이터 노이즈 필터링 (Z-score, IQR, Kalman, EMA, Median)
- 매매 신호 생성 (모멘텀, 돌파, 평균회귀)
- 9-step 검증 프로세스
- 기술적 지표 계산 (RSI, MACD, 볼린저밴드, ATR, OBV)

Usage:
    from occore.verification import (
        VerificationCenter,
        SignalGenerator,
        NoiseFilter,
        IndicatorEngine,
        VerificationPipeline,
        TradingSignal,
        SignalType,
        SignalDirection,
        VerificationStatus,
        FilteredData,
        VerificationResult,
        IndicatorValues,
    )

    # 싱글톤 인스턴스 사용
    center = get_verification_center()
    signals = center.process_data(
        symbol="BTC-USDT",
        price=Decimal("50000"),
        timestamp=datetime.now(),
        volume=Decimal("1000")
    )
"""

from .models import (
    SignalType,
    SignalDirection,
    VerificationStatus,
    FilteredData,
    TradingSignal,
    VerificationStep,
    VerificationResult,
    IndicatorValues,
    SignalPerformance,
    DEFAULT_VERIFICATION_CONFIG,
    DEFAULT_NOISE_FILTER_CONFIG,
    DEFAULT_SIGNAL_GENERATOR_CONFIG,
    DEFAULT_STEP_WEIGHTS,
)

from .noise_filter import (
    NoiseFilter,
    get_noise_filter,
    init_noise_filter,
)

from .indicators import (
    IndicatorEngine,
    get_indicator_engine,
    init_indicator_engine,
)

from .signal_generator import (
    SignalGenerator,
    get_signal_generator,
    init_signal_generator,
)

from .verification_pipeline import (
    VerificationPipeline,
)

from .reality_check import (
    VerificationCenter,
    get_verification_center,
    init_verification_center,
)

__version__ = "1.0.0"

__all__ = [
    # Enums
    "SignalType",
    "SignalDirection",
    "VerificationStatus",
    # Dataclasses
    "FilteredData",
    "TradingSignal",
    "VerificationStep",
    "VerificationResult",
    "IndicatorValues",
    "SignalPerformance",
    # Classes
    "NoiseFilter",
    "IndicatorEngine",
    "SignalGenerator",
    "VerificationPipeline",
    "VerificationCenter",
    # Singleton getters
    "get_noise_filter",
    "init_noise_filter",
    "get_indicator_engine",
    "init_indicator_engine",
    "get_signal_generator",
    "init_signal_generator",
    "get_verification_center",
    "init_verification_center",
    # Config defaults
    "DEFAULT_VERIFICATION_CONFIG",
    "DEFAULT_NOISE_FILTER_CONFIG",
    "DEFAULT_SIGNAL_GENERATOR_CONFIG",
    "DEFAULT_STEP_WEIGHTS",
    # Version
    "__version__",
]

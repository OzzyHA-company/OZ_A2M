"""
OZ_A2M 아키텍처 기반 트레이딩 시스템

부서별 모듈:
- 제1부서: 관제탑센터 (control_tower)
- 제2부서: 정보검증분석센터 (verification)
- 제3부서: 보안팀 (security)
- 제4부서: 유지보수관리센터 (devops)
- 제5부서: 일일 성과분석팀 (pnl)
- 제6부서: 연구개발팀 (rnd)
- 외부 탐색팀: 데이터 수집 (data_sources)
"""

from .security import (
    Vault, AccessControl, PermissionLevel,
    AuditLogger, ThreatMonitor
)
from .data_sources import (
    OpenBBAdapter, NewsCollector, SentimentAnalyzer, DataRouter
)
from .verification import (
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
    get_verification_center,
    get_signal_generator,
    get_noise_filter,
    get_indicator_engine,
)

__all__ = [
    # 제2부서 정보검증분석센터
    "VerificationCenter",
    "SignalGenerator",
    "NoiseFilter",
    "IndicatorEngine",
    "VerificationPipeline",
    "TradingSignal",
    "SignalType",
    "SignalDirection",
    "VerificationStatus",
    "FilteredData",
    "VerificationResult",
    "IndicatorValues",
    "get_verification_center",
    "get_signal_generator",
    "get_noise_filter",
    "get_indicator_engine",
    # 제3부서 보안팀
    "Vault",
    "AccessControl",
    "PermissionLevel",
    "AuditLogger",
    "ThreatMonitor",
    # 외부 탐색팀 데이터 소스
    "OpenBBAdapter",
    "NewsCollector",
    "SentimentAnalyzer",
    "DataRouter",
]

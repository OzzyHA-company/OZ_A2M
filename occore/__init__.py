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
    AuditLogger, ElasticsearchAuditAdapter, ThreatMonitor,
    init_audit_logger, init_elasticsearch_adapter,
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
from .devops import (
    HealthChecker,
    NetdataAdapter,
    Watchdog,
    Diagnoser,
    Healer,
    RepairLog,
    HealthStatus,
    DiagnosisType,
    SeverityLevel,
    RepairType,
    RepairStatus,
    HealthCheckResult,
    DiagnosisResult,
    HealResult,
    RepairRecord,
    get_health_checker,
    get_netdata_adapter,
    get_watchdog,
    get_diagnoser,
    get_healer,
    init_health_checker,
    init_netdata_adapter,
    init_watchdog,
    DEFAULT_HEALTH_CHECK_CONFIG,
    DEFAULT_WATCHDOG_CONFIG,
)
from .pnl import (
    ProfitCalculator,
    PerformanceAnalyzer,
    ReportGenerator,
    TradeRecord,
    DailyPnL,
    PerformanceMetrics,
    PnLType,
    TradeStatus,
    PositionSide,
    get_calculator,
    get_analyzer,
    get_report_generator,
    init_calculator,
    init_analyzer,
    init_report_generator,
    DEFAULT_PNL_CONFIG,
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
    "ElasticsearchAuditAdapter",
    "ThreatMonitor",
    "init_audit_logger",
    "init_elasticsearch_adapter",
    # 제4부서 유지보수관리센터
    "HealthChecker",
    "NetdataAdapter",
    "Watchdog",
    "Diagnoser",
    "Healer",
    "RepairLog",
    "HealthStatus",
    "DiagnosisType",
    "SeverityLevel",
    "RepairType",
    "RepairStatus",
    "HealthCheckResult",
    "DiagnosisResult",
    "HealResult",
    "RepairRecord",
    "get_health_checker",
    "get_netdata_adapter",
    "get_watchdog",
    "get_diagnoser",
    "get_healer",
    "init_health_checker",
    "init_netdata_adapter",
    "init_watchdog",
    "DEFAULT_HEALTH_CHECK_CONFIG",
    "DEFAULT_WATCHDOG_CONFIG",
    # 제5부서 일일 성과분석팀
    "ProfitCalculator",
    "PerformanceAnalyzer",
    "ReportGenerator",
    "TradeRecord",
    "DailyPnL",
    "PerformanceMetrics",
    "PnLType",
    "TradeStatus",
    "PositionSide",
    "get_calculator",
    "get_analyzer",
    "get_report_generator",
    "init_calculator",
    "init_analyzer",
    "init_report_generator",
    "DEFAULT_PNL_CONFIG",
    # 외부 탐색팀 데이터 소스
    "OpenBBAdapter",
    "NewsCollector",
    "SentimentAnalyzer",
    "DataRouter",
]

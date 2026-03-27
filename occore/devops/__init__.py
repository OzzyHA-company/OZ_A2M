"""
OZ_A2M 제4부서: 유지보수관리센터 (DevOps & Maintenance Center)

시스템 모니터링, 헬스 체크, 와치독, 자동 복구, 자가 진단/치유 관리
Netdata 실시간 모니터링 통합 지원

주요 기능:
- 시스템 리소스 모니터링 (CPU, 메모리, 디스크, 네트워크) [유지]
- Netdata 실시간 모니터링 통합 [유지]
- 서비스 헬스 체크 (거래소 API, 데이터베이스) [유지]
- 프로세스 와치독 및 자동 복구 [유지]
- 자가 진단 (Self-Diagnosis) [보수]
- 자가 치유 (Self-Healing) [보수]
- 수리 이력 관리 (Repair Logging) [보수]
"""

from .models import (
    HealthStatus,
    HealthEntryFlags,
    ResourceMetrics,
    ServiceStatus,
    HealthCheckResult,
    DiagnosisResult,
    DiagnosisType,
    SeverityLevel,
    HealResult,
)
from .exceptions import (
    DevOpsError,
    HealthCheckError,
    ServiceUnavailableError,
    RecoveryFailedError,
    CircuitBreakerOpenError,
)
from .health_checker import HealthChecker, get_health_checker, init_health_checker
from .netdata_adapter import NetdataAdapter, get_netdata_adapter, init_netdata_adapter
from .watchdog import Watchdog, get_watchdog, init_watchdog
from .diagnoser import Diagnoser, get_diagnoser
from .healer import Healer, get_healer
from .repair_log import RepairLog, RepairRecord, RepairType, RepairStatus
from .config import (
    DEFAULT_HEALTH_CHECK_CONFIG,
    DEFAULT_WATCHDOG_CONFIG,
    DEFAULT_SERVICE_CHECKS,
)

__all__ = [
    # === 유지 (Maintenance) ===
    # 모델
    "HealthStatus",
    "HealthEntryFlags",
    "ResourceMetrics",
    "ServiceStatus",
    "HealthCheckResult",
    # 예외
    "DevOpsError",
    "HealthCheckError",
    "ServiceUnavailableError",
    "RecoveryFailedError",
    "CircuitBreakerOpenError",
    # 클래스 - 모니터링/복구
    "HealthChecker",
    "NetdataAdapter",
    "Watchdog",
    # 싱글톤 getter
    "get_health_checker",
    "get_netdata_adapter",
    "get_watchdog",
    # 초기화
    "init_health_checker",
    "init_netdata_adapter",
    "init_watchdog",
    # 설정
    "DEFAULT_HEALTH_CHECK_CONFIG",
    "DEFAULT_WATCHDOG_CONFIG",
    "DEFAULT_SERVICE_CHECKS",
    # === 보수 (Repair) ===
    # 진단
    "Diagnoser",
    "DiagnosisResult",
    "DiagnosisType",
    "SeverityLevel",
    "get_diagnoser",
    # 치유
    "Healer",
    "HealResult",
    "get_healer",
    # 수리 이력
    "RepairLog",
    "RepairRecord",
    "RepairType",
    "RepairStatus",
]

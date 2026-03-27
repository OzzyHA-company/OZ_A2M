"""OZ_A2M 제4부서: 유지보수관리센터 - 데이터 모델"""
from enum import IntFlag, Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List


class HealthStatus(Enum):
    """헬스 상태 열거형"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"
    MAINTENANCE = "maintenance"


class HealthEntryFlags(IntFlag):
    """헬스 엔트리 플래그 (netdata 패턴)"""
    PROCESSED = 0x00000001
    EXEC_RUN = 0x00000004
    EXEC_FAILED = 0x00000008
    SILENCED = 0x00000010
    EXEC_IN_PROGRESS = 0x00000040


class DiagnosisType(Enum):
    """진단 유형"""
    CONNECTIVITY = "connectivity"
    RESOURCE_EXHAUSTION = "resource"
    CONFIGURATION = "config"
    DEPENDENCY_FAILURE = "dependency"
    PERFORMANCE = "performance"
    UNKNOWN = "unknown"


class SeverityLevel(Enum):
    """심각도 레벨"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ResourceMetrics:
    """리소스 메트릭"""
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    memory_used_mb: int
    disk_percent: float
    disk_used_gb: float
    network_latency_ms: float


@dataclass
class ServiceStatus:
    """서비스 상태"""
    name: str
    is_healthy: bool
    last_check: datetime
    response_time_ms: Optional[float] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthCheckResult:
    """헬스체크 결과"""
    timestamp: datetime
    overall_status: HealthStatus
    resource_metrics: ResourceMetrics
    services: Dict[str, ServiceStatus]
    flags: HealthEntryFlags = HealthEntryFlags.PROCESSED
    message: Optional[str] = None


@dataclass
class DiagnosisResult:
    """진단 결과"""
    timestamp: datetime
    component: str
    diagnosis_type: DiagnosisType
    severity: SeverityLevel
    symptoms: List[str]
    root_cause: str
    evidence: Dict[str, Any]
    recommendations: List[str]
    auto_fixable: bool = False


@dataclass
class HealResult:
    """치유 결과"""
    success: bool
    action_taken: str
    message: str
    timestamp: datetime
    repair_id: Optional[str] = None
    side_effects: List[str] = field(default_factory=list)

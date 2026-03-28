"""OZ_A2M 제4부서: 유지보수관리센터 - 기본 설정"""
from typing import Dict, Any


DEFAULT_HEALTH_CHECK_CONFIG = {
    # 체크 간격 (초)
    "check_interval_seconds": 60,
    "run_at_least_every_seconds": 10,

    # CPU 임계값 (%)
    "cpu_warning_threshold": 75,
    "cpu_critical_threshold": 90,

    # 메모리 임계값 (%)
    "memory_warning_threshold": 80,
    "memory_critical_threshold": 95,

    # 디스크 임계값 (%)
    "disk_warning_threshold": 80,
    "disk_critical_threshold": 95,

    # 네트워크 타임아웃 (초)
    "network_timeout_seconds": 5,

    # 히스토리 저장 개수
    "max_history_entries": 1000,

    # 알림 설정
    "alert_cooldown_seconds": 600,
    "alert_repeat_every": 0,

    # 활성화
    "enabled": True,
}


DEFAULT_WATCHDOG_CONFIG = {
    # 체크 간격 (초)
    "check_interval_seconds": 30,

    # 프로세스 설정
    "heartbeat_timeout_seconds": 120,
    "pid_file_dir": "/tmp/oz_a2m",

    # 자동 복구 설정
    "auto_restart_enabled": True,
    "max_auto_restarts": 3,
    "restart_cooldown_seconds": 600,

    # 서킷 브레이커 (nuclei 패턴)
    "circuit_breaker_enabled": True,
    "circuit_breaker_failure_threshold": 5,
    "circuit_breaker_cooldown_seconds": 300,

    # 활성화
    "enabled": True,
}


DEFAULT_SERVICE_CHECKS = {
    "exchange_api": {
        "enabled": True,
        "timeout_seconds": 10,
        "retry_count": 3,
        "retry_delay_seconds": 1,
    },
    "database": {
        "enabled": True,
        "timeout_seconds": 5,
        "query": "SELECT 1",
    },
    "filesystem": {
        "enabled": True,
        "paths": ["/", "/tmp", "/var/log"],
    },
}

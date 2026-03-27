"""헬스 체커 - 시스템 및 서비스 상태 모니터링"""
import logging
import threading
import asyncio
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime

from .models import HealthStatus, HealthCheckResult, ResourceMetrics, ServiceStatus, HealthEntryFlags
from .config import DEFAULT_HEALTH_CHECK_CONFIG, DEFAULT_SERVICE_CHECKS
from .exceptions import HealthCheckError

logger = logging.getLogger(__name__)


class HealthChecker:
    """시스템 헬스 체커"""

    DEFAULT_CONFIG = DEFAULT_HEALTH_CHECK_CONFIG

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        self._lock = threading.RLock()
        self._history: List[HealthCheckResult] = []
        self._callbacks: List[Callable] = []
        self._service_checks = DEFAULT_SERVICE_CHECKS.copy()
        self._circuit_failures: Dict[str, List[datetime]] = {}

    def check_system_resources(self) -> ResourceMetrics:
        """시스템 리소스 체크 (psutil 사용)"""
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            # 네트워크 지연 시간 측정
            latency = self._measure_network_latency()

            return ResourceMetrics(
                timestamp=datetime.now(),
                cpu_percent=cpu,
                memory_percent=mem.percent,
                memory_used_mb=mem.used // (1024 * 1024),
                disk_percent=(disk.used / disk.total) * 100,
                disk_used_gb=disk.used / (1024**3),
                network_latency_ms=latency
            )
        except Exception as e:
            logger.error(f"Resource check failed: {e}")
            raise HealthCheckError("system", str(e))

    def _measure_network_latency(self) -> float:
        """네트워크 지연 시간 측정"""
        try:
            import subprocess
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "2", "8.8.8.8"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                # Parse time from ping output
                output = result.stdout.decode()
                if "time=" in output:
                    time_str = output.split("time=")[1].split()[0]
                    return float(time_str.replace("ms", ""))
            return 0.0
        except Exception:
            return 0.0

    async def check_service(self, name: str, config: Dict[str, Any]) -> ServiceStatus:
        """개별 서비스 상태 체크"""
        start_time = datetime.now()

        try:
            if name == "exchange_api":
                result = await self._check_exchange_api(config)
            elif name == "database":
                result = await self._check_database(config)
            elif name == "filesystem":
                result = await self._check_filesystem(config)
            else:
                result = ServiceStatus(
                    name=name,
                    is_healthy=False,
                    last_check=start_time,
                    error_message="Unknown service"
                )

            # 응답 시간 계산
            elapsed = (datetime.now() - start_time).total_seconds() * 1000
            result.response_time_ms = elapsed

            return result

        except Exception as e:
            return ServiceStatus(
                name=name,
                is_healthy=False,
                last_check=start_time,
                error_message=str(e)
            )

    async def _check_exchange_api(self, config: Dict[str, Any]) -> ServiceStatus:
        """거래소 API 연결 체크 (재시도 로직)"""
        retries = config.get("retry_count", 3)
        delay = config.get("retry_delay_seconds", 1)

        for i in range(retries):
            try:
                # 실제 거래소 API ping (구현 필요)
                return ServiceStatus(
                    name="exchange_api",
                    is_healthy=True,
                    last_check=datetime.now()
                )
            except Exception as e:
                if i < retries - 1:
                    await asyncio.sleep(delay)
                    continue
                raise e

    async def _check_database(self, config: Dict[str, Any]) -> ServiceStatus:
        """데이터베이스 연결 체크"""
        try:
            # 구현 필요: DB 연결 체크
            return ServiceStatus(
                name="database",
                is_healthy=True,
                last_check=datetime.now()
            )
        except Exception as e:
            return ServiceStatus(
                name="database",
                is_healthy=False,
                last_check=datetime.now(),
                error_message=str(e)
            )

    async def _check_filesystem(self, config: Dict[str, Any]) -> ServiceStatus:
        """파일시스템 체크"""
        paths = config.get("paths", ["/"])
        for path in paths:
            import os
            if not os.path.exists(path):
                return ServiceStatus(
                    name="filesystem",
                    is_healthy=False,
                    last_check=datetime.now(),
                    error_message=f"Path not found: {path}"
                )
        return ServiceStatus(
            name="filesystem",
            is_healthy=True,
            last_check=datetime.now()
        )

    def evaluate_health_status(
        self,
        metrics: ResourceMetrics,
        services: Dict[str, ServiceStatus]
    ) -> HealthStatus:
        """전체 헬스 상태 평가"""
        critical_count = 0
        warning_count = 0

        # 리소스 체크
        if metrics.cpu_percent > self.config["cpu_critical_threshold"]:
            critical_count += 1
        elif metrics.cpu_percent > self.config["cpu_warning_threshold"]:
            warning_count += 1

        if metrics.memory_percent > self.config["memory_critical_threshold"]:
            critical_count += 1
        elif metrics.memory_percent > self.config["memory_warning_threshold"]:
            warning_count += 1

        if metrics.disk_percent > self.config["disk_critical_threshold"]:
            critical_count += 1
        elif metrics.disk_percent > self.config["disk_warning_threshold"]:
            warning_count += 1

        # 서비스 체크
        for service in services.values():
            if not service.is_healthy:
                critical_count += 1

        # 상태 결정
        if critical_count > 0:
            return HealthStatus.CRITICAL
        elif warning_count > 0:
            return HealthStatus.WARNING
        return HealthStatus.HEALTHY

    def on_status_change(self, callback: Callable[[HealthStatus, HealthCheckResult], None]):
        """상태 변경 콜백 등록"""
        self._callbacks.append(callback)


# 싱글톤 인스턴스
_health_checker_instance: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    """HealthChecker 싱글톤 인스턴스 가져오기"""
    global _health_checker_instance
    if _health_checker_instance is None:
        _health_checker_instance = HealthChecker()
    return _health_checker_instance


def init_health_checker(config: Optional[Dict[str, Any]] = None) -> HealthChecker:
    """HealthChecker 초기화 (명시적)"""
    global _health_checker_instance
    _health_checker_instance = HealthChecker(config=config)
    return _health_checker_instance

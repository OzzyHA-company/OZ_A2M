"""OZ_A2M 제4부서: 유지보수관리센터 - 예외 클래스"""


class DevOpsError(Exception):
    """유지보수관리센터 기본 예외"""
    pass


class HealthCheckError(DevOpsError):
    """헬스체크 실패 예외"""
    def __init__(self, service_name: str, message: str):
        self.service_name = service_name
        self.message = message
        super().__init__(f"[{service_name}] {message}")


class ServiceUnavailableError(DevOpsError):
    """서비스 사용 불가 예외"""
    def __init__(self, service_name: str, reason: str = ""):
        self.service_name = service_name
        msg = f"Service '{service_name}' is unavailable"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class RecoveryFailedError(DevOpsError):
    """복구 실패 예외"""
    def __init__(self, service_name: str, attempts: int, last_error: str):
        self.service_name = service_name
        self.attempts = attempts
        super().__init__(
            f"Failed to recover '{service_name}' after {attempts} attempts: {last_error}"
        )


class CircuitBreakerOpenError(DevOpsError):
    """서킷 브레이커 오픈 예외 (nuclei 패턴)"""
    def __init__(self, service_name: str, cooldown_seconds: int):
        self.service_name = service_name
        self.cooldown_seconds = cooldown_seconds
        super().__init__(
            f"Circuit breaker open for '{service_name}'. "
            f"Retry after {cooldown_seconds}s"
        )

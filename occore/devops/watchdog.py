"""와치독 - 프로세스 모니터링 및 자동 복구"""
import os
import time
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, List, Callable, Any
from datetime import datetime, timedelta
from collections import defaultdict

from .config import DEFAULT_WATCHDOG_CONFIG
from .exceptions import RecoveryFailedError, CircuitBreakerOpenError

logger = logging.getLogger(__name__)


class Watchdog:
    """시스템 와치독"""

    DEFAULT_CONFIG = DEFAULT_WATCHDOG_CONFIG

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        self._lock = threading.RLock()
        self._running = False
        self._monitored_processes: Dict[str, Dict[str, Any]] = {}
        self._restart_history: Dict[str, List[float]] = defaultdict(list)
        self._circuit_failures: Dict[str, List[datetime]] = defaultdict(list)
        self._callbacks: List[Callable] = []
        self._pid_dir = Path(self.config["pid_file_dir"])
        self._pid_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def register_process(
        self,
        name: str,
        pid: Optional[int] = None,
        pid_file: Optional[str] = None,
        restart_cmd: Optional[str] = None,
        heartbeat_file: Optional[str] = None,
        auto_restart: bool = True
    ):
        """프로세스 등록"""
        with self._lock:
            self._monitored_processes[name] = {
                "name": name,
                "pid": pid,
                "pid_file": pid_file,
                "restart_cmd": restart_cmd,
                "heartbeat_file": heartbeat_file,
                "auto_restart": auto_restart,
                "registered_at": datetime.now(),
                "last_heartbeat": None,
                "status": "unknown"
            }
        logger.info(f"Registered process: {name}")

    def is_process_alive(self, name: str) -> bool:
        """프로세스 생존 확인"""
        proc = self._monitored_processes.get(name)
        if not proc:
            return False

        # 1. PID 파일 체크
        if proc.get("pid_file"):
            pid_file = Path(proc["pid_file"])
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    os.kill(pid, 0)
                    return True
                except (ValueError, ProcessLookupError, PermissionError):
                    pass

        # 2. 하트비트 파일 체크
        if proc.get("heartbeat_file"):
            hb_file = Path(proc["heartbeat_file"])
            if hb_file.exists():
                last_modified = datetime.fromtimestamp(hb_file.stat().st_mtime)
                timeout = timedelta(seconds=self.config["heartbeat_timeout_seconds"])
                if datetime.now() - last_modified < timeout:
                    return True

        # 3. PID 직접 체크
        if proc.get("pid"):
            try:
                os.kill(proc["pid"], 0)
                return True
            except (ProcessLookupError, PermissionError):
                pass

        return False

    def _check_circuit_breaker(self, name: str) -> bool:
        """서킷 브레이커 체크 (nuclei 패턴)"""
        if not self.config["circuit_breaker_enabled"]:
            return True

        threshold = self.config["circuit_breaker_failure_threshold"]
        cooldown = self.config["circuit_breaker_cooldown_seconds"]

        with self._lock:
            failures = self._circuit_failures[name]
            now = datetime.now()

            # 오래된 실패 제거
            failures[:] = [f for f in failures if now - f < timedelta(seconds=cooldown)]

            if len(failures) >= threshold:
                logger.warning(f"Circuit breaker open for {name}")
                return False

        return True

    def _record_failure(self, name: str):
        """실패 기록"""
        with self._lock:
            self._circuit_failures[name].append(datetime.now())

    def _can_restart(self, name: str) -> bool:
        """재시작 가능 여부 체크"""
        max_restarts = self.config["max_auto_restarts"]
        cooldown = self.config["restart_cooldown_seconds"]

        with self._lock:
            history = self._restart_history[name]
            now = time.time()

            # 오래된 재시작 기록 제거
            history[:] = [t for t in history if now - t < cooldown]

            return len(history) < max_restarts

    def restart_process(self, name: str) -> bool:
        """프로세스 재시작"""
        proc = self._monitored_processes.get(name)
        if not proc:
            logger.error(f"Unknown process: {name}")
            return False

        restart_cmd = proc.get("restart_cmd")
        if not restart_cmd:
            logger.error(f"No restart command for {name}")
            return False

        try:
            import subprocess
            result = subprocess.run(
                restart_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60
            )

            success = result.returncode == 0

            if success:
                with self._lock:
                    self._restart_history[name].append(time.time())
                logger.info(f"Successfully restarted {name}")
            else:
                logger.error(f"Failed to restart {name}: {result.stderr}")
                self._record_failure(name)

            return success

        except Exception as e:
            logger.error(f"Restart error for {name}: {e}")
            self._record_failure(name)
            return False

    def check_all(self) -> Dict[str, str]:
        """모든 프로세스 체크"""
        results = {}

        for name in self._monitored_processes:
            if self.is_process_alive(name):
                results[name] = "healthy"
            else:
                results[name] = "unhealthy"

                # 자동 복구 시도
                proc = self._monitored_processes[name]
                if proc.get("auto_restart") and self.config["auto_restart_enabled"]:
                    if self._can_restart(name) and self._check_circuit_breaker(name):
                        logger.warning(f"Attempting to restart {name}")
                        if self.restart_process(name):
                            results[name] = "restarted"
                    else:
                        results[name] = "restart_limit_exceeded"

        return results

    def start(self):
        """와치독 시작"""
        self._running = True
        logger.info("Watchdog started")

    def stop(self):
        """와치독 중지"""
        self._running = False
        logger.info("Watchdog stopped")


# 싱글톤 인스턴스
_watchdog_instance: Optional[Watchdog] = None


def get_watchdog() -> Watchdog:
    """Watchdog 싱글톤 인스턴스 가져오기"""
    global _watchdog_instance
    if _watchdog_instance is None:
        _watchdog_instance = Watchdog()
    return _watchdog_instance


def init_watchdog(config: Optional[Dict[str, Any]] = None) -> Watchdog:
    """Watchdog 초기화 (명시적)"""
    global _watchdog_instance
    _watchdog_instance = Watchdog(config=config)
    return _watchdog_instance

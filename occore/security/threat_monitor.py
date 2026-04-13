"""
OZ_A2M 제3부서: 보안팀 - 실시간 위협 모니터링 시스템

실패한 인증 시도 추적, 비정상 패턴 탐지, 자동 IP 차단 및 알림
"""

import os
import json
import time
import logging
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Set
from dataclasses import dataclass, asdict
from collections import defaultdict, deque
import ipaddress

from .acl import get_acl, AccessDenied
from .audit import get_audit_logger, AuditEventType

logger = logging.getLogger(__name__)


@dataclass
class ThreatPattern:
    """탐지된 위협 패턴"""
    pattern_type: str
    source_ip: Optional[str]
    user_id: Optional[str]
    confidence: float  # 0-1
    details: Dict[str, Any]
    detected_at: str


class ThreatMonitor:
    """
    실시간 위협 모니터링 시스템

    기능:
    - 실패한 인증 시도 추적 (5분 내 5회 → 차단)
    - 비정상 패턴 탐지 (대량 요청, 비정상 시간대)
    - 자동 IP 차단 및 알림
    - 실시간 위협 인텔리전스
    """

    DEFAULT_CONFIG = {
        "failed_attempt_threshold": 5,
        "failed_attempt_window_minutes": 5,
        "request_rate_threshold": 100,  # 1분당 최대 요청 수
        "auto_block_duration_minutes": 30,
        "suspicious_hours": [0, 1, 2, 3, 4, 5],  # 자정-새벽 6시
        "enabled": True,
    }

    def __init__(self, config_dir: Optional[Path] = None):
        """
        위협 모니터 초기화

        Args:
            config_dir: 설정 디렉토리 (기본: ~/.openclaw/security)
        """
        self.config_dir = config_dir or Path.home() / ".openclaw" / "security"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "threat_monitor.json"

        self.config = self._load_config()
        self.acl = get_acl()
        self.audit = get_audit_logger()

        # 실시간 모니터링 데이터
        self._failed_attempts: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=100)
        )
        self._request_counts: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        self._blocked_until: Dict[str, datetime] = {}
        self._suspicious_ips: Set[str] = set()

        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

    def _load_config(self) -> Dict[str, Any]:
        """설정 로드"""
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    return {**self.DEFAULT_CONFIG, **json.load(f)}
            except Exception as e:
                logger.error(f"Failed to load threat monitor config: {e}")

        return self.DEFAULT_CONFIG.copy()

    def save_config(self) -> None:
        """설정 저장"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)

    def start(self) -> None:
        """모니터링 시작"""
        if self._running:
            logger.warning("Threat monitor already running")
            return

        if not self.config.get("enabled", True):
            logger.info("Threat monitor is disabled")
            return

        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

        logger.info("Threat monitor started")

    def stop(self) -> None:
        """모니터링 중지"""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logger.info("Threat monitor stopped")

    def _monitor_loop(self) -> None:
        """모니터링 루프 (백그라운드)"""
        while self._running:
            try:
                self._cleanup_old_data()
                self._check_suspicious_patterns()
                time.sleep(30)  # 30초마다 체크
            except Exception as e:
                logger.error(f"Error in threat monitor loop: {e}")
                time.sleep(60)

    def _cleanup_old_data(self) -> None:
        """오래된 데이터 정리"""
        with self._lock:
            now = datetime.now()

            # 차단 만료 확인
            expired = [
                ip for ip, until in self._blocked_until.items()
                if now > until
            ]
            for ip in expired:
                del self._blocked_until[ip]
                self.acl.unblock_ip(ip)
                logger.info(f"Auto-unblocked IP: {ip}")

            # 만료된 실패 시도 제거
            cutoff = now - timedelta(minutes=self.config["failed_attempt_window_minutes"])
            for ip, attempts in list(self._failed_attempts.items()):
                while attempts and attempts[0] < cutoff:
                    attempts.popleft()
                if not attempts:
                    del self._failed_attempts[ip]

    def _check_suspicious_patterns(self) -> None:
        """의심스러운 패턴 체크"""
        with self._lock:
            now = datetime.now()

            # 비정상 시간대 접속 체크
            current_hour = now.hour
            if current_hour in self.config.get("suspicious_hours", []):
                for ip in self._request_counts:
                    if ip not in self._suspicious_ips:
                        recent_count = len([
                            t for t in self._request_counts[ip]
                            if now - t < timedelta(minutes=10)
                        ])
                        if recent_count > 10:
                            self._suspicious_ips.add(ip)
                            self.audit.log_security_alert(
                                alert_type="suspicious_hour_activity",
                                severity="medium",
                                description=f"Activity detected during suspicious hours ({current_hour}:00) from {ip}",
                                source_ip=ip
                            )

    def record_failed_attempt(
        self,
        ip_address: str,
        user_id: Optional[str] = None,
        attempt_type: str = "auth"
    ) -> bool:
        """
        실패한 시도 기록 및 위협 평가

        Args:
            ip_address: IP 주소
            user_id: 사용자 ID
            attempt_type: 시도 유형

        Returns:
            차단 여부
        """
        with self._lock:
            now = datetime.now()
            self._failed_attempts[ip_address].append(now)

            # 감사 로그 기록
            self.audit.log_access_attempt(
                ip_address=ip_address,
                user_id=user_id,
                attempt_type=attempt_type,
                success=False,
                reason="Authentication failed"
            )

            # 차단 임계값 체크
            window_start = now - timedelta(
                minutes=self.config["failed_attempt_window_minutes"]
            )
            recent_failures = len([
                t for t in self._failed_attempts[ip_address]
                if t > window_start
            ])

            threshold = self.config["failed_attempt_threshold"]

            if recent_failures >= threshold:
                # 자동 차단
                block_duration = self.config["auto_block_duration_minutes"]
                self._blocked_until[ip_address] = now + timedelta(minutes=block_duration)
                self.acl.block_ip(ip_address, block_duration)

                self.audit.log_security_alert(
                    alert_type="auto_block_brute_force",
                    severity="high",
                    description=f"IP {ip_address} blocked for {block_duration}min due to {recent_failures} failed attempts",
                    source_ip=ip_address,
                    user_id=user_id
                )

                logger.warning(
                    f"Auto-blocked {ip_address} for {block_duration}min "
                    f"({recent_failures} failed attempts)"
                )
                return True

            return False

    def record_request(self, ip_address: str, user_id: Optional[str] = None) -> Optional[str]:
        """
        요청 기록 및 속도 제한 체크

        Args:
            ip_address: IP 주소
            user_id: 사용자 ID

        Returns:
            차단 메시지 (None이면 정상)
        """
        with self._lock:
            now = datetime.now()

            # 현재 차단 중인지 확인
            if ip_address in self._blocked_until:
                if now < self._blocked_until[ip_address]:
                    remaining = (self._blocked_until[ip_address] - now).seconds // 60
                    return f"IP blocked. Try again in {remaining} minutes."
                else:
                    del self._blocked_until[ip_address]

            self._request_counts[ip_address].append(now)

            # 속도 제한 체크 (1분 윈도우)
            minute_ago = now - timedelta(minutes=1)
            recent_requests = len([
                t for t in self._request_counts[ip_address]
                if t > minute_ago
            ])

            if recent_requests > self.config["request_rate_threshold"]:
                # 일시적 차단 (5분)
                self._blocked_until[ip_address] = now + timedelta(minutes=5)

                self.audit.log_security_alert(
                    alert_type="rate_limit_exceeded",
                    severity="medium",
                    description=f"Rate limit exceeded from {ip_address} ({recent_requests} req/min)",
                    source_ip=ip_address,
                    user_id=user_id
                )

                return "Rate limit exceeded. Please slow down."

            return None

    def analyze_threat_intelligence(self, ip_address: str) -> Dict[str, Any]:
        """
        IP 위협 인텔리전스 분석

        Args:
            ip_address: 분석할 IP

        Returns:
            위협 분석 결과
        """
        result = {
            "ip": ip_address,
            "threat_level": "low",
            "factors": [],
            "recommendation": "allow"
        }

        with self._lock:
            # 실패 시도 수
            failed_count = len(self._failed_attempts.get(ip_address, []))
            if failed_count > 0:
                result["factors"].append(f"{failed_count} failed attempts")
                result["threat_level"] = "medium"

            # 차단 이력
            if ip_address in self._blocked_until:
                result["factors"].append("Currently blocked")
                result["threat_level"] = "high"
                result["recommendation"] = "block"
            elif ip_address in self._suspicious_ips:
                result["factors"].append("Suspicious activity pattern")
                result["threat_level"] = "medium"
                result["recommendation"] = "monitor"

            # 요청 패턴
            request_count = len(self._request_counts.get(ip_address, []))
            if request_count > 100:
                result["factors"].append(f"High request volume ({request_count})")

        return result

    def get_blocked_ips(self) -> List[Dict[str, Any]]:
        """현재 차단된 IP 목록"""
        with self._lock:
            now = datetime.now()
            return [
                {
                    "ip": ip,
                    "blocked_until": until.isoformat(),
                    "remaining_minutes": max(0, (until - now).seconds // 60)
                }
                for ip, until in self._blocked_until.items()
                if now < until
            ]

    def get_threat_stats(self) -> Dict[str, Any]:
        """위협 모니터링 통계"""
        with self._lock:
            now = datetime.now()

            # 1시간 내 실패 시도
            hour_ago = now - timedelta(hours=1)
            recent_failures = sum(
                1 for attempts in self._failed_attempts.values()
                for t in attempts if t > hour_ago
            )

            return {
                "currently_blocked": len(self._blocked_until),
                "suspicious_ips": len(self._suspicious_ips),
                "recent_failures_1h": recent_failures,
                "monitored_ips": len(self._failed_attempts),
                "config": self.config,
            }

    def manual_block(
        self,
        ip_address: str,
        duration_minutes: int,
        reason: str,
        admin_id: str
    ) -> bool:
        """
        수동 IP 차단

        Args:
            ip_address: 차단할 IP
            duration_minutes: 차단 기간
            reason: 차단 사유
            admin_id: 관리자 ID

        Returns:
            성공 여부
        """
        try:
            ipaddress.IPv4Address(ip_address)
        except ValueError:
            logger.error(f"Invalid IP for manual block: {ip_address}")
            return False

        with self._lock:
            until = datetime.now() + timedelta(minutes=duration_minutes)
            self._blocked_until[ip_address] = until
            self.acl.block_ip(ip_address, duration_minutes)

            self.audit.log_security_alert(
                alert_type="manual_block",
                severity="medium",
                description=f"IP {ip_address} manually blocked by {admin_id} for {duration_minutes}min. Reason: {reason}",
                source_ip=ip_address
            )

            logger.info(f"Manual block: {ip_address} by {admin_id}")
            return True

    def unblock(self, ip_address: str, admin_id: str) -> bool:
        """
        IP 차단 해제

        Args:
            ip_address: 해제할 IP
            admin_id: 관리자 ID

        Returns:
            성공 여부
        """
        with self._lock:
            if ip_address not in self._blocked_until:
                return False

            del self._blocked_until[ip_address]
            self.acl.unblock_ip(ip_address)

            if ip_address in self._suspicious_ips:
                self._suspicious_ips.remove(ip_address)

            self.audit.log_security_alert(
                alert_type="manual_unblock",
                severity="low",
                description=f"IP {ip_address} unblocked by {admin_id}",
                source_ip=ip_address
            )

            logger.info(f"Unblocked: {ip_address} by {admin_id}")
            return True

    def detect_anomalies(self) -> List[ThreatPattern]:
        """
        이상 패턴 탐지

        Returns:
            탐지된 위협 패턴 목록
        """
        patterns = []
        now = datetime.now()

        with self._lock:
            # 비정상적인 요청 패턴
            for ip, times in self._request_counts.items():
                if len(times) < 10:
                    continue

                # 시간 간격 분석
                intervals = []
                sorted_times = sorted(times)
                for i in range(1, len(sorted_times)):
                    diff = (sorted_times[i] - sorted_times[i-1]).total_seconds()
                    intervals.append(diff)

                if not intervals:
                    continue

                avg_interval = sum(intervals) / len(intervals)

                # 너무 규칙적인 패턴 (봇 의심)
                if avg_interval < 2 and len(times) > 50:
                    patterns.append(ThreatPattern(
                        pattern_type="bot_like_pattern",
                        source_ip=ip,
                        user_id=None,
                        confidence=0.8,
                        details={"avg_interval": avg_interval, "request_count": len(times)},
                        detected_at=now.isoformat()
                    ))

            # 지리적 이상 (같은 사용자가 다른 IP에서)
            # (구현 시 IP 지리정보 DB 필요)

        return patterns


# 싱글톤 인스턴스
_threat_monitor_instance: Optional[ThreatMonitor] = None


def get_threat_monitor() -> ThreatMonitor:
    """ThreatMonitor 싱글톤 인스턴스 가져오기"""
    global _threat_monitor_instance
    if _threat_monitor_instance is None:
        _threat_monitor_instance = ThreatMonitor()
    return _threat_monitor_instance


# 호환성 별칭
from enum import Enum

class ThreatLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

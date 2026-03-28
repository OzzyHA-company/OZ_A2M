"""
OZ_A2M 제3부서: 보안팀 - 접근 제어 시스템 (ACL)

IP 화이트리스트, 사용자 인증, 명령어 권한 레벨 관리
"""

import os
import json
import logging
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional, Set, Dict, Any
from datetime import datetime
import ipaddress

logger = logging.getLogger(__name__)


class PermissionLevel(Enum):
    """권한 레벨"""
    READ = "read"          # 읽기만 가능 (상태 조회)
    WRITE = "write"        # 쓰기 가능 (봇 제어, 명령 실행)
    ADMIN = "admin"        # 관리자 (설정 변경, 사용자 관리)


class AccessDenied(Exception):
    """접근 거부 예외"""
    def __init__(self, reason: str, user_id: Optional[str] = None):
        self.reason = reason
        self.user_id = user_id
        super().__init__(f"Access denied for {user_id}: {reason}")


class AccessControl:
    """
    접근 제어 관리자

    기능:
    - IP 화이트리스트 검사
    - Telegram 사용자 ID 검증
    - 명령어 레벨 권한 관리
    - 세션 기반 접근 제어
    """

    CONFIG_FILENAME = "acl.json"

    def __init__(self, config_dir: Optional[Path] = None):
        """
        ACL 초기화

        Args:
            config_dir: 설정 파일 디렉토리 (기본: ~/.openclaw/security)
        """
        self.config_dir = config_dir or Path.home() / ".openclaw" / "security"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / self.CONFIG_FILENAME

        self._allowed_ips: Set[ipaddress.IPv4Network] = set()
        self._allowed_telegram_ids: Dict[str, PermissionLevel] = {}
        self._blocked_ips: Set[ipaddress.IPv4Address] = set()
        self._command_permissions: Dict[str, PermissionLevel] = {}

        self._load_config()
        self._apply_env_overrides()

    def _load_config(self) -> None:
        """설정 파일 로드"""
        if not self.config_file.exists():
            logger.info("ACL config not found, creating default")
            self._create_default_config()
            return

        try:
            data = json.loads(self.config_file.read_text())

            # IP 화이트리스트
            for ip_str in data.get("allowed_ips", []):
                try:
                    self._allowed_ips.add(ipaddress.IPv4Network(ip_str, strict=False))
                except ValueError:
                    logger.warning(f"Invalid IP in whitelist: {ip_str}")

            # Telegram 사용자 ID
            for user_id, level in data.get("allowed_telegram_ids", {}).items():
                self._allowed_telegram_ids[user_id] = PermissionLevel(level)

            # 차단된 IP
            for ip_str in data.get("blocked_ips", []):
                try:
                    self._blocked_ips.add(ipaddress.IPv4Address(ip_str))
                except ValueError:
                    logger.warning(f"Invalid blocked IP: {ip_str}")

            # 명령어 권한
            for cmd, level in data.get("command_permissions", {}).items():
                self._command_permissions[cmd] = PermissionLevel(level)

            logger.debug(f"ACL config loaded: {len(self._allowed_ips)} IPs, "
                        f"{len(self._allowed_telegram_ids)} users")

        except Exception as e:
            logger.error(f"Failed to load ACL config: {e}")
            self._create_default_config()

    def _create_default_config(self) -> None:
        """기본 설정 생성"""
        default_config = {
            "allowed_ips": ["127.0.0.1/32", "192.168.0.0/16", "10.0.0.0/8"],
            "allowed_telegram_ids": {},
            "blocked_ips": [],
            "command_permissions": {
                "status": "read",
                "profit": "read",
                "bot_status": "read",
                "bot_start": "write",
                "bot_stop": "write",
                "bot_restart": "write",
                "bash_exec": "admin",
                "system_reboot": "admin",
                "killswitch": "admin",
            },
            "created_at": datetime.now().isoformat(),
        }
        self.save_config(default_config)
        self._load_config()

    def _apply_env_overrides(self) -> None:
        """환경변수 설정 오버라이드"""
        # ALLOWED_IPS 환경변수 (쉼표로 구분)
        if env_ips := os.getenv("ALLOWED_IPS"):
            self._allowed_ips.clear()
            for ip_str in env_ips.split(","):
                try:
                    self._allowed_ips.add(ipaddress.IPv4Network(ip_str.strip(), strict=False))
                except ValueError:
                    logger.warning(f"Invalid IP in ALLOWED_IPS: {ip_str}")
            logger.info(f"IP whitelist overridden from env: {len(self._allowed_ips)} IPs")

        # ALLOWED_TELEGRAM_IDS 환경변수 (user_id:level,user_id:level 형식)
        if env_users := os.getenv("ALLOWED_TELEGRAM_IDS"):
            self._allowed_telegram_ids.clear()
            for user_entry in env_users.split(","):
                parts = user_entry.strip().split(":")
                user_id = parts[0]
                level = PermissionLevel(parts[1]) if len(parts) > 1 else PermissionLevel.READ
                self._allowed_telegram_ids[user_id] = level
            logger.info(f"Telegram users overridden from env: {len(self._allowed_telegram_ids)} users")

    def save_config(self, config: Optional[Dict] = None) -> None:
        """설정 저장"""
        if config is None:
            config = {
                "allowed_ips": [str(ip) for ip in self._allowed_ips],
                "allowed_telegram_ids": {
                    uid: level.value for uid, level in self._allowed_telegram_ids.items()
                },
                "blocked_ips": [str(ip) for ip in self._blocked_ips],
                "command_permissions": {
                    cmd: level.value for cmd, level in self._command_permissions.items()
                },
                "updated_at": datetime.now().isoformat(),
            }

        self.config_file.write_text(json.dumps(config, indent=2))
        os.chmod(self.config_file, 0o600)

    def check_ip_allowed(self, ip_str: str) -> bool:
        """
        IP가 허용되는지 검사

        Args:
            ip_str: 검사할 IP 주소

        Returns:
            허용 여부
        """
        try:
            ip = ipaddress.IPv4Address(ip_str)

            # 명시적 차단 확인
            if ip in self._blocked_ips:
                logger.warning(f"IP {ip} is blocked")
                return False

            # 화이트리스트 확인 (비어있으면 모두 허용)
            if not self._allowed_ips:
                return True

            # 서브넷 매칭
            for network in self._allowed_ips:
                if ip in network:
                    return True

            logger.warning(f"IP {ip} not in whitelist")
            return False

        except ValueError:
            logger.error(f"Invalid IP address: {ip_str}")
            return False

    def check_telegram_user(self, user_id: str) -> PermissionLevel:
        """
        Telegram 사용자 권한 확인

        Args:
            user_id: Telegram 사용자 ID

        Returns:
            사용자 권한 레벨

        Raises:
            AccessDenied: 사용자가 등록되지 않은 경우
        """
        if user_id not in self._allowed_telegram_ids:
            raise AccessDenied(f"User {user_id} not authorized", user_id)

        return self._allowed_telegram_ids[user_id]

    def check_command_permission(self, command: str, user_level: PermissionLevel) -> bool:
        """
        명령어 실행 권한 확인

        Args:
            command: 실행하려는 명령어
            user_level: 사용자 권한 레벨

        Returns:
            실행 가능 여부
        """
        required_level = self._command_permissions.get(command, PermissionLevel.ADMIN)

        level_order = {
            PermissionLevel.READ: 0,
            PermissionLevel.WRITE: 1,
            PermissionLevel.ADMIN: 2,
        }

        return level_order[user_level] >= level_order[required_level]

    def authorize(
        self,
        user_id: Optional[str] = None,
        ip: Optional[str] = None,
        command: Optional[str] = None
    ) -> PermissionLevel:
        """
        종합 권한 검사

        Args:
            user_id: Telegram 사용자 ID
            ip: 클라이언트 IP
            command: 실행하려는 명령어

        Returns:
            부여된 권한 레벨

        Raises:
            AccessDenied: 권한이 없는 경우
        """
        # IP 검사
        if ip and not self.check_ip_allowed(ip):
            raise AccessDenied(f"IP {ip} not allowed", user_id)

        # 사용자 검사
        if user_id:
            user_level = self.check_telegram_user(user_id)
        else:
            user_level = PermissionLevel.READ  # 기본 읽기 권한

        # 명령어 권한 검사
        if command and not self.check_command_permission(command, user_level):
            raise AccessDenied(
                f"Command '{command}' requires {self._command_permissions.get(command, PermissionLevel.ADMIN).value}, "
                f"user has {user_level.value}",
                user_id
            )

        logger.info(f"Access granted: user={user_id}, ip={ip}, command={command}, level={user_level.value}")
        return user_level

    def add_telegram_user(self, user_id: str, level: PermissionLevel = PermissionLevel.READ) -> None:
        """Telegram 사용자 추가"""
        self._allowed_telegram_ids[user_id] = level
        self.save_config()
        logger.info(f"Added telegram user {user_id} with {level.value} permission")

    def remove_telegram_user(self, user_id: str) -> bool:
        """Telegram 사용자 제거"""
        if user_id in self._allowed_telegram_ids:
            del self._allowed_telegram_ids[user_id]
            self.save_config()
            logger.info(f"Removed telegram user {user_id}")
            return True
        return False

    def add_allowed_ip(self, ip_str: str) -> None:
        """허용 IP 추가"""
        try:
            network = ipaddress.IPv4Network(ip_str, strict=False)
            self._allowed_ips.add(network)
            self.save_config()
            logger.info(f"Added IP to whitelist: {ip_str}")
        except ValueError as e:
            logger.error(f"Invalid IP: {ip_str} - {e}")

    def block_ip(self, ip_str: str, duration_minutes: Optional[int] = None) -> None:
        """
        IP 차단

        Args:
            ip_str: 차단할 IP
            duration_minutes: 차단 기간 (None이면 영구)
        """
        try:
            ip = ipaddress.IPv4Address(ip_str)
            self._blocked_ips.add(ip)
            self.save_config()
            logger.warning(f"Blocked IP: {ip_str} (duration: {duration_minutes}min)")
        except ValueError:
            logger.error(f"Invalid IP to block: {ip_str}")

    def unblock_ip(self, ip_str: str) -> bool:
        """IP 차단 해제"""
        try:
            ip = ipaddress.IPv4Address(ip_str)
            if ip in self._blocked_ips:
                self._blocked_ips.remove(ip)
                self.save_config()
                logger.info(f"Unblocked IP: {ip_str}")
                return True
            return False
        except ValueError:
            logger.error(f"Invalid IP to unblock: {ip_str}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """ACL 상태 정보"""
        return {
            "allowed_ips_count": len(self._allowed_ips),
            "allowed_telegram_users_count": len(self._allowed_telegram_ids),
            "blocked_ips_count": len(self._blocked_ips),
            "telegram_users": {
                uid: level.value for uid, level in self._allowed_telegram_ids.items()
            },
            "blocked_ips": [str(ip) for ip in self._blocked_ips],
        }


# 싱글톤 인스턴스
_acl_instance: Optional[AccessControl] = None


def get_acl() -> AccessControl:
    """ACL 싱글톤 인스턴스 가져오기"""
    global _acl_instance
    if _acl_instance is None:
        _acl_instance = AccessControl()
    return _acl_instance

"""
OZ_A2M 제3부서: 보안팀 - API Key Vault 시스템

API key, 비밀번호 등 민감정보를 암호화하여 저장하고
런타임에만 메모리에 복호화하는 보안 저장소
"""

import os
import json
import base64
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


class VaultKeyError(Exception):
    """Vault 키 관련 예외"""
    pass


class Vault:
    """
    암호화된 API Key 및 민감정보 저장소

    특징:
    - Fernet 대칭 암호화 사용
    - 런타임에만 메모리에 평문 복호화
    - 주기적 키 순환 (기본 30일)
    - 안전한 메모리 삭제
    """

    DEFAULT_KEY_ROTATION_DAYS = 30
    VAULT_FILENAME = "vault.enc"
    SALT_FILENAME = "vault.salt"

    def __init__(
        self,
        vault_dir: Optional[Path] = None,
        master_key: Optional[str] = None,
        rotation_days: int = DEFAULT_KEY_ROTATION_DAYS
    ):
        """
        Vault 초기화

        Args:
            vault_dir: Vault 파일 저장 디렉토리 (기본: ~/.openclaw/security)
            master_key: 마스터 암호화 키 (기본: 환경변수 VAULT_MASTER_KEY)
            rotation_days: 키 순환 주기 (일)
        """
        self.vault_dir = vault_dir or Path.home() / ".openclaw" / "security"
        self.vault_dir.mkdir(parents=True, exist_ok=True)

        self.master_key = master_key or os.getenv("VAULT_MASTER_KEY")
        if not self.master_key:
            raise VaultKeyError(
                "VAULT_MASTER_KEY 환경변수 또는 master_key 인자 필요"
            )

        self.rotation_days = rotation_days
        self.vault_file = self.vault_dir / self.VAULT_FILENAME
        self.salt_file = self.vault_dir / self.SALT_FILENAME

        self._cipher: Optional[Fernet] = None
        self._cache: Dict[str, Any] = {}
        self._last_rotation: Optional[datetime] = None

        self._init_cipher()
        self._load_metadata()

    def _init_cipher(self) -> None:
        """Fernet cipher 초기화"""
        salt = self._get_or_create_salt()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self.master_key.encode()))
        self._cipher = Fernet(key)
        logger.debug("Vault cipher initialized")

    def _get_or_create_salt(self) -> bytes:
        """Salt 가져오기 또는 생성"""
        if self.salt_file.exists():
            return self.salt_file.read_bytes()

        salt = os.urandom(16)
        self.salt_file.write_bytes(salt)
        # Salt 파일 권한 제한 (소유자만 읽기)
        os.chmod(self.salt_file, 0o600)
        logger.info("New vault salt created")
        return salt

    def _load_metadata(self) -> None:
        """Vault 메타데이터 로드"""
        if not self.vault_file.exists():
            return

        try:
            encrypted_data = self.vault_file.read_bytes()
            if not encrypted_data:
                return

            decrypted = self._cipher.decrypt(encrypted_data)
            data = json.loads(decrypted.decode())
            self._last_rotation = datetime.fromisoformat(data.get("last_rotation", ""))
            logger.debug(f"Vault metadata loaded, last rotation: {self._last_rotation}")
        except Exception as e:
            logger.warning(f"Failed to load vault metadata: {e}")
            self._last_rotation = None

    def _save(self, secrets: Dict[str, Any]) -> None:
        """Vault에 암호화하여 저장"""
        data = {
            "secrets": secrets,
            "last_rotation": datetime.now().isoformat(),
            "version": "1.0",
        }
        encrypted = self._cipher.encrypt(json.dumps(data).encode())
        self.vault_file.write_bytes(encrypted)
        # Vault 파일 권한 제한
        os.chmod(self.vault_file, 0o600)

    def _load(self) -> Dict[str, Any]:
        """Vault에서 복호화하여 로드"""
        if not self.vault_file.exists():
            return {}

        try:
            encrypted_data = self.vault_file.read_bytes()
            if not encrypted_data:
                return {}

            decrypted = self._cipher.decrypt(encrypted_data)
            data = json.loads(decrypted.decode())
            return data.get("secrets", {})
        except Exception as e:
            logger.error(f"Failed to decrypt vault: {e}")
            raise VaultKeyError(f"Vault 복호화 실패: {e}")

    def store(self, key: str, value: str, metadata: Optional[Dict] = None) -> None:
        """
        민감정보 저장

        Args:
            key: 저장 키 (예: "gemini_api_key_1")
            value: 암호화할 값
            metadata: 추가 메타데이터 (만료일, 권한 등)
        """
        secrets = self._load()

        entry = {
            "value": value,
            "stored_at": datetime.now().isoformat(),
            "metadata": metadata or {},
        }

        # 이전 값이 있으면 히스토리에 저장
        if key in secrets:
            old_entry = secrets[key]
            history_key = f"{key}_history"
            if history_key not in secrets:
                secrets[history_key] = []
            secrets[history_key].append({
                "value": old_entry["value"][:10] + "...",  # 부분만 저장
                "stored_at": old_entry["stored_at"],
                "replaced_at": datetime.now().isoformat(),
            })
            # 히스토리 최대 5개 유지
            secrets[history_key] = secrets[history_key][-5:]

        secrets[key] = entry
        self._save(secrets)

        # 메모리 캐시 업데이트
        self._cache[key] = value

        logger.info(f"Secret stored: {key}")

    def retrieve(self, key: str) -> Optional[str]:
        """
        민감정보 조회

        Args:
            key: 저장 키

        Returns:
            복호화된 값 또는 None
        """
        # 메모리 캐시 먼저 확인
        if key in self._cache:
            return self._cache[key]

        secrets = self._load()
        if key not in secrets:
            return None

        value = secrets[key]["value"]
        self._cache[key] = value
        return value

    def delete(self, key: str) -> bool:
        """
        민감정보 삭제

        Args:
            key: 삭제할 키

        Returns:
            삭제 성공 여부
        """
        secrets = self._load()
        if key not in secrets:
            return False

        # 안전한 삭제를 위해 값 덮어쓰기
        entry = secrets[key]
        entry["value"] = "0" * len(entry["value"])
        entry["deleted_at"] = datetime.now().isoformat()

        del secrets[key]
        self._save(secrets)

        # 캐시에서도 삭제
        if key in self._cache:
            self._cache[key] = "0" * len(self._cache[key])
            del self._cache[key]

        logger.info(f"Secret deleted: {key}")
        return True

    def list_keys(self, include_metadata: bool = False) -> Dict[str, Any]:
        """
        저장된 키 목록 조회

        Args:
            include_metadata: 메타데이터 포함 여부

        Returns:
            키 목록 (값은 노출되지 않음)
        """
        secrets = self._load()
        result = {}

        for key, entry in secrets.items():
            if key.endswith("_history"):
                continue

            if include_metadata:
                result[key] = {
                    "stored_at": entry.get("stored_at"),
                    "metadata": entry.get("metadata", {}),
                }
            else:
                result[key] = {"stored_at": entry.get("stored_at")}

        return result

    def check_rotation_needed(self) -> bool:
        """키 순환이 필요한지 확인"""
        if not self._last_rotation:
            return True

        days_since = (datetime.now() - self._last_rotation).days
        return days_since >= self.rotation_days

    def rotate_key(self, new_master_key: Optional[str] = None) -> None:
        """
        마스터 키 순환

        Args:
            new_master_key: 새 마스터 키 (None이면 기존 키로 재암호화)
        """
        # 현재 모든 데이터 복호화
        secrets = self._load()

        if new_master_key:
            self.master_key = new_master_key
            self._init_cipher()

        # 새 키로 재암호화
        self._save(secrets)
        self._last_rotation = datetime.now()

        logger.info("Vault key rotated successfully")

    def clear_cache(self) -> None:
        """메모리 캐시 안전하게 삭제"""
        for key in list(self._cache.keys()):
            if isinstance(self._cache[key], str):
                # 문자열 덮어쓰기 (안전 삭제)
                self._cache[key] = "0" * len(self._cache[key])
        self._cache.clear()
        logger.debug("Vault cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """Vault 상태 정보"""
        secrets = self._load()
        key_count = len([k for k in secrets.keys() if not k.endswith("_history")])

        return {
            "key_count": key_count,
            "vault_file": str(self.vault_file),
            "vault_file_size": self.vault_file.stat().st_size if self.vault_file.exists() else 0,
            "last_rotation": self._last_rotation.isoformat() if self._last_rotation else None,
            "rotation_due": self.check_rotation_needed(),
            "cache_size": len(self._cache),
        }

    def migrate_from_env(self, env_prefix: str = "GEMINI_API_KEY") -> int:
        """
        환경변수에서 Vault로 마이그레이션

        Args:
            env_prefix: 마이그레이션할 환경변수 접두사

        Returns:
            마이그레이션된 키 수
        """
        migrated = 0
        for env_key, env_value in os.environ.items():
            if env_key.startswith(env_prefix) and env_value:
                vault_key = env_key.lower().replace("_", "_")
                self.store(vault_key, env_value, {
                    "source": "env_migration",
                    "migrated_at": datetime.now().isoformat(),
                })
                migrated += 1
                logger.info(f"Migrated {env_key} to vault")

        return migrated


# 싱글톤 인스턴스
_vault_instance: Optional[Vault] = None


def get_vault() -> Vault:
    """Vault 싱글톤 인스턴스 가져오기"""
    global _vault_instance
    if _vault_instance is None:
        _vault_instance = Vault()
    return _vault_instance


def init_vault(master_key: Optional[str] = None) -> Vault:
    """Vault 초기화 (명시적)"""
    global _vault_instance
    _vault_instance = Vault(master_key=master_key)
    return _vault_instance

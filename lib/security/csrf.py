"""CSRF protection for OZ_A2M."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional

from ..core.config import get_settings


class CSRFProtection:
    """CSRF token protection."""

    TOKEN_LENGTH = 32
    TOKEN_LIFETIME_HOURS = 24

    @classmethod
    def generate_token(cls, session_id: str) -> str:
        """Generate CSRF token for session."""
        settings = get_settings()
        timestamp = datetime.utcnow().isoformat()
        nonce = secrets.token_hex(16)

        data = f"{session_id}:{timestamp}:{nonce}"
        signature = hmac.new(
            settings.secret_key.encode(),
            data.encode(),
            hashlib.sha256,
        ).hexdigest()

        token = f"{timestamp}:{nonce}:{signature}"
        return token

    @classmethod
    def validate_token(cls, token: str, session_id: str) -> bool:
        """Validate CSRF token."""
        try:
            parts = token.split(":")
            if len(parts) != 3:
                return False

            timestamp_str, nonce, signature = parts

            # Check timestamp
            timestamp = datetime.fromisoformat(timestamp_str)
            if datetime.utcnow() - timestamp > timedelta(hours=cls.TOKEN_LIFETIME_HOURS):
                return False

            # Verify signature
            settings = get_settings()
            data = f"{session_id}:{timestamp_str}:{nonce}"
            expected_signature = hmac.new(
                settings.secret_key.encode(),
                data.encode(),
                hashlib.sha256,
            ).hexdigest()

            return hmac.compare_digest(signature, expected_signature)
        except Exception:
            return False


def generate_csrf_token(session_id: str) -> str:
    """Generate CSRF token."""
    return CSRFProtection.generate_token(session_id)


def validate_csrf_token(token: str, session_id: str) -> bool:
    """Validate CSRF token."""
    return CSRFProtection.validate_token(token, session_id)

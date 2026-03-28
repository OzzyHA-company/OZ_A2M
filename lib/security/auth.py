"""Authentication utilities for OZ_A2M."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

from ..core.config import get_settings
from ..core.logger import get_logger

logger = get_logger(__name__)


class APIKeyManager:
    """API key management."""

    KEY_PREFIX = "oz_"

    @classmethod
    def generate_key(cls, name: str) -> Tuple[str, str]:
        """Generate a new API key.

        Returns:
            Tuple of (full_key, hashed_key)
            full_key should be shown once to the user
            hashed_key should be stored in database
        """
        random_part = secrets.token_urlsafe(32)
        full_key = f"{cls.KEY_PREFIX}{name}_{random_part}"
        hashed_key = cls._hash_key(full_key)
        return full_key, hashed_key

    @classmethod
    def _hash_key(cls, key: str) -> str:
        """Hash API key for storage."""
        settings = get_settings()
        return hmac.new(
            settings.api_key_salt.encode(),
            key.encode(),
            hashlib.sha256,
        ).hexdigest()

    @classmethod
    def verify_key(cls, provided_key: str, stored_hash: str) -> bool:
        """Verify API key against stored hash."""
        computed_hash = cls._hash_key(provided_key)
        return hmac.compare_digest(computed_hash, stored_hash)


async def verify_api_key(api_key: str) -> Optional[dict]:
    """Verify API key and return user info.

    This is a placeholder - integrate with your user database.
    """
    if not api_key or not api_key.startswith(APIKeyManager.KEY_PREFIX):
        return None

    # TODO: Lookup in database
    # For now, just validate format
    return {
        "user_id": "placeholder",
        "permissions": ["read"],
    }

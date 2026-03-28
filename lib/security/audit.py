"""Security audit logging for OZ_A2M."""

import hashlib
import hmac
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4

from ..core.config import get_settings
from ..core.logger import get_logger
from ..data.elasticsearch_client import get_es_client

logger = get_logger(__name__)


class AuditEventType(str, Enum):
    """Audit event types."""
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    DATA_ACCESS = "data_access"
    DATA_MODIFICATION = "data_modification"
    ADMIN_ACTION = "admin_action"
    SECURITY_ALERT = "security_alert"
    API_CALL = "api_call"


class AuditSeverity(str, Enum):
    """Audit event severity."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditLogger:
    """Security audit logger."""

    def __init__(self):
        self._es = get_es_client()

    async def log(
        self,
        event_type: AuditEventType,
        severity: AuditSeverity,
        user_id: Optional[str] = None,
        action: str = "",
        resource: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        """Log an audit event."""
        event = {
            "event_id": str(uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event_type": event_type.value,
            "severity": severity.value,
            "user_id": user_id,
            "action": action,
            "resource": resource,
            "details": details or {},
            "ip_address": self._hash_ip(ip_address) if ip_address else None,
            "user_agent": user_agent,
            "success": success,
            "error_message": error_message,
        }

        # Log to Elasticsearch
        try:
            await self._es.index("audit", event)
        except Exception as e:
            logger.error("Failed to index audit event", error=str(e))

        # Also log to application logs for critical events
        if severity in (AuditSeverity.ERROR, AuditSeverity.CRITICAL):
            log_method = logger.error if severity == AuditSeverity.ERROR else logger.critical
            log_method(
                "Security audit event",
                event_type=event_type.value,
                action=action,
                user_id=user_id,
                success=success,
                error=error_message,
            )

    def _hash_ip(self, ip: str) -> str:
        """Hash IP address for privacy."""
        settings = get_settings()
        return hmac.new(
            settings.secret_key.encode(),
            ip.encode(),
            hashlib.sha256,
        ).hexdigest()[:16]

    async def log_auth(
        self,
        user_id: Optional[str],
        success: bool,
        ip_address: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Log authentication attempt."""
        severity = AuditSeverity.INFO if success else AuditSeverity.WARNING
        await self.log(
            event_type=AuditEventType.AUTHENTICATION,
            severity=severity,
            user_id=user_id,
            action="login",
            ip_address=ip_address,
            success=success,
            error_message=error_message,
        )

    async def log_data_access(
        self,
        user_id: str,
        resource: str,
        action: str = "read",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log data access."""
        await self.log(
            event_type=AuditEventType.DATA_ACCESS,
            severity=AuditSeverity.INFO,
            user_id=user_id,
            action=action,
            resource=resource,
            details=details,
        )

    async def log_admin_action(
        self,
        user_id: str,
        action: str,
        resource: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log administrative action."""
        await self.log(
            event_type=AuditEventType.ADMIN_ACTION,
            severity=AuditSeverity.WARNING,
            user_id=user_id,
            action=action,
            resource=resource,
            details=details,
        )


# Global instance
_audit_logger: Optional[AuditLogger] = None


async def get_audit_logger() -> AuditLogger:
    """Get global audit logger."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger

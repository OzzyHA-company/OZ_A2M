"""
OZ_A2M 제3부서: 보안팀 (Security & Gatekeeper Team)

API Key 외부 유출 방지, 승인되지 않은 접속 방어, 보안 유지 관리
SQLite + Elasticsearch 하이브리드 감사 로그 지원
"""

from .vault import Vault, VaultKeyError, get_vault
from .acl import AccessControl, PermissionLevel, get_acl
from .audit import (
    AuditLogger,
    get_audit_logger,
    init_audit_logger,
)
from .elasticsearch_adapter import (
    ElasticsearchAuditAdapter,
    get_elasticsearch_adapter,
    init_elasticsearch_adapter,
)
from .threat_monitor import ThreatMonitor, get_threat_monitor

__all__ = [
    # Vault
    "Vault",
    "VaultKeyError",
    # Access Control
    "AccessControl",
    "PermissionLevel",
    # Audit (SQLite + Elasticsearch)
    "AuditLogger",
    "ElasticsearchAuditAdapter",
    # Threat Monitor
    "ThreatMonitor",
    # Singleton getters
    "get_vault",
    "get_acl",
    "get_audit_logger",
    "init_audit_logger",
    "get_elasticsearch_adapter",
    "init_elasticsearch_adapter",
    "get_threat_monitor",
]

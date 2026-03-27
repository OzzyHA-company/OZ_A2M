"""
OZ_A2M 제3부서: 보안팀 - 보안 감사 로그 시스템

모든 명령어/접속 로그, 이상 행위 탐지, 대시보드 조회
SQLite + Elasticsearch 하이브리드 모드 지원
"""

import json
import logging
import sqlite3
from enum import Enum
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
import threading

logger = logging.getLogger(__name__)


class AuditEventType(Enum):
    """감사 이벤트 유형"""
    COMMAND = "command"           # 명령어 실행
    LOGIN = "login"               # 로그인 시도
    LOGOUT = "logout"             # 로그아웃
    ACCESS_DENIED = "access_denied"  # 접근 거부
    CONFIG_CHANGE = "config_change"  # 설정 변경
    KEY_ACCESS = "key_access"     # 키 접근
    DATA_EXPORT = "data_export"   # 데이터 낳출
    SUSPICIOUS = "suspicious"     # 의심스러운 행위


class AuditLogger:
    """
    보안 감사 로그 관리자 (SQLite + Elasticsearch 하이브리드)

    기능:
    - 모든 명령어/접속 로깅 (SQLite + Elasticsearch)
    - SQLite: 빠른 로컬 캐싱, 오프라인 지원
    - Elasticsearch: 중앙 집중 저장소, 검색/분석, 장기 보관
    - 이상 행위 탐지
    - 대시보드 연동
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        use_elasticsearch: bool = False,
        es_hosts: Optional[List[str]] = None
    ):
        """
        감사 로거 초기화

        Args:
            db_path: DB 파일 경로 (기본: ~/.openclaw/security/audit.db)
            use_elasticsearch: Elasticsearch 사용 여부
            es_hosts: Elasticsearch 호스트 목록
        """
        self.db_path = db_path or Path.home() / ".openclaw" / "security" / "audit.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._local = threading.local()
        self._init_db()

        # Elasticsearch 설정
        self._es = None
        self._use_elasticsearch = use_elasticsearch
        if use_elasticsearch:
            self._init_elasticsearch(es_hosts)

    def _init_elasticsearch(self, hosts: Optional[List[str]] = None):
        """Elasticsearch 어댑터 초기화"""
        try:
            from .elasticsearch_adapter import ElasticsearchAuditAdapter
            self._es = ElasticsearchAuditAdapter(hosts=hosts)
            if self._es.connect():
                logger.info("Elasticsearch audit logging enabled")
            else:
                logger.warning("Elasticsearch connection failed, falling back to SQLite only")
                self._use_elasticsearch = False
        except ImportError:
            logger.warning("elasticsearch package not installed. Run: pip install elasticsearch")
            self._use_elasticsearch = False
        except Exception as e:
            logger.error(f"Failed to initialize Elasticsearch: {e}")
            self._use_elasticsearch = False

    @contextmanager
    def _get_connection(self):
        """스레드별 DB 연결 관리"""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._local.connection.row_factory = sqlite3.Row

        try:
            yield self._local.connection
        except Exception:
            self._local.connection.rollback()
            raise

    def _init_db(self) -> None:
        """DB 스키마 초기화"""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    user_id TEXT,
                    ip_address TEXT,
                    command TEXT,
                    details TEXT,
                    result TEXT,
                    risk_score INTEGER DEFAULT 0,
                    session_id TEXT
                );

                CREATE TABLE IF NOT EXISTS access_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    user_id TEXT,
                    attempt_type TEXT NOT NULL,
                    success BOOLEAN NOT NULL,
                    reason TEXT
                );

                CREATE TABLE IF NOT EXISTS security_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    source_ip TEXT,
                    user_id TEXT,
                    description TEXT,
                    resolved BOOLEAN DEFAULT FALSE,
                    resolved_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);
                CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id);
                CREATE INDEX IF NOT EXISTS idx_audit_ip ON audit_logs(ip_address);
                CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_logs(event_type);
                CREATE INDEX IF NOT EXISTS idx_access_ip ON access_attempts(ip_address);
                CREATE INDEX IF NOT EXISTS idx_access_time ON access_attempts(timestamp);
                CREATE INDEX IF NOT EXISTS idx_alerts_unresolved ON security_alerts(resolved);
            """)
            conn.commit()

        logger.debug("Audit database initialized")

    def log_command(
        self,
        user_id: Optional[str],
        ip_address: Optional[str],
        command: str,
        details: Optional[Dict] = None,
        result: Optional[str] = None,
        risk_score: int = 0,
        session_id: Optional[str] = None
    ) -> int:
        """
        명령어 실행 로그 기록 (SQLite + Elasticsearch)

        Args:
            user_id: 사용자 ID
            ip_address: IP 주소
            command: 실행된 명령어
            details: 상세 정보 (JSON)
            result: 실행 결과
            risk_score: 위험 점수 (0-100)
            session_id: 세션 ID

        Returns:
            로그 ID
        """
        # SQLite에 저장
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_logs
                (timestamp, event_type, user_id, ip_address, command, details, result, risk_score, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(),
                    AuditEventType.COMMAND.value,
                    user_id,
                    ip_address,
                    command,
                    json.dumps(details) if details else None,
                    result,
                    risk_score,
                    session_id
                )
            )
            conn.commit()
            log_id = cursor.lastrowid

        # Elasticsearch에도 저장 (비동기로 처리 가능)
        if self._use_elasticsearch and self._es:
            try:
                self._es.index_command_log(
                    user_id=user_id,
                    ip_address=ip_address,
                    command=command,
                    details=details,
                    result=result,
                    risk_score=risk_score,
                    session_id=session_id
                )
            except Exception as e:
                logger.warning(f"Failed to index command log to Elasticsearch: {e}")

        return log_id

    def log_access_attempt(
        self,
        ip_address: str,
        attempt_type: str,
        success: bool,
        user_id: Optional[str] = None,
        reason: Optional[str] = None
    ) -> int:
        """
        접근 시도 로그 기록 (SQLite + Elasticsearch)

        Args:
            ip_address: IP 주소
            attempt_type: 시도 유형 (login, api_call, etc)
            success: 성공 여부
            user_id: 사용자 ID
            reason: 실패 사유

        Returns:
            로그 ID
        """
        # SQLite에 저장
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO access_attempts
                (timestamp, ip_address, user_id, attempt_type, success, reason)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(),
                    ip_address,
                    user_id,
                    attempt_type,
                    success,
                    reason
                )
            )
            conn.commit()
            log_id = cursor.lastrowid

        # Elasticsearch에도 저장
        if self._use_elasticsearch and self._es:
            try:
                self._es.index_access_attempt(
                    ip_address=ip_address,
                    attempt_type=attempt_type,
                    success=success,
                    user_id=user_id,
                    reason=reason
                )
            except Exception as e:
                logger.warning(f"Failed to index access attempt to Elasticsearch: {e}")

        # 실패 시 위협 점수 계산
        if not success:
            self._check_failed_attempts(ip_address, user_id)

        return log_id

    def log_security_alert(
        self,
        alert_type: str,
        severity: str,  # low, medium, high, critical
        description: str,
        source_ip: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> int:
        """
        보안 알림 기록 (SQLite + Elasticsearch)

        Args:
            alert_type: 알림 유형
            severity: 심각도
            description: 설명
            source_ip: 출처 IP
            user_id: 관련 사용자

        Returns:
            알림 ID
        """
        # SQLite에 저장
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO security_alerts
                (timestamp, alert_type, severity, source_ip, user_id, description)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(),
                    alert_type,
                    severity,
                    source_ip,
                    user_id,
                    description
                )
            )
            conn.commit()
            alert_id = cursor.lastrowid

        # Elasticsearch에도 저장
        if self._use_elasticsearch and self._es:
            try:
                self._es.index_security_alert(
                    alert_type=alert_type,
                    severity=severity,
                    description=description,
                    source_ip=source_ip,
                    user_id=user_id
                )
            except Exception as e:
                logger.warning(f"Failed to index security alert to Elasticsearch: {e}")

        logger.warning(f"Security alert: [{severity}] {alert_type} - {description}")
        return alert_id

    def _check_failed_attempts(self, ip_address: str, user_id: Optional[str]) -> None:
        """실패한 시도가 임계값을 초과하는지 확인"""
        with self._get_connection() as conn:
            # 5분 내 실패 횟수
            five_min_ago = (datetime.now() - timedelta(minutes=5)).isoformat()

            cursor = conn.execute(
                """
                SELECT COUNT(*) as count FROM access_attempts
                WHERE ip_address = ? AND success = FALSE AND timestamp > ?
                """,
                (ip_address, five_min_ago)
            )
            result = cursor.fetchone()
            failed_count = result["count"] if result else 0

            if failed_count >= 5:
                self.log_security_alert(
                    alert_type="brute_force_attempt",
                    severity="high",
                    description=f"Multiple failed access attempts from {ip_address} ({failed_count} times in 5 min)",
                    source_ip=ip_address,
                    user_id=user_id
                )

    def get_recent_logs(
        self,
        hours: int = 24,
        event_type: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        최근 로그 조회

        Args:
            hours: 조회할 시간 범위
            event_type: 이벤트 유형 필터
            user_id: 사용자 필터
            limit: 최대 개수

        Returns:
            로그 목록
        """
        since = (datetime.now() - timedelta(hours=hours)).isoformat()

        query = "SELECT * FROM audit_logs WHERE timestamp > ?"
        params = [since]

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [dict(row) for row in rows]

    def get_failed_attempts(
        self,
        minutes: int = 60,
        ip_address: Optional[str] = None
    ) -> List[Dict]:
        """
        실패한 접근 시도 조회

        Args:
            minutes: 조회할 분 범위
            ip_address: 특정 IP 필터

        Returns:
            실패 시도 목록
        """
        since = (datetime.now() - timedelta(minutes=minutes)).isoformat()

        query = """
            SELECT ip_address, COUNT(*) as count, MAX(timestamp) as last_attempt
            FROM access_attempts
            WHERE timestamp > ? AND success = FALSE
        """
        params = [since]

        if ip_address:
            query += " AND ip_address = ?"
            params.append(ip_address)

        query += " GROUP BY ip_address ORDER BY count DESC"

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_security_alerts(
        self,
        unresolved_only: bool = True,
        severity: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        보안 알림 조회

        Args:
            unresolved_only: 미해결 알림만
            severity: 심각도 필터
            limit: 최대 개수

        Returns:
            알림 목록
        """
        query = "SELECT * FROM security_alerts WHERE 1=1"
        params = []

        if unresolved_only:
            query += " AND resolved = FALSE"

        if severity:
            query += " AND severity = ?"
            params.append(severity)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def resolve_alert(self, alert_id: int, resolved_by: Optional[str] = None) -> bool:
        """알림 해결 표시"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE security_alerts
                SET resolved = TRUE, resolved_at = ?
                WHERE id = ?
                """,
                (datetime.now().isoformat(), alert_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_stats(self) -> Dict[str, Any]:
        """감사 로그 통계 (SQLite + Elasticsearch)"""
        with self._get_connection() as conn:
            stats = {
                "sqlite": {},
                "elasticsearch": None
            }

            # SQLite 통계
            # 전체 로그 수
            cursor = conn.execute("SELECT COUNT(*) as count FROM audit_logs")
            stats["sqlite"]["total_logs"] = cursor.fetchone()["count"]

            # 오늘 로그 수
            today = datetime.now().strftime("%Y-%m-%d")
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM audit_logs WHERE date(timestamp) = ?",
                (today,)
            )
            stats["sqlite"]["today_logs"] = cursor.fetchone()["count"]

            # 미해결 알림
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM security_alerts WHERE resolved = FALSE"
            )
            stats["sqlite"]["unresolved_alerts"] = cursor.fetchone()["count"]

            # 최근 1시간 실패 시도
            hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
            cursor = conn.execute(
                """SELECT COUNT(*) as count FROM access_attempts
                   WHERE timestamp > ? AND success = FALSE""",
                (hour_ago,)
            )
            stats["sqlite"]["recent_failed_attempts"] = cursor.fetchone()["count"]

            # 고위험 이벤트 (risk_score >= 70)
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM audit_logs WHERE risk_score >= 70"
            )
            stats["sqlite"]["high_risk_events"] = cursor.fetchone()["count"]

        # Elasticsearch 통계
        if self._use_elasticsearch and self._es:
            try:
                stats["elasticsearch"] = self._es.get_stats()
            except Exception as e:
                logger.warning(f"Failed to get Elasticsearch stats: {e}")
                stats["elasticsearch"] = {"error": str(e)}

        return stats

    def search_logs_elasticsearch(
        self,
        query: str,
        hours: int = 24,
        event_type: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Elasticsearch를 사용한 고급 로그 검색

        Args:
            query: 검색어
            hours: 검색할 시간 범위
            event_type: 이벤트 유형 필터
            user_id: 사용자 필터
            limit: 최대 결과 수

        Returns:
            검색 결과 목록
        """
        if not self._use_elasticsearch or not self._es:
            logger.warning("Elasticsearch not enabled, using SQLite fallback")
            # SQLite fallback
            return self.get_recent_logs(hours=hours, event_type=event_type, user_id=user_id, limit=limit)

        return self._es.search_logs(
            query=query,
            hours=hours,
            event_type=event_type,
            user_id=user_id,
            limit=limit
        )

    def aggregate_event_types(self, hours: int = 24) -> Dict[str, int]:
        """이벤트 유형별 집계 (Elasticsearch 우선)"""
        if self._use_elasticsearch and self._es:
            try:
                return self._es.aggregate_by_event_type(hours=hours)
            except Exception as e:
                logger.warning(f"Elasticsearch aggregation failed, using SQLite: {e}")

        # SQLite fallback
        with self._get_connection() as conn:
            since = (datetime.now() - timedelta(hours=hours)).isoformat()
            cursor = conn.execute(
                """SELECT event_type, COUNT(*) as count
                   FROM audit_logs
                   WHERE timestamp > ?
                   GROUP BY event_type""",
                (since,)
            )
            return {row["event_type"]: row["count"] for row in cursor.fetchall()}

    def get_failed_attempts_aggregated(
        self,
        hours: int = 24,
        min_attempts: int = 3
    ) -> List[Dict]:
        """IP별 실패 시도 집계 (브루트 포스 탐지)"""
        if self._use_elasticsearch and self._es:
            try:
                return self._es.get_failed_attempts_by_ip(
                    hours=hours,
                    min_attempts=min_attempts
                )
            except Exception as e:
                logger.warning(f"Elasticsearch aggregation failed, using SQLite: {e}")

        # SQLite fallback
        with self._get_connection() as conn:
            since = (datetime.now() - timedelta(hours=hours)).isoformat()
            cursor = conn.execute(
                """SELECT ip_address, COUNT(*) as count, MAX(timestamp) as last_attempt
                   FROM access_attempts
                   WHERE timestamp > ? AND success = FALSE
                   GROUP BY ip_address
                   HAVING COUNT(*) >= ?
                   ORDER BY count DESC""",
                (since, min_attempts)
            )
            return [
                {
                    "ip": row["ip_address"],
                    "count": row["count"],
                    "last_attempt": row["last_attempt"]
                }
                for row in cursor.fetchall()
            ]

    def cleanup_old_logs(self, days: int = 90) -> int:
        """
        오래된 로그 정리

        Args:
            days: 보관할 일수

        Returns:
            삭제된 로그 수
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM audit_logs WHERE timestamp < ?",
                (cutoff,)
            )
            deleted_logs = cursor.rowcount

            cursor = conn.execute(
                "DELETE FROM access_attempts WHERE timestamp < ?",
                (cutoff,)
            )
            deleted_attempts = cursor.rowcount

            conn.commit()

            logger.info(f"Cleaned up {deleted_logs} old audit logs, {deleted_attempts} access attempts")
            return deleted_logs + deleted_attempts


# 싱글톤 인스턴스
_audit_instance: Optional[AuditLogger] = None


def get_audit_logger(
    use_elasticsearch: bool = False,
    es_hosts: Optional[List[str]] = None
) -> AuditLogger:
    """AuditLogger 싱글톤 인스턴스 가져오기

    Args:
        use_elasticsearch: Elasticsearch 사용 여부
        es_hosts: Elasticsearch 호스트 목록 (예: ['localhost:9200'])
    """
    global _audit_instance
    if _audit_instance is None:
        _audit_instance = AuditLogger(
            use_elasticsearch=use_elasticsearch,
            es_hosts=es_hosts
        )
    return _audit_instance


def init_audit_logger(
    db_path: Optional[Path] = None,
    use_elasticsearch: bool = False,
    es_hosts: Optional[List[str]] = None
) -> AuditLogger:
    """AuditLogger 초기화 (명시적 설정)"""
    global _audit_instance
    _audit_instance = AuditLogger(
        db_path=db_path,
        use_elasticsearch=use_elasticsearch,
        es_hosts=es_hosts
    )
    return _audit_instance

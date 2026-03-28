"""수리 이력 관리 - 모든 수리 작업 기록 및 통계"""
import sqlite3
import threading
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass, asdict
from pathlib import Path
from contextlib import contextmanager
from enum import Enum

logger = logging.getLogger(__name__)


class RepairType(Enum):
    """수리 유형"""
    AUTO_HEAL = "auto_heal"
    MANUAL_FIX = "manual_fix"
    COMPONENT_REPLACE = "replace"
    CONFIG_RESTORE = "config_restore"
    REBOOT = "reboot"
    ROLLBACK = "rollback"


class RepairStatus(Enum):
    """수리 상태"""
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    PARTIAL = "partial"


@dataclass
class RepairRecord:
    """수리 기록"""
    repair_id: str
    timestamp: datetime
    component: str
    repair_type: RepairType
    status: RepairStatus
    description: str
    diagnosis: Optional[Dict[str, Any]] = None
    actions_taken: List[str] = None
    duration_seconds: Optional[float] = None
    technician: str = "system"
    before_state: Optional[Dict[str, Any]] = None
    after_state: Optional[Dict[str, Any]] = None
    rollback_info: Optional[Dict[str, Any]] = None


class RepairLog:
    """수리 이력 관리자"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = Path.home() / ".oz_a2m" / "repair_log.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._local = threading.local()

        self._init_db()

    def _init_db(self):
        """데이터베이스 초기화"""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS repairs (
                    repair_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    component TEXT NOT NULL,
                    repair_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    description TEXT,
                    diagnosis TEXT,
                    actions_taken TEXT,
                    duration_seconds REAL,
                    technician TEXT DEFAULT 'system',
                    before_state TEXT,
                    after_state TEXT,
                    rollback_info TEXT
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_repairs_component
                ON repairs(component)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_repairs_timestamp
                ON repairs(timestamp)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_repairs_status
                ON repairs(status)
            """)

    @contextmanager
    def _get_connection(self):
        """스레드별 연결 관리"""
        if not hasattr(self._local, 'connection'):
            self._local.connection = sqlite3.connect(str(self.db_path))

        try:
            yield self._local.connection
        except Exception:
            self._local.connection.rollback()
            raise

    def start_repair(
        self,
        component: str,
        repair_type: RepairType,
        description: str,
        diagnosis: Optional[Any] = None,
        technician: str = "system",
        before_state: Optional[Dict] = None
    ) -> str:
        """수리 시작 기록"""
        import uuid

        repair_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()

        diagnosis_dict = None
        if diagnosis:
            if hasattr(diagnosis, '__dataclass_fields__'):
                diagnosis_dict = asdict(diagnosis)
            else:
                diagnosis_dict = dict(diagnosis)

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO repairs (
                    repair_id, timestamp, component, repair_type, status,
                    description, diagnosis, technician, before_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                repair_id,
                timestamp,
                component,
                repair_type.value,
                RepairStatus.IN_PROGRESS.value,
                description,
                json.dumps(diagnosis_dict) if diagnosis_dict else None,
                technician,
                json.dumps(before_state) if before_state else None
            ))
            conn.commit()

        logger.info(f"Repair started: {repair_id} for {component}")
        return repair_id

    def finish_repair(
        self,
        repair_id: str,
        success: bool,
        details: str = "",
        after_state: Optional[Dict] = None,
        duration_seconds: Optional[float] = None
    ):
        """수리 완료 기록"""
        status = RepairStatus.SUCCESS if success else RepairStatus.FAILED

        with self._get_connection() as conn:
            conn.execute("""
                UPDATE repairs
                SET status = ?,
                    after_state = ?,
                    duration_seconds = ?,
                    description = description || '\nResult: ' || ?
                WHERE repair_id = ?
            """, (
                status.value,
                json.dumps(after_state) if after_state else None,
                duration_seconds,
                details,
                repair_id
            ))
            conn.commit()

        logger.info(f"Repair finished: {repair_id} - {status.value}")

    def add_actions(self, repair_id: str, actions: List[str]):
        """수리 액션 추가"""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE repairs
                SET actions_taken = ?
                WHERE repair_id = ?
            """, (json.dumps(actions), repair_id))
            conn.commit()

    def get_repairs(
        self,
        component: Optional[str] = None,
        repair_type: Optional[RepairType] = None,
        status: Optional[RepairStatus] = None,
        since: Optional[datetime] = None,
        limit: int = 100
    ) -> List[RepairRecord]:
        """수리 이력 조회"""
        query = "SELECT * FROM repairs WHERE 1=1"
        params = []

        if component:
            query += " AND component = ?"
            params.append(component)

        if repair_type:
            query += " AND repair_type = ?"
            params.append(repair_type.value)

        if status:
            query += " AND status = ?"
            params.append(status.value)

        if since:
            query += " AND timestamp >= ?"
            params.append(since.isoformat())

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        records = []
        for row in rows:
            records.append(self._row_to_record(row))

        return records

    def get_repair_stats(self, days: int = 30) -> Dict[str, Any]:
        """수리 통계"""
        from datetime import timedelta
        since = datetime.now() - timedelta(days=days)

        with self._get_connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM repairs WHERE timestamp >= ?",
                (since.isoformat(),)
            ).fetchone()[0]

            success = conn.execute(
                "SELECT COUNT(*) FROM repairs WHERE timestamp >= ? AND status = ?",
                (since.isoformat(), RepairStatus.SUCCESS.value)
            ).fetchone()[0]

            failed = conn.execute(
                "SELECT COUNT(*) FROM repairs WHERE timestamp >= ? AND status = ?",
                (since.isoformat(), RepairStatus.FAILED.value)
            ).fetchone()[0]

            cursor = conn.execute("""
                SELECT component, COUNT(*) as count
                FROM repairs
                WHERE timestamp >= ?
                GROUP BY component
                ORDER BY count DESC
            """, (since.isoformat(),))
            by_component = {row[0]: row[1] for row in cursor.fetchall()}

            cursor = conn.execute("""
                SELECT repair_type, COUNT(*) as count
                FROM repairs
                WHERE timestamp >= ?
                GROUP BY repair_type
            """, (since.isoformat(),))
            by_type = {row[0]: row[1] for row in cursor.fetchall()}

        return {
            "period_days": days,
            "total_repairs": total,
            "successful": success,
            "failed": failed,
            "success_rate": success / total * 100 if total > 0 else 0,
            "by_component": by_component,
            "by_type": by_type,
        }

    def get_mttr(self, component: Optional[str] = None) -> float:
        """Mean Time To Repair (평균 수리 시간)"""
        query = "SELECT AVG(duration_seconds) FROM repairs WHERE status = ?"
        params = [RepairStatus.SUCCESS.value]

        if component:
            query += " AND component = ?"
            params.append(component)

        with self._get_connection() as conn:
            result = conn.execute(query, params).fetchone()[0]

        return result or 0.0

    def get_components_needing_attention(self, threshold: int = 3) -> List[str]:
        """주의가 필요한 컴포넌트 (임계값 초과 수리)"""
        from datetime import timedelta
        since = datetime.now() - timedelta(days=7)

        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT component, COUNT(*) as count
                FROM repairs
                WHERE timestamp >= ? AND status != ?
                GROUP BY component
                HAVING count >= ?
                ORDER BY count DESC
            """, (since.isoformat(), RepairStatus.SUCCESS.value, threshold))

            return [row[0] for row in cursor.fetchall()]

    def _row_to_record(self, row) -> RepairRecord:
        """DB row를 RepairRecord로 변환"""
        return RepairRecord(
            repair_id=row[0],
            timestamp=datetime.fromisoformat(row[1]),
            component=row[2],
            repair_type=RepairType(row[3]),
            status=RepairStatus(row[4]),
            description=row[5],
            diagnosis=json.loads(row[6]) if row[6] else None,
            actions_taken=json.loads(row[7]) if row[7] else [],
            duration_seconds=row[8],
            technician=row[9],
            before_state=json.loads(row[10]) if row[10] else None,
            after_state=json.loads(row[11]) if row[11] else None,
            rollback_info=json.loads(row[12]) if row[12] else None,
        )

    def close(self):
        """연결 종료"""
        if hasattr(self._local, 'connection'):
            self._local.connection.close()
            delattr(self._local, 'connection')

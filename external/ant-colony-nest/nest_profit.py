"""
Nest Profit Module - Ant-Colony Nest 수익 추적 확장 모듈

원금-보존 리워드 시스템 핵심 컴포넌트
- 원금/수익 명확히 분리 추적
- 실시간 출금 상태 관리
- 자본 재분배 히스토리 기록
"""

import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import sqlite3
from pathlib import Path

import redis.asyncio as redis


class WithdrawalStatus(Enum):
    """출금 상태"""
    PENDING = "pending"           # 출금 대기
    PROCESSING = "processing"     # 출금 진행 중
    COMPLETED = "completed"       # 출금 완료
    FAILED = "failed"             # 출금 실패
    SCHEDULED = "scheduled"       # 예약 출금


class ProfitType(Enum):
    """수익 유형"""
    REALIZED = "realized"         # 실현 수익
    UNREALIZED = "unrealized"     # 미실현 수익
    WITHDRAWN = "withdrawn"       # 출금 완료 수익


@dataclass
class ProfitRecord:
    """수익 기록 데이터 클래스"""
    bot_id: str
    base_capital: float           # 원금 (변하지 않음)
    profit_amount: float          # 수익액
    profit_type: ProfitType       # 수익 유형
    timestamp: datetime
    trade_id: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    withdrawal_status: WithdrawalStatus = WithdrawalStatus.PENDING
    withdrawal_tx_id: Optional[str] = None
    withdrawal_completed_at: Optional[datetime] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "bot_id": self.bot_id,
            "base_capital": self.base_capital,
            "profit_amount": self.profit_amount,
            "profit_type": self.profit_type.value,
            "timestamp": self.timestamp.isoformat(),
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "side": self.side,
            "withdrawal_status": self.withdrawal_status.value,
            "withdrawal_tx_id": self.withdrawal_tx_id,
            "withdrawal_completed_at": self.withdrawal_completed_at.isoformat() if self.withdrawal_completed_at else None,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProfitRecord":
        """딕셔너리에서 생성"""
        return cls(
            bot_id=data["bot_id"],
            base_capital=data["base_capital"],
            profit_amount=data["profit_amount"],
            profit_type=ProfitType(data["profit_type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            trade_id=data.get("trade_id"),
            symbol=data.get("symbol"),
            side=data.get("side"),
            withdrawal_status=WithdrawalStatus(data.get("withdrawal_status", "pending")),
            withdrawal_tx_id=data.get("withdrawal_tx_id"),
            withdrawal_completed_at=datetime.fromisoformat(data["withdrawal_completed_at"]) if data.get("withdrawal_completed_at") else None,
            notes=data.get("notes"),
        )


@dataclass
class BotCapitalState:
    """봇 자본 상태"""
    bot_id: str
    base_capital: float           # 원금 (고정)
    current_capital: float        # 현재 자본 (원금 + 미출금 수익)
    total_realized_profit: float  # 총 실현 수익
    total_withdrawn: float        # 총 출금액
    pending_withdrawal: float     # 출금 대기액
    last_updated: datetime
    daily_profits: List[Dict] = field(default_factory=list)  # 최근 30일 일별 수익

    @property
    def available_to_withdraw(self) -> float:
        """출금 가능액 (미출금 수익)"""
        return max(0, self.total_realized_profit - self.total_withdrawn)

    @property
    def total_return_pct(self) -> float:
        """총 수익률 (%)"""
        if self.base_capital <= 0:
            return 0.0
        return ((self.current_capital - self.base_capital) / self.base_capital) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bot_id": self.bot_id,
            "base_capital": self.base_capital,
            "current_capital": self.current_capital,
            "total_realized_profit": self.total_realized_profit,
            "total_withdrawn": self.total_withdrawn,
            "pending_withdrawal": self.pending_withdrawal,
            "available_to_withdraw": self.available_to_withdraw,
            "total_return_pct": self.total_return_pct,
            "last_updated": self.last_updated.isoformat(),
            "daily_profits": self.daily_profits,
        }


class ProfitTracker:
    """
    수익 추적 관리자

    핵심 기능:
    1. 원금/수익 명확히 분리 추적
    2. 출금 가능 잔액 실시간 계산
    3. 일일/주간/월간 수익 집계
    4. 출금 상태 관리
    """

    def __init__(self, redis_client: redis.Redis, db_path: str = "data/profit_tracking.db"):
        self.redis = redis_client
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """SQLite 데이터베이스 초기화"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 수익 기록 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS profit_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id TEXT NOT NULL,
                base_capital REAL NOT NULL,
                profit_amount REAL NOT NULL,
                profit_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                trade_id TEXT,
                symbol TEXT,
                side TEXT,
                withdrawal_status TEXT DEFAULT 'pending',
                withdrawal_tx_id TEXT,
                withdrawal_completed_at TEXT,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 봇 자본 상태 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_capital_states (
                bot_id TEXT PRIMARY KEY,
                base_capital REAL NOT NULL,
                current_capital REAL NOT NULL,
                total_realized_profit REAL DEFAULT 0,
                total_withdrawn REAL DEFAULT 0,
                pending_withdrawal REAL DEFAULT 0,
                last_updated TEXT NOT NULL
            )
        """)

        # 일별 수익 집계 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_profits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id TEXT NOT NULL,
                date TEXT NOT NULL,
                realized_profit REAL DEFAULT 0,
                withdrawn_amount REAL DEFAULT 0,
                trade_count INTEGER DEFAULT 0,
                UNIQUE(bot_id, date)
            )
        """)

        # 출금 히스토리 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS withdrawal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL,
                destination TEXT NOT NULL,
                tx_id TEXT,
                status TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            )
        """)

        conn.commit()
        conn.close()
        print(f"📊 Profit tracking database initialized: {self.db_path}")

    # ========== 수익 기록 ==========

    async def record_profit(
        self,
        bot_id: str,
        base_capital: float,
        profit_amount: float,
        trade_id: Optional[str] = None,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        notes: Optional[str] = None
    ) -> ProfitRecord:
        """수익 기록 저장"""
        record = ProfitRecord(
            bot_id=bot_id,
            base_capital=base_capital,
            profit_amount=profit_amount,
            profit_type=ProfitType.REALIZED,
            timestamp=datetime.utcnow(),
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            notes=notes,
        )

        # Redis에 저장 (실시간)
        await self.redis.lpush(f"nest:profits:{bot_id}", json.dumps(record.to_dict()))
        await self.redis.expire(f"nest:profits:{bot_id}", 86400 * 30)  # 30일 유지

        # SQLite에 저장 (영구) - 단일 커넥션 사용
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO profit_records
                (bot_id, base_capital, profit_amount, profit_type, timestamp, trade_id, symbol, side, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.bot_id, record.base_capital, record.profit_amount,
                record.profit_type.value, record.timestamp.isoformat(),
                record.trade_id, record.symbol, record.side, record.notes
            ))

            # 봇 자본 상태 업데이트 (동일 커넥션)
            cursor.execute("""
                INSERT INTO bot_capital_states (bot_id, base_capital, current_capital, total_realized_profit, last_updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(bot_id) DO UPDATE SET
                    current_capital = current_capital + ?,
                    total_realized_profit = total_realized_profit + ?,
                    pending_withdrawal = pending_withdrawal + ?,
                    last_updated = ?
            """, (bot_id, base_capital, profit_amount, profit_amount, datetime.utcnow().isoformat(),
                  profit_amount, profit_amount, profit_amount, datetime.utcnow().isoformat()))

            # 일별 수익 집계 업데이트
            today = datetime.utcnow().date().isoformat()
            cursor.execute("""
                INSERT INTO daily_profits (bot_id, date, realized_profit, trade_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(bot_id, date) DO UPDATE SET
                    realized_profit = realized_profit + ?,
                    trade_count = trade_count + 1
            """, (bot_id, today, profit_amount, profit_amount))

            conn.commit()
        finally:
            conn.close()

        # 원금 보존 검증 (별도 검증)
        await self._verify_principal_preservation(bot_id, base_capital)

        print(f"💰 Profit recorded: {bot_id} +${profit_amount:.4f} (Base: ${base_capital:.2f})")
        return record

    async def _verify_principal_preservation(self, bot_id: str, expected_base: float):
        """원금 보존 검증"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT base_capital FROM bot_capital_states WHERE bot_id = ?", (bot_id,))
        result = cursor.fetchone()
        conn.close()

        if result and result[0] != expected_base:
            # 원금 변경 감지 - 심각한 오류
            print(f"🚨 CRITICAL: Base capital changed for {bot_id}! Expected: ${expected_base}, Found: ${result[0]}")
            # 알림 발행
            await self.redis.publish("nest:alerts:principal", json.dumps({
                "bot_id": bot_id,
                "expected": expected_base,
                "actual": result[0],
                "timestamp": datetime.utcnow().isoformat()
            }))

    # ========== 출금 관리 ==========

    async def mark_withdrawal_processing(
        self,
        bot_id: str,
        amount: float,
        tx_id: Optional[str] = None
    ) -> bool:
        """출금 진행 중 표시"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 출금 대기 중인 수익 레코드 업데이트
        cursor.execute("""
            UPDATE profit_records
            SET withdrawal_status = 'processing', withdrawal_tx_id = ?
            WHERE bot_id = ? AND withdrawal_status = 'pending'
            ORDER BY timestamp ASC
            LIMIT 1
        """, (tx_id, bot_id))

        # 봇 자본 상태 업데이트
        cursor.execute("""
            UPDATE bot_capital_states
            SET pending_withdrawal = pending_withdrawal + ?,
                last_updated = ?
            WHERE bot_id = ?
        """, (amount, datetime.utcnow().isoformat(), bot_id))

        conn.commit()
        conn.close()

        # Redis 업데이트
        await self.redis.hset(f"nest:withdrawals:processing", bot_id, json.dumps({
            "amount": amount,
            "tx_id": tx_id,
            "started_at": datetime.utcnow().isoformat()
        }))

        return True

    async def complete_withdrawal(
        self,
        bot_id: str,
        amount: float,
        currency: str,
        destination: str,
        tx_id: Optional[str] = None
    ) -> bool:
        """출금 완료 처리"""
        now = datetime.utcnow()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 수익 레코드 업데이트
        cursor.execute("""
            UPDATE profit_records
            SET withdrawal_status = 'completed',
                withdrawal_completed_at = ?
            WHERE bot_id = ? AND withdrawal_status = 'processing'
            AND withdrawal_tx_id = ?
        """, (now.isoformat(), bot_id, tx_id))

        # 봇 자본 상태 업데이트
        cursor.execute("""
            UPDATE bot_capital_states
            SET current_capital = current_capital - ?,
                total_withdrawn = total_withdrawn + ?,
                pending_withdrawal = pending_withdrawal - ?,
                last_updated = ?
            WHERE bot_id = ?
        """, (amount, amount, amount, now.isoformat(), bot_id))

        # 출금 히스토리 기록
        cursor.execute("""
            INSERT INTO withdrawal_history
            (bot_id, amount, currency, destination, tx_id, status, completed_at)
            VALUES (?, ?, ?, ?, ?, 'completed', ?)
        """, (bot_id, amount, currency, destination, tx_id, now.isoformat()))

        # 일별 출금 집계 업데이트
        today = now.date().isoformat()
        cursor.execute("""
            INSERT INTO daily_profits (bot_id, date, withdrawn_amount)
            VALUES (?, ?, ?)
            ON CONFLICT(bot_id, date) DO UPDATE SET
                withdrawn_amount = withdrawn_amount + ?
        """, (bot_id, today, amount, amount))

        conn.commit()
        conn.close()

        # Redis 업데이트
        await self.redis.hincrbyfloat(f"nest:withdrawals:completed", bot_id, amount)
        await self.redis.hdel(f"nest:withdrawals:processing", bot_id)

        # 원금 복원 검증
        await self._reset_to_principal(bot_id)

        print(f"✅ Withdrawal completed: {bot_id} ${amount:.4f} {currency} → {destination}")
        return True

    async def _reset_to_principal(self, bot_id: str):
        """출금 후 원금으로 리셋"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT base_capital, current_capital FROM bot_capital_states WHERE bot_id = ?
        """, (bot_id,))
        result = cursor.fetchone()

        if result:
            base_capital, current_capital = result
            # 원금으로 정확히 맞춤
            cursor.execute("""
                UPDATE bot_capital_states
                SET current_capital = base_capital,
                    last_updated = ?
                WHERE bot_id = ?
            """, (datetime.utcnow().isoformat(), bot_id))
            conn.commit()

            print(f"🔄 Reset to principal: {bot_id} ${current_capital:.4f} → ${base_capital:.4f}")

        conn.close()

    # ========== 조회 기능 ==========

    async def get_bot_capital_state(self, bot_id: str) -> Optional[BotCapitalState]:
        """봇 자본 상태 조회"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT bot_id, base_capital, current_capital, total_realized_profit,
                   total_withdrawn, pending_withdrawal, last_updated
            FROM bot_capital_states WHERE bot_id = ?
        """, (bot_id,))

        result = cursor.fetchone()
        conn.close()

        if not result:
            return None

        return BotCapitalState(
            bot_id=result[0],
            base_capital=result[1],
            current_capital=result[2],
            total_realized_profit=result[3],
            total_withdrawn=result[4],
            pending_withdrawal=result[5],
            last_updated=datetime.fromisoformat(result[6]),
        )

    async def get_pending_withdrawals(self, bot_id: Optional[str] = None) -> List[Dict]:
        """출금 대기 목록 조회"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if bot_id:
            cursor.execute("""
                SELECT bot_id, profit_amount, timestamp, trade_id, symbol
                FROM profit_records
                WHERE bot_id = ? AND withdrawal_status = 'pending'
                ORDER BY timestamp ASC
            """, (bot_id,))
        else:
            cursor.execute("""
                SELECT bot_id, profit_amount, timestamp, trade_id, symbol
                FROM profit_records
                WHERE withdrawal_status = 'pending'
                ORDER BY timestamp ASC
            """)

        results = cursor.fetchall()
        conn.close()

        return [
            {
                "bot_id": r[0],
                "amount": r[1],
                "timestamp": r[2],
                "trade_id": r[3],
                "symbol": r[4],
            }
            for r in results
        ]

    async def get_daily_profit_summary(self, date: Optional[str] = None) -> Dict[str, Any]:
        """일별 수익 집계"""
        if date is None:
            date = datetime.utcnow().date().isoformat()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT bot_id, realized_profit, withdrawn_amount, trade_count
            FROM daily_profits
            WHERE date = ?
        """, (date,))

        results = cursor.fetchall()
        conn.close()

        bot_stats = {}
        total_realized = 0
        total_withdrawn = 0
        total_trades = 0

        for r in results:
            bot_stats[r[0]] = {
                "realized_profit": r[1],
                "withdrawn_amount": r[2],
                "trade_count": r[3],
            }
            total_realized += r[1]
            total_withdrawn += r[2]
            total_trades += r[3]

        return {
            "date": date,
            "total_realized_profit": total_realized,
            "total_withdrawn": total_withdrawn,
            "total_trades": total_trades,
            "bot_count": len(bot_stats),
            "bot_stats": bot_stats,
        }

    async def get_profit_history(
        self,
        bot_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> List[ProfitRecord]:
        """수익 히스토리 조회"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = """
            SELECT bot_id, base_capital, profit_amount, profit_type, timestamp,
                   trade_id, symbol, side, withdrawal_status, withdrawal_tx_id,
                   withdrawal_completed_at, notes
            FROM profit_records
            WHERE 1=1
        """
        params = []

        if bot_id:
            query += " AND bot_id = ?"
            params.append(bot_id)

        if start_date:
            query += " AND date(timestamp) >= ?"
            params.append(start_date)

        if end_date:
            query += " AND date(timestamp) <= ?"
            params.append(end_date)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()

        records = []
        for r in results:
            record = ProfitRecord(
                bot_id=r[0],
                base_capital=r[1],
                profit_amount=r[2],
                profit_type=ProfitType(r[3]),
                timestamp=datetime.fromisoformat(r[4]),
                trade_id=r[5],
                symbol=r[6],
                side=r[7],
                withdrawal_status=WithdrawalStatus(r[8]),
                withdrawal_tx_id=r[9],
                withdrawal_completed_at=datetime.fromisoformat(r[10]) if r[10] else None,
                notes=r[11],
            )
            records.append(record)

        return records

    async def get_aggregate_stats(self) -> Dict[str, Any]:
        """전체 집계 통계"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 전체 통계
        cursor.execute("""
            SELECT
                COUNT(DISTINCT bot_id) as bot_count,
                SUM(total_realized_profit) as total_profit,
                SUM(total_withdrawn) as total_withdrawn,
                SUM(pending_withdrawal) as total_pending
            FROM bot_capital_states
        """)
        stats = cursor.fetchone()

        # 오늘 수익
        today = datetime.utcnow().date().isoformat()
        cursor.execute("""
            SELECT SUM(realized_profit), SUM(withdrawn_amount), SUM(trade_count)
            FROM daily_profits
            WHERE date = ?
        """, (today,))
        today_stats = cursor.fetchone()

        conn.close()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_bots": stats[0] or 0,
            "total_realized_profit": stats[1] or 0,
            "total_withdrawn": stats[2] or 0,
            "total_pending_withdrawal": stats[3] or 0,
            "today": {
                "date": today,
                "realized_profit": today_stats[0] or 0,
                "withdrawn": today_stats[1] or 0,
                "trades": today_stats[2] or 0,
            }
        }

    # ========== 실시간 스트림 ==========

    async def publish_profit_event(self, record: ProfitRecord):
        """수익 발생 이벤트 발행 (WebSocket/MQTT)"""
        event = {
            "type": "profit_realized",
            "data": record.to_dict(),
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self.redis.publish("nest:events:profits", json.dumps(event))

    async def publish_withdrawal_event(self, bot_id: str, amount: float, status: str):
        """출금 이벤트 발행"""
        event = {
            "type": f"withdrawal_{status}",
            "data": {
                "bot_id": bot_id,
                "amount": amount,
                "timestamp": datetime.utcnow().isoformat(),
            }
        }
        await self.redis.publish("nest:events:withdrawals", json.dumps(event))


# 편의 함수
async def create_profit_tracker(redis_host: str = "localhost", redis_port: int = 6379) -> ProfitTracker:
    """ProfitTracker 팩토리 함수"""
    redis_client = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
    return ProfitTracker(redis_client)

"""
전략 성과 DB (제6부서 R&D)

SQLite 기반 전략 성과 저장 및 분석
- 향후 PostgreSQL 전환 가능하도록 추상화
"""

import sqlite3
import json
from dataclasses import dataclass, asdict
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class StrategyPerformance:
    """전략 성과 데이터"""
    strategy_id: str
    date: str  # YYYY-MM-DD
    pnl: float  # Profit and Loss
    sharpe: float
    mdd: float  # Max Drawdown
    win_rate: float
    parameters: Dict[str, Any]
    trades_count: int = 0
    created_at: Optional[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


@dataclass
class StrategyRank:
    """전략 순위 정보"""
    strategy_id: str
    rank: int
    total_pnl: float
    avg_sharpe: float
    flag: str  # 'strengthen', 'maintain', 'deprecate'


class StrategyDB:
    """
    전략 성과 데이터베이스

    SQLite 기본 구현, PostgreSQL 마이그레이션 준비
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # 기본 경로: 프로젝트 루트/data/strategy_performance.db
            project_root = Path(__file__).parent.parent.parent
            db_path = project_root / "data" / "strategy_performance.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()
        logger.info(f"StrategyDB initialized: {self.db_path}")

    def _init_db(self):
        """데이터베이스 초기화"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS strategy_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    pnl REAL DEFAULT 0.0,
                    sharpe REAL DEFAULT 0.0,
                    mdd REAL DEFAULT 0.0,
                    win_rate REAL DEFAULT 0.0,
                    parameters TEXT,  -- JSON
                    trades_count INTEGER DEFAULT 0,
                    created_at TEXT,
                    UNIQUE(strategy_id, date)
                )
            """)

            # 인덱스 생성
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_strategy_date
                ON strategy_performance(strategy_id, date)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_date
                ON strategy_performance(date)
            """)
            conn.commit()

    def save_performance(self, perf: StrategyPerformance) -> bool:
        """전략 성과 저장"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO strategy_performance
                    (strategy_id, date, pnl, sharpe, mdd, win_rate,
                     parameters, trades_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(strategy_id, date) DO UPDATE SET
                        pnl=excluded.pnl,
                        sharpe=excluded.sharpe,
                        mdd=excluded.mdd,
                        win_rate=excluded.win_rate,
                        parameters=excluded.parameters,
                        trades_count=excluded.trades_count
                """, (
                    perf.strategy_id,
                    perf.date,
                    perf.pnl,
                    perf.sharpe,
                    perf.mdd,
                    perf.win_rate,
                    json.dumps(perf.parameters),
                    perf.trades_count,
                    perf.created_at
                ))
                conn.commit()
                logger.debug(f"Saved performance for {perf.strategy_id} on {perf.date}")
                return True
        except Exception as e:
            logger.error(f"Failed to save performance: {e}")
            return False

    def get_performance(
        self,
        strategy_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[StrategyPerformance]:
        """전략 성과 조회"""
        query = "SELECT * FROM strategy_performance WHERE strategy_id = ?"
        params = [strategy_id]

        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)

        query += " ORDER BY date DESC"

        results = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)

            for row in cursor.fetchall():
                results.append(StrategyPerformance(
                    strategy_id=row['strategy_id'],
                    date=row['date'],
                    pnl=row['pnl'],
                    sharpe=row['sharpe'],
                    mdd=row['mdd'],
                    win_rate=row['win_rate'],
                    parameters=json.loads(row['parameters']) if row['parameters'] else {},
                    trades_count=row['trades_count'],
                    created_at=row['created_at']
                ))

        return results

    def get_latest_performance(self, strategy_id: str) -> Optional[StrategyPerformance]:
        """최신 성과 조회"""
        results = self.get_performance(strategy_id)
        return results[0] if results else None

    def get_all_strategies(self) -> List[str]:
        """모든 전략 ID 조회"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT DISTINCT strategy_id FROM strategy_performance"
            )
            return [row[0] for row in cursor.fetchall()]

    def get_daily_summary(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """일일 성과 요약"""
        if target_date is None:
            target_date = date.today().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # 전략별 성과
            cursor = conn.execute("""
                SELECT strategy_id,
                       SUM(pnl) as total_pnl,
                       AVG(sharpe) as avg_sharpe,
                       AVG(mdd) as avg_mdd,
                       AVG(win_rate) as avg_win_rate,
                       SUM(trades_count) as total_trades
                FROM strategy_performance
                WHERE date = ?
                GROUP BY strategy_id
                ORDER BY total_pnl DESC
            """, (target_date,))

            strategies = []
            total_pnl = 0.0
            for row in cursor.fetchall():
                strategies.append({
                    'strategy_id': row['strategy_id'],
                    'pnl': row['total_pnl'],
                    'sharpe': row['avg_sharpe'],
                    'mdd': row['avg_mdd'],
                    'win_rate': row['avg_win_rate'],
                    'trades': row['total_trades']
                })
                total_pnl += row['total_pnl']

            return {
                'date': target_date,
                'total_pnl': total_pnl,
                'strategies': strategies,
                'strategy_count': len(strategies)
            }

    def get_rankings(self, days: int = 30) -> List[StrategyRank]:
        """전략 순위 계산"""
        from_date = (date.today() - __import__('datetime').timedelta(days=days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT strategy_id,
                       SUM(pnl) as total_pnl,
                       AVG(sharpe) as avg_sharpe
                FROM strategy_performance
                WHERE date >= ?
                GROUP BY strategy_id
                ORDER BY total_pnl DESC
            """, (from_date,))

            rankings = []
            for rank, row in enumerate(cursor.fetchall(), 1):
                # 순위에 따른 플래그 설정
                if rank <= 3:
                    flag = 'strengthen'
                elif rank >= 10:
                    flag = 'deprecate'
                else:
                    flag = 'maintain'

                rankings.append(StrategyRank(
                    strategy_id=row['strategy_id'],
                    rank=rank,
                    total_pnl=row['total_pnl'],
                    avg_sharpe=row['avg_sharpe'],
                    flag=flag
                ))

        return rankings


# 전역 인스턴스
_db_instance: Optional[StrategyDB] = None


def get_strategy_db(db_path: Optional[str] = None) -> StrategyDB:
    """전역 StrategyDB 인스턴스"""
    global _db_instance
    if _db_instance is None:
        _db_instance = StrategyDB(db_path)
    return _db_instance


# 편의 함수
def save_strategy_performance(
    strategy_id: str,
    pnl: float,
    sharpe: float = 0.0,
    mdd: float = 0.0,
    win_rate: float = 0.0,
    parameters: Optional[Dict] = None,
    trades_count: int = 0,
    target_date: Optional[str] = None
) -> bool:
    """전략 성과 저장 (간편 함수)"""
    if target_date is None:
        target_date = date.today().isoformat()

    perf = StrategyPerformance(
        strategy_id=strategy_id,
        date=target_date,
        pnl=pnl,
        sharpe=sharpe,
        mdd=mdd,
        win_rate=win_rate,
        parameters=parameters or {},
        trades_count=trades_count
    )

    db = get_strategy_db()
    return db.save_performance(perf)


if __name__ == "__main__":
    # 테스트
    db = StrategyDB()

    # 샘플 데이터 저장
    save_strategy_performance(
        strategy_id="scalping_001",
        pnl=1250.50,
        sharpe=1.8,
        mdd=0.05,
        win_rate=0.62,
        parameters={"interval": "1m", "rsi_period": 14},
        trades_count=45
    )

    print("Rankings:")
    for rank in db.get_rankings():
        print(f"  {rank.rank}. {rank.strategy_id}: PnL={rank.total_pnl:.2f}, Flag={rank.flag}")

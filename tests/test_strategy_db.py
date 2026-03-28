"""
전략 성과 DB 테스트

STEP 2: 전략 성과 DB + GitHub Actions CI
"""

import pytest
import tempfile
import os
from datetime import date, timedelta

from occore.rnd.strategy_db import (
    StrategyDB,
    StrategyPerformance,
    StrategyRank,
    get_strategy_db,
    save_strategy_performance
)


class TestStrategyDB:
    """StrategyDB 기본 테스트"""

    @pytest.fixture
    def db(self):
        """임시 DB 인스턴스"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        db = StrategyDB(db_path)
        yield db

        # Cleanup
        os.unlink(db_path)

    def test_init_creates_tables(self, db):
        """DB 초기화 시 테이블 생성"""
        # 테이블이 존재하는지 확인
        with sqlite3.connect(db.db_path) as conn:
            cursor = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='strategy_performance'
            """)
            assert cursor.fetchone() is not None

    def test_save_performance(self, db):
        """성과 저장 테스트"""
        perf = StrategyPerformance(
            strategy_id="test_strategy_001",
            date="2024-03-28",
            pnl=1500.50,
            sharpe=1.5,
            mdd=0.05,
            win_rate=0.65,
            parameters={"rsi_period": 14, "ema_fast": 20},
            trades_count=42
        )

        result = db.save_performance(perf)
        assert result is True

    def test_get_performance(self, db):
        """성과 조회 테스트"""
        # 샘플 데이터 저장
        for i in range(5):
            perf = StrategyPerformance(
                strategy_id="test_strategy",
                date=(date(2024, 3, 28) - timedelta(days=i)).isoformat(),
                pnl=1000.0 + i * 100,
                sharpe=1.5,
                mdd=0.05,
                win_rate=0.65,
                parameters={},
                trades_count=10
            )
            db.save_performance(perf)

        # 조회
        results = db.get_performance("test_strategy")
        assert len(results) == 5
        assert results[0].pnl == 1000.0  # 최신 데이터 (2024-03-28)

    def test_get_latest_performance(self, db):
        """최신 성과 조회"""
        perf1 = StrategyPerformance(
            strategy_id="latest_test",
            date="2024-03-27",
            pnl=1000.0,
            sharpe=1.0,
            mdd=0.05,
            win_rate=0.5,
            parameters={}
        )
        perf2 = StrategyPerformance(
            strategy_id="latest_test",
            date="2024-03-28",
            pnl=2000.0,
            sharpe=2.0,
            mdd=0.03,
            win_rate=0.7,
            parameters={}
        )

        db.save_performance(perf1)
        db.save_performance(perf2)

        latest = db.get_latest_performance("latest_test")
        assert latest is not None
        assert latest.date == "2024-03-28"
        assert latest.pnl == 2000.0

    def test_get_all_strategies(self, db):
        """모든 전략 ID 조회"""
        for i in range(3):
            perf = StrategyPerformance(
                strategy_id=f"strategy_{i}",
                date="2024-03-28",
                pnl=1000.0,
                sharpe=1.0,
                mdd=0.05,
                win_rate=0.5,
                parameters={}
            )
            db.save_performance(perf)

        strategies = db.get_all_strategies()
        assert len(strategies) == 3
        assert "strategy_0" in strategies
        assert "strategy_1" in strategies
        assert "strategy_2" in strategies

    def test_get_daily_summary(self, db):
        """일일 요약 조회"""
        target_date = "2024-03-28"

        # 여러 전략 저장
        for i in range(3):
            perf = StrategyPerformance(
                strategy_id=f"strat_{i}",
                date=target_date,
                pnl=1000.0 * (i + 1),
                sharpe=1.0 + i * 0.2,
                mdd=0.05,
                win_rate=0.5 + i * 0.1,
                parameters={},
                trades_count=10 * (i + 1)
            )
            db.save_performance(perf)

        summary = db.get_daily_summary(target_date)
        assert summary['date'] == target_date
        assert summary['strategy_count'] == 3
        assert summary['total_pnl'] == 6000.0  # 1000 + 2000 + 3000

    def test_get_rankings(self, db):
        """순위 계산"""
        # 샘플 데이터 (최근 30일간)
        today = date.today()
        for day in range(30):
            for i in range(3):
                perf = StrategyPerformance(
                    strategy_id=f"rank_strat_{i}",
                    date=(today - timedelta(days=day)).isoformat(),
                    pnl=100.0 * (i + 1),
                    sharpe=1.0 + i * 0.3,
                    mdd=0.05,
                    win_rate=0.5,
                    parameters={}
                )
                db.save_performance(perf)

        rankings = db.get_rankings(days=30)
        assert len(rankings) == 3
        assert rankings[0].strategy_id == "rank_strat_2"  # 최고 수익
        # 30일 * 300 (strat_2) = 9000
        assert rankings[0].total_pnl == 9000.0

    def test_update_existing_performance(self, db):
        """기존 성과 업데이트"""
        perf1 = StrategyPerformance(
            strategy_id="update_test",
            date="2024-03-28",
            pnl=1000.0,
            sharpe=1.0,
            mdd=0.05,
            win_rate=0.5,
            parameters={}
        )

        perf2 = StrategyPerformance(
            strategy_id="update_test",
            date="2024-03-28",
            pnl=2000.0,  # 수정된 값
            sharpe=2.0,
            mdd=0.03,
            win_rate=0.7,
            parameters={"updated": True}
        )

        db.save_performance(perf1)
        db.save_performance(perf2)

        # 업데이트 확인
        results = db.get_performance("update_test")
        assert len(results) == 1
        assert results[0].pnl == 2000.0


class TestSaveStrategyPerformance:
    """편의 함수 테스트"""

    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            path = f.name
        yield path
        os.unlink(path)

    def test_save_strategy_performance(self, db_path):
        """간편 저장 함수 테스트"""
        import occore.rnd.strategy_db as sdb
        original_instance = sdb._db_instance

        try:
            sdb._db_instance = StrategyDB(db_path)

            result = save_strategy_performance(
                strategy_id="easy_save_test",
                pnl=5000.0,
                sharpe=2.0,
                mdd=0.04,
                win_rate=0.75,
                parameters={"fast": 10, "slow": 30},
                trades_count=50
            )

            assert result is True

            # 조회 확인
            perf = sdb._db_instance.get_latest_performance("easy_save_test")
            assert perf is not None
            assert perf.pnl == 5000.0
            assert perf.parameters == {"fast": 10, "slow": 30}

        finally:
            sdb._db_instance = original_instance


class TestStrategyRank:
    """StrategyRank 데이터클래스 테스트"""

    def test_strategy_rank_creation(self):
        """StrategyRank 생성"""
        rank = StrategyRank(
            strategy_id="test",
            rank=1,
            total_pnl=10000.0,
            avg_sharpe=1.8,
            flag="strengthen"
        )

        assert rank.strategy_id == "test"
        assert rank.rank == 1
        assert rank.flag == "strengthen"


# SQLite import for internal tests
import sqlite3

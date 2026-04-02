"""
Nest Profit Module 테스트
Phase 1 검증 테스트
"""

import asyncio
import json
import sqlite3
import tempfile
import os
from datetime import datetime, timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))

from nest_profit import (
    ProfitTracker, ProfitRecord, BotCapitalState,
    WithdrawalStatus, ProfitType, create_profit_tracker
)


class MockRedis:
    """테스트용 Mock Redis"""
    def __init__(self):
        self.data = {}
        self.lists = {}
        self.hashes = {}

    async def lpush(self, key, value):
        if key not in self.lists:
            self.lists[key] = []
        self.lists[key].insert(0, value)

    async def expire(self, key, seconds):
        pass

    async def hset(self, key, mapping=None, value=None):
        if mapping:
            if key not in self.hashes:
                self.hashes[key] = {}
            self.hashes[key].update(mapping)
        elif value:
            if key not in self.hashes:
                self.hashes[key] = {}
            self.hashes[key][value[0]] = value[1]

    async def hdel(self, key, field):
        if key in self.hashes and field in self.hashes[key]:
            del self.hashes[key][field]

    async def hincrbyfloat(self, key, field, amount):
        if key not in self.hashes:
            self.hashes[key] = {}
        current = float(self.hashes[key].get(field, 0))
        self.hashes[key][field] = str(current + amount)

    async def publish(self, channel, message):
        print(f"  [Mock Redis] Published to {channel}")

    def pubsub(self):
        return MockPubSub()


class MockPubSub:
    async def subscribe(self, channel):
        pass

    async def listen(self):
        yield {"type": "subscribe", "channel": "test"}


async def test_profit_record_creation():
    """수익 기록 생성 테스트"""
    print("\n=== Test 1: Profit Record Creation ===")

    record = ProfitRecord(
        bot_id="test_bot_01",
        base_capital=11.0,
        profit_amount=0.5,
        profit_type=ProfitType.REALIZED,
        timestamp=datetime.utcnow(),
        trade_id="trade_001",
        symbol="BTC/USDT",
        side="sell",
    )

    data = record.to_dict()
    assert data["bot_id"] == "test_bot_01"
    assert data["base_capital"] == 11.0
    assert data["profit_amount"] == 0.5
    assert data["profit_type"] == "realized"

    print("  ✓ Profit record creation passed")
    return True


async def test_profit_tracker_init():
    """Profit Tracker 초기화 테스트"""
    print("\n=== Test 2: Profit Tracker Initialization ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_profit.db")
        mock_redis = MockRedis()

        tracker = ProfitTracker(mock_redis, db_path)

        # DB 테이블 확인
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [t[0] for t in cursor.fetchall()]

        assert "profit_records" in tables
        assert "bot_capital_states" in tables
        assert "daily_profits" in tables
        assert "withdrawal_history" in tables

        conn.close()

    print("  ✓ Profit tracker initialization passed")
    return True


async def test_record_profit():
    """수익 기록 저장 테스트"""
    print("\n=== Test 3: Record Profit ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_profit.db")
        mock_redis = MockRedis()

        tracker = ProfitTracker(mock_redis, db_path)

        # 수익 기록
        record = await tracker.record_profit(
            bot_id="grid_bot_01",
            base_capital=11.0,
            profit_amount=0.25,
            trade_id="trade_001",
            symbol="BTC/USDT",
            side="sell"
        )

        assert record.bot_id == "grid_bot_01"
        assert record.base_capital == 11.0
        assert record.profit_amount == 0.25

        # DB 확인
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM profit_records WHERE bot_id = ?", ("grid_bot_01",))
        result = cursor.fetchone()
        assert result is not None

        # 봇 자본 상태 확인
        cursor.execute("SELECT * FROM bot_capital_states WHERE bot_id = ?", ("grid_bot_01",))
        state = cursor.fetchone()
        assert state is not None
        assert state[1] == 11.0  # base_capital
        assert state[3] == 0.25  # total_realized_profit

        conn.close()

    print("  ✓ Record profit passed")
    return True


async def test_multiple_profits():
    """다중 수익 기록 테스트"""
    print("\n=== Test 4: Multiple Profits ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_profit.db")
        mock_redis = MockRedis()

        tracker = ProfitTracker(mock_redis, db_path)

        # 여러 수익 기록
        for i in range(5):
            await tracker.record_profit(
                bot_id="multi_bot",
                base_capital=14.0,
                profit_amount=0.1 * (i + 1),
                trade_id=f"trade_{i}",
                symbol="ETH/USDT"
            )

        # 집계 확인
        state = await tracker.get_bot_capital_state("multi_bot")
        assert state is not None
        assert state.base_capital == 14.0
        assert state.total_realized_profit == 1.5  # 0.1+0.2+0.3+0.4+0.5
        assert state.available_to_withdraw == 1.5

    print("  ✓ Multiple profits passed")
    return True


async def test_withdrawal_flow():
    """출금 플로우 테스트"""
    print("\n=== Test 5: Withdrawal Flow ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_profit.db")
        mock_redis = MockRedis()

        tracker = ProfitTracker(mock_redis, db_path)

        # 수익 발생
        await tracker.record_profit(
            bot_id="withdraw_bot",
            base_capital=20.0,
            profit_amount=1.0,
            trade_id="trade_001"
        )

        # 출금 대기 확인
        pending = await tracker.get_pending_withdrawals("withdraw_bot")
        assert len(pending) == 1
        assert pending[0]["amount"] == 1.0

        # 출금 완료 처리
        result = await tracker.complete_withdrawal(
            bot_id="withdraw_bot",
            amount=1.0,
            currency="USDT",
            destination="master_wallet",
            tx_id="tx_12345"
        )

        assert result is True

        # 출금 후 상태 확인
        state = await tracker.get_bot_capital_state("withdraw_bot")
        assert state.total_withdrawn == 1.0
        assert state.available_to_withdraw == 0.0
        assert state.current_capital == 20.0  # 원금 복원됨

    print("  ✓ Withdrawal flow passed")
    return True


async def test_daily_summary():
    """일별 집계 테스트"""
    print("\n=== Test 6: Daily Summary ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_profit.db")
        mock_redis = MockRedis()

        tracker = ProfitTracker(mock_redis, db_path)

        # 여러 봇 수익
        for bot in ["bot_a", "bot_b", "bot_c"]:
            await tracker.record_profit(
                bot_id=bot,
                base_capital=10.0,
                profit_amount=0.5
            )

        # 일별 집계
        summary = await tracker.get_daily_profit_summary()

        assert summary["bot_count"] == 3
        assert summary["total_realized_profit"] == 1.5
        assert len(summary["bot_stats"]) == 3

    print("  ✓ Daily summary passed")
    return True


async def test_principal_preservation():
    """원금 보존 검증 테스트"""
    print("\n=== Test 7: Principal Preservation ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_profit.db")
        mock_redis = MockRedis()

        tracker = ProfitTracker(mock_redis, db_path)

        # 수익 발생 및 출금
        await tracker.record_profit(
            bot_id="preserve_bot",
            base_capital=11.0,
            profit_amount=2.0
        )

        # 출금 완료
        await tracker.complete_withdrawal(
            bot_id="preserve_bot",
            amount=2.0,
            currency="USDT",
            destination="wallet",
            tx_id="tx_001"
        )

        # 원금 보존 확인
        state = await tracker.get_bot_capital_state("preserve_bot")
        assert state.base_capital == 11.0  # 원금 그대로
        assert state.current_capital == 11.0  # 출금 후 원금만 남음
        assert state.total_withdrawn == 2.0  # 출금 완료

    print("  ✓ Principal preservation passed")
    return True


async def run_all_tests():
    """모든 테스트 실행"""
    print("=" * 60)
    print("🧪 Nest Profit Module Test Suite")
    print("=" * 60)

    tests = [
        test_profit_record_creation,
        test_profit_tracker_init,
        test_record_profit,
        test_multiple_profits,
        test_withdrawal_flow,
        test_daily_summary,
        test_principal_preservation,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            result = await test()
            if result:
                passed += 1
        except Exception as e:
            print(f"  ✗ Test failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"📊 Test Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)

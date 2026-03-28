"""
OpenRPA Automation Tests

STEP 8: RPA 자동화 테스트
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock

from occore.operations.rpa import RPAAutomation, AutomationTask


class TestAutomationTask:
    """AutomationTask 테스트"""

    def test_task_creation(self):
        """작업 생성 테스트"""
        task = AutomationTask(
            task_id="test_001",
            name="Test Task",
            task_type="report_download",
            schedule="daily",
            params={"report_type": "daily_pnl"},
        )

        assert task.task_id == "test_001"
        assert task.name == "Test Task"
        assert task.enabled is True


class TestRPAAutomation:
    """RPAAutomation 테스트"""

    @pytest.fixture
    def rpa(self, tmp_path):
        """테스트용 RPA 인스턴스 (고유 설정 파일)"""
        config_path = tmp_path / "rpa_tasks.json"
        return RPAAutomation(config_path=str(config_path))

    def test_rpa_initialization(self, rpa):
        """RPA 초기화 테스트"""
        assert rpa.running is False
        assert len(rpa.tasks) == 0

    def test_add_task(self, rpa):
        """작업 추가 테스트"""
        task = AutomationTask(
            task_id="daily_001",
            name="Daily Report",
            task_type="report_download",
            params={"output_dir": "reports/"},
        )

        result = rpa.add_task(task)

        assert result is True
        assert "daily_001" in rpa.tasks

    def test_remove_task(self, rpa):
        """작업 제거 테스트"""
        task = AutomationTask(
            task_id="remove_test",
            name="Remove Test",
            task_type="health_check",
        )

        rpa.add_task(task)
        result = rpa.remove_task("remove_test")

        assert result is True
        assert "remove_test" not in rpa.tasks

    @pytest.mark.asyncio
    async def test_execute_task_not_found(self, rpa):
        """존재하지 않는 작업 실행 테스트"""
        result = await rpa.execute_task("nonexistent")

        assert result["status"] == "error"
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_execute_task_disabled(self, rpa):
        """비활성화된 작업 실행 테스트"""
        task = AutomationTask(
            task_id="disabled_task",
            name="Disabled Task",
            task_type="report_download",
            enabled=False,
        )

        rpa.add_task(task)
        result = await rpa.execute_task("disabled_task")

        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_execute_report_download(self, rpa):
        """리포트 다운로드 작업 테스트"""
        task = AutomationTask(
            task_id="report_001",
            name="Daily PnL Report",
            task_type="report_download",
            params={
                "report_type": "daily_pnl",
                "output_dir": "/tmp/reports/",
            },
        )

        rpa.add_task(task)
        result = await rpa.execute_task("report_001")

        assert result["status"] == "success"
        assert "filepath" in result["result"]

    @pytest.mark.asyncio
    async def test_execute_order_adjustment(self, rpa):
        """주문 조정 작업 테스트"""
        task = AutomationTask(
            task_id="order_adj_001",
            name="Order Adjustment",
            task_type="order_adjustment",
            params={
                "symbol": "BTC/USDT",
                "spread_threshold": 0.5,
            },
        )

        rpa.add_task(task)
        result = await rpa.execute_task("order_adj_001")

        assert result["status"] == "success"
        assert "cancelled" in result["result"]

    @pytest.mark.asyncio
    async def test_execute_health_check(self, rpa):
        """헬스 체크 작업 테스트"""
        task = AutomationTask(
            task_id="health_001",
            name="Health Check",
            task_type="health_check",
        )

        rpa.add_task(task)
        result = await rpa.execute_task("health_001")

        assert result["status"] == "success"
        assert "checks" in result["result"]

    def test_get_status(self, rpa):
        """상태 조회 테스트"""
        import uuid
        task_id = f"status_test_{uuid.uuid4().hex[:8]}"
        task = AutomationTask(
            task_id=task_id,
            name="Status Test",
            task_type="health_check",
        )
        rpa.add_task(task)

        status = rpa.get_status()

        assert status["running"] is False
        assert status["task_count"] >= 1
        # 추가된 task_id가 목록에 있는지 확인
        task_ids = [t["task_id"] for t in status["tasks"]]
        assert task_id in task_ids


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

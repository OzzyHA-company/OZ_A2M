#!/usr/bin/env python3
"""OZ_A2M 제4부서 유지보수관리센터 테스트 스크립트"""
import os
import sys
import unittest
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from occore.devops import (
    get_health_checker,
    get_watchdog,
    get_diagnoser,
    get_healer,
    HealthStatus,
    HealthCheckError,
    DiagnosisType,
    SeverityLevel,
    RepairLog,
    RepairType,
    RepairStatus,
)


class TestHealthChecker(unittest.TestCase):
    """HealthChecker 테스트"""

    def setUp(self):
        self.health = get_health_checker()

    def test_singleton(self):
        """싱글톤 패턴 테스트"""
        health2 = get_health_checker()
        self.assertIs(self.health, health2)

    def test_check_system_resources(self):
        """리소스 체크 테스트"""
        metrics = self.health.check_system_resources()
        self.assertIsNotNone(metrics)
        self.assertGreaterEqual(metrics.cpu_percent, 0)
        self.assertGreaterEqual(metrics.memory_percent, 0)

    def test_evaluate_health_status(self):
        """헬스 상태 평가 테스트"""
        from occore.devops import ResourceMetrics, ServiceStatus
        from datetime import datetime

        metrics = ResourceMetrics(
            timestamp=datetime.now(),
            cpu_percent=50,
            memory_percent=60,
            memory_used_mb=1000,
            disk_percent=70,
            disk_used_gb=50,
            network_latency_ms=10
        )

        services = {
            "test": ServiceStatus(
                name="test",
                is_healthy=True,
                last_check=datetime.now()
            )
        }

        status = self.health.evaluate_health_status(metrics, services)
        self.assertEqual(status, HealthStatus.HEALTHY)


class TestWatchdog(unittest.TestCase):
    """Watchdog 테스트"""

    def setUp(self):
        self.watchdog = get_watchdog()

    def test_register_process(self):
        """프로세스 등록 테스트"""
        self.watchdog.register_process(
            name="test_process",
            pid=12345,
            auto_restart=False
        )
        self.assertIn("test_process", self.watchdog._monitored_processes)

    def test_is_process_alive_with_heartbeat(self):
        """하트비트 기반 생존 확인 테스트"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("")
            hb_file = f.name

        self.watchdog.register_process(
            name="test_hb",
            heartbeat_file=hb_file,
            auto_restart=False
        )

        # 하트비트 파일 업데이트
        Path(hb_file).touch()
        self.assertTrue(self.watchdog.is_process_alive("test_hb"))

        os.unlink(hb_file)


class TestDiagnoser(unittest.TestCase):
    """Diagnoser 테스트"""

    def setUp(self):
        self.diagnoser = get_diagnoser()

    def test_singleton(self):
        """싱글톤 패턴 테스트"""
        d2 = get_diagnoser()
        self.assertIs(self.diagnoser, d2)

    def test_diagnose_unknown(self):
        """알 수 없는 문제 진단 테스트"""
        import asyncio

        result = asyncio.run(self.diagnoser.diagnose(
            component="test",
            symptoms=["something weird"]
        ))

        self.assertEqual(result.diagnosis_type, DiagnosisType.UNKNOWN)
        self.assertEqual(result.component, "test")

    def test_diagnose_connectivity(self):
        """연결 문제 진단 테스트"""
        import asyncio

        result = asyncio.run(self.diagnoser.diagnose(
            component="network_service",
            symptoms=["connection timeout", "unreachable"]
        ))

        # 연결 문제로 진단되거나 UNKNOWN으로 폐기
        self.assertIn(result.diagnosis_type, [DiagnosisType.CONNECTIVITY, DiagnosisType.UNKNOWN])


class TestRepairLog(unittest.TestCase):
    """RepairLog 테스트"""

    def setUp(self):
        import tempfile
        self.db_path = tempfile.mktemp(suffix=".db")
        self.repair_log = RepairLog(db_path=self.db_path)

    def tearDown(self):
        import os
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_start_and_finish_repair(self):
        """수리 시작 및 완료 테스트"""
        repair_id = self.repair_log.start_repair(
            component="test_service",
            repair_type=RepairType.AUTO_HEAL,
            description="Test repair"
        )

        self.assertIsNotNone(repair_id)
        self.assertEqual(len(repair_id), 8)

        self.repair_log.finish_repair(
            repair_id=repair_id,
            success=True,
            details="Test completed"
        )

        # 조회
        repairs = self.repair_log.get_repairs()
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0].status, RepairStatus.SUCCESS)

    def test_get_repair_stats(self):
        """수리 통계 테스트"""
        # 여러 수리 기록
        for i in range(5):
            rid = self.repair_log.start_repair(
                component=f"service_{i % 2}",
                repair_type=RepairType.AUTO_HEAL,
                description=f"Test {i}"
            )
            self.repair_log.finish_repair(
                repair_id=rid,
                success=(i % 2 == 0),
                details="Done"
            )

        stats = self.repair_log.get_repair_stats(days=1)
        self.assertEqual(stats["total_repairs"], 5)
        self.assertEqual(stats["successful"], 3)
        self.assertEqual(stats["failed"], 2)


if __name__ == "__main__":
    unittest.main()

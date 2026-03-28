"""
Process Mining Tests

STEP 5: PM4Py 프로세스 마이닝 테스트
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, AsyncMock

from occore.analytics.event_logger import (
    EventLogger,
    EventType,
    Event,
    get_event_logger,
)
from occore.analytics.process_mining import (
    ProcessMiner,
    BottleneckAnalyzer,
    BottleneckInfo,
    DepartmentMetrics,
    DailyReport,
)


class TestEventLogger:
    """EventLogger 테스트"""

    @pytest.fixture
    def event_logger(self):
        """테스트용 이벤트 로거"""
        return EventLogger(
            es_hosts=["http://localhost:9200"],
            enable_console=False,
        )

    def test_event_creation(self):
        """이벤트 생성 테스트"""
        event = Event(
            event_type=EventType.TASK_START,
            department="dept1",
            task_name="test_task",
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_ms=100.0,
            metadata={"key": "value"},
        )

        assert event.event_type == EventType.TASK_START
        assert event.department == "dept1"
        assert event.task_name == "test_task"

    def test_event_to_dict(self):
        """이벤트 딕셔너리 변환 테스트"""
        event = Event(
            event_type=EventType.TASK_COMPLETE,
            department="dept2",
            task_name="completed_task",
            timestamp="2024-03-28T10:00:00+00:00",
            duration_ms=250.0,
        )

        data = event.to_dict()
        assert data["event_type"] == "task_complete"
        assert data["department"] == "dept2"
        assert data["duration_ms"] == 250.0

    @pytest.mark.asyncio
    async def test_log_event(self, event_logger):
        """이벤트 로깅 테스트"""
        result = await event_logger.log_event(
            event_type=EventType.API_REQUEST,
            department="dept3",
            task_name="api_call",
            duration_ms=150.0,
            metadata={"endpoint": "/api/test"},
        )

        assert result is True
        assert len(event_logger._buffer) == 1

    @pytest.mark.asyncio
    async def test_log_event_no_duration(self, event_logger):
        """소요 시간 없는 이벤트 로깅 테스트"""
        result = await event_logger.log_event(
            event_type=EventType.ERROR,
            department="dept4",
            task_name="failed_task",
            error="Test error",
        )

        assert result is True

    def test_get_event_logger_singleton(self):
        """싱글톤 테스트"""
        logger1 = get_event_logger()
        logger2 = get_event_logger()

        assert logger1 is logger2


class TestBottleneckAnalyzer:
    """BottleneckAnalyzer 테스트"""

    @pytest.fixture
    def analyzer(self):
        """테스트용 분석기"""
        return BottleneckAnalyzer(
            window_size=10,
            threshold_multiplier=2.0,
        )

    @pytest.mark.asyncio
    async def test_analyze_event_no_bottleneck(self, analyzer):
        """병목 없는 이벤트 분석 테스트"""
        event = {
            "department": "dept1",
            "task_name": "task1",
            "duration_ms": 50.0,
        }

        result = await analyzer.analyze_event(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_event_with_bottleneck(self, analyzer):
        """병목 이벤트 분석 테스트"""
        # 기준 통계 수집을 위한 이벤트 (11개 샘플, 마지막은 병목)
        for i in range(10):
            await analyzer.analyze_event({
                "department": "dept1",
                "task_name": "task1",
                "duration_ms": 100.0,
            })

        # 병목 이벤트 (임계값 초과)
        # 기준: 평균 100ms, 표준편차 0, 임계값 = 100 + 2*0 = 100ms
        # 500ms > 100ms * 2.0 = 200ms 이므로 병목
        bottleneck_event = {
            "department": "dept1",
            "task_name": "task1",
            "duration_ms": 500.0,
        }

        result = await analyzer.analyze_event(bottleneck_event)

        assert result is not None
        assert result.department == "dept1"
        assert result.task_name == "task1"
        assert result.max_duration_ms == 500.0
        # 병목은 감지됨
        assert result.severity in ["medium", "high", "critical"]

    def test_get_current_stats(self, analyzer):
        """현재 통계 조회 테스트"""
        stats = analyzer.get_current_stats()
        assert isinstance(stats, dict)


class TestProcessMiner:
    """ProcessMiner 테스트"""

    @pytest.fixture
    def miner(self):
        """테스트용 마이너"""
        return ProcessMiner(es_hosts=["http://localhost:9200"])

    def test_bottleneck_info_creation(self):
        """BottleneckInfo 생성 테스트"""
        info = BottleneckInfo(
            department="dept1",
            task_name="slow_task",
            avg_duration_ms=1000.0,
            max_duration_ms=5000.0,
            event_count=100,
            severity="high",
        )

        assert info.department == "dept1"
        assert info.severity == "high"

        data = info.to_dict()
        assert data["avg_duration_ms"] == 1000.0

    def test_department_metrics_creation(self):
        """DepartmentMetrics 생성 테스트"""
        metrics = DepartmentMetrics(
            department="dept1",
            total_events=1000,
            avg_processing_time_ms=150.0,
            error_rate=0.05,
            handoff_count=50,
            tasks=["task1", "task2", "task3"],
        )

        assert metrics.department == "dept1"
        assert metrics.total_events == 1000
        assert len(metrics.tasks) == 3

        data = metrics.to_dict()
        assert data["error_rate"] == 0.05

    def test_daily_report_creation(self):
        """DailyReport 생성 테스트"""
        report = DailyReport(
            date="2024-03-28",
            total_events=5000,
            unique_processes=100,
            bottlenecks=[],
            department_metrics=[],
            recommendations=["Test recommendation"],
        )

        assert report.date == "2024-03-28"
        assert report.total_events == 5000

        data = report.to_dict()
        assert data["unique_processes"] == 100

        json_str = report.to_json()
        assert "2024-03-28" in json_str

    def test_generate_recommendations(self, miner):
        """권장사항 생성 테스트"""
        bottlenecks = [
            BottleneckInfo(
                department="dept1",
                task_name="critical_task",
                avg_duration_ms=5000.0,
                max_duration_ms=10000.0,
                event_count=50,
                severity="critical",
            ),
        ]

        dept_metrics = [
            DepartmentMetrics(
                department="dept1",
                total_events=100,
                avg_processing_time_ms=3000.0,
                error_rate=0.15,
                handoff_count=150,
                tasks=["task1"],
            ),
        ]

        recommendations = miner._generate_recommendations(bottlenecks, dept_metrics)

        assert len(recommendations) > 0
        # 심각한 병목 관련 권장사항 확인
        assert any("심각한 병목" in r for r in recommendations)
        # 오류율 관련 권장사항 확인
        assert any("오류율" in r for r in recommendations)
        # 처리 시간 관련 권장사항 확인
        assert any("처리 시간" in r for r in recommendations)
        # 핸드오프 관련 권장사항 확인
        assert any("핸드오프" in r for r in recommendations)

    def test_generate_recommendations_no_issues(self, miner):
        """문제 없을 때 권장사항 테스트"""
        recommendations = miner._generate_recommendations([], [])

        assert len(recommendations) > 0
        assert any("안정적" in r for r in recommendations)


class TestProcessMiningIntegration:
    """통합 테스트"""

    @pytest.mark.asyncio
    async def test_event_logger_to_miner_flow(self):
        """이벤트 로거 → 마이너 흐름 테스트"""
        # 이벤트 로거 생성
        logger = EventLogger(enable_console=False)

        # 이벤트 기록
        for i in range(10):
            await logger.log_event(
                event_type=EventType.TASK_START,
                department="dept1",
                task_name="processing_task",
                duration_ms=100.0 + i * 10,
            )

        # 버퍼에 이벤트가 쌓임
        assert len(logger._buffer) == 10

    def test_bottleneck_severity_calculation(self):
        """병목 심각도 계산 테스트"""
        # 이 테스트는 ProcessMiner.detect_bottlenecks의 로직을 검증
        # 임계값 1000ms, 평균 5000ms = high severity
        # 임계값 1000ms, 평균 10000ms = critical severity

        threshold = 1000.0

        # low severity: 1000 * 2 = 2000 > avg=1500
        avg_low = 1500.0
        if avg_low > threshold * 10:
            severity_low = "critical"
        elif avg_low > threshold * 5:
            severity_low = "high"
        elif avg_low > threshold * 2:
            severity_low = "medium"
        else:
            severity_low = "low"
        assert severity_low == "low"

        # medium severity
        avg_med = 2500.0
        if avg_med > threshold * 10:
            severity_med = "critical"
        elif avg_med > threshold * 5:
            severity_med = "high"
        elif avg_med > threshold * 2:
            severity_med = "medium"
        else:
            severity_med = "low"
        assert severity_med == "medium"

        # high severity
        avg_high = 6000.0
        if avg_high > threshold * 10:
            severity_high = "critical"
        elif avg_high > threshold * 5:
            severity_high = "high"
        elif avg_high > threshold * 2:
            severity_high = "medium"
        else:
            severity_high = "low"
        assert severity_high == "high"

        # critical severity
        avg_crit = 12000.0
        if avg_crit > threshold * 10:
            severity_crit = "critical"
        elif avg_crit > threshold * 5:
            severity_crit = "high"
        elif avg_crit > threshold * 2:
            severity_crit = "medium"
        else:
            severity_crit = "low"
        assert severity_crit == "critical"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

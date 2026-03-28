"""
Process Mining

PM4Py 기반 프로세스 마이닝 모듈
- Elasticsearch 이벤트 로그 → PM4Py 변환
- 병목 탐지
- 일일 리포트 생성
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict

import pandas as pd
from elasticsearch import AsyncElasticsearch

# PM4Py imports
try:
    import pm4py
    from pm4py.objects.log.obj import EventLog, Trace, Event
    from pm4py.objects.conversion.log import converter as log_converter
    from pm4py.algo.discovery.alpha import algorithm as alpha_miner
    from pm4py.algo.discovery.heuristics_net import algorithm as heuristics_miner
    from pm4py.algo.evaluation.replay_fitness import algorithm as replay_fitness
    from pm4py.algo.conformance.tokenreplay import algorithm as token_replay
    from pm4py.statistics.performance_spectrum import algorithm as performance_spectrum
    from pm4py.util import constants
    PM4PY_AVAILABLE = True
except ImportError:
    PM4PY_AVAILABLE = False
    logging.warning("PM4Py not installed. Process mining features disabled.")

from .event_logger import EventLogger, EventType

logger = logging.getLogger(__name__)


@dataclass
class BottleneckInfo:
    """병목 정보"""
    department: str
    task_name: str
    avg_duration_ms: float
    max_duration_ms: float
    event_count: int
    severity: str  # low, medium, high, critical

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DepartmentMetrics:
    """부서별 메트릭스"""
    department: str
    total_events: int
    avg_processing_time_ms: float
    error_rate: float
    handoff_count: int
    tasks: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DailyReport:
    """일일 프로세스 마이닝 리포트"""
    date: str
    total_events: int
    unique_processes: int
    bottlenecks: List[BottleneckInfo]
    department_metrics: List[DepartmentMetrics]
    recommendations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "total_events": self.total_events,
            "unique_processes": self.unique_processes,
            "bottlenecks": [b.to_dict() for b in self.bottlenecks],
            "department_metrics": [d.to_dict() for d in self.department_metrics],
            "recommendations": self.recommendations,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


class ProcessMiner:
    """
    PM4Py 기반 프로세스 마이너

    Usage:
        miner = ProcessMiner()

        # 일일 리포트 생성
        report = await miner.generate_daily_report()
        print(report.to_json())

        # 병목 분석
        bottlenecks = await miner.detect_bottlenecks()
    """

    def __init__(
        self,
        es_hosts: Optional[List[str]] = None,
        event_logger: Optional[EventLogger] = None,
    ):
        self.es_hosts = es_hosts or ["http://localhost:9200"]
        self.event_logger = event_logger
        self._es: Optional[AsyncElasticsearch] = None

        if not PM4PY_AVAILABLE:
            logger.warning("PM4Py not available. Process mining limited to basic stats.")

    async def _get_es_client(self) -> Optional[AsyncElasticsearch]:
        """Elasticsearch 클라이언트 가져오기"""
        if self._es is None:
            try:
                self._es = AsyncElasticsearch(self.es_hosts)
                if await self._es.ping():
                    logger.info(f"Connected to Elasticsearch: {self.es_hosts}")
                else:
                    logger.warning("Elasticsearch ping failed")
                    self._es = None
            except Exception as e:
                logger.warning(f"Elasticsearch connection failed: {e}")
                self._es = None
        return self._es

    async def fetch_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        size: int = 10000,
    ) -> List[Dict[str, Any]]:
        """
        Elasticsearch에서 이벤트 조회

        Args:
            start_time: 시작 시간
            end_time: 종료 시간
            size: 최대 결과 수

        Returns:
            이벤트 목록
        """
        es = await self._get_es_client()
        if es is None:
            logger.warning("Elasticsearch not available")
            return []

        # 기본 시간 범위: 어제부터 오늘
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        if start_time is None:
            start_time = end_time - timedelta(days=1)

        query = {
            "bool": {
                "must": [
                    {
                        "range": {
                            "timestamp": {
                                "gte": start_time.isoformat(),
                                "lte": end_time.isoformat(),
                            }
                        }
                    }
                ]
            }
        }

        try:
            response = await es.search(
                index="oz_a2m_events*",
                body={
                    "query": query,
                    "sort": [{"timestamp": {"order": "asc"}}],
                    "size": size,
                }
            )

            events = [hit["_source"] for hit in response["hits"]["hits"]]
            logger.info(f"Fetched {len(events)} events from Elasticsearch")
            return events

        except Exception as e:
            logger.error(f"Failed to fetch events: {e}")
            return []

    def _events_to_pm4py_log(self, events: List[Dict[str, Any]]) -> Optional[Any]:
        """
        이벤트를 PM4Py EventLog로 변환

        Args:
            events: 이벤트 목록

        Returns:
            PM4Py EventLog
        """
        if not PM4PY_AVAILABLE or not events:
            return None

        # Pandas DataFrame 생성
        df_data = []
        for event in events:
            df_data.append({
                "case_id": event.get("trace_id", "unknown"),
                "activity": f"{event.get('department', 'unknown')}_{event.get('task_name', 'unknown')}",
                "timestamp": event.get("timestamp"),
                "department": event.get("department"),
                "task_name": event.get("task_name"),
                "duration_ms": event.get("duration_ms"),
                "event_type": event.get("event_type"),
            })

        df = pd.DataFrame(df_data)

        if df.empty:
            return None

        # PM4Py 로그 변환
        try:
            log = log_converter.apply(df)
            return log
        except Exception as e:
            logger.error(f"Failed to convert to PM4Py log: {e}")
            return None

    async def detect_bottlenecks(
        self,
        threshold_ms: float = 1000.0,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[BottleneckInfo]:
        """
        병목 탐지

        Args:
            threshold_ms: 병목으로 간주할 최소 소요 시간 (ms)
            start_time: 분석 시작 시간
            end_time: 분석 종료 시간

        Returns:
            병목 정보 목록
        """
        events = await self.fetch_events(start_time, end_time)

        if not events:
            logger.warning("No events found for bottleneck analysis")
            return []

        # 부서+작업별 집계
        task_stats: Dict[str, Dict[str, Any]] = {}

        for event in events:
            key = f"{event.get('department', 'unknown')}_{event.get('task_name', 'unknown')}"
            duration = event.get("duration_ms", 0) or 0

            if key not in task_stats:
                task_stats[key] = {
                    "department": event.get("department", "unknown"),
                    "task_name": event.get("task_name", "unknown"),
                    "durations": [],
                    "count": 0,
                }

            task_stats[key]["durations"].append(duration)
            task_stats[key]["count"] += 1

        # 병목 식별
        bottlenecks = []
        for key, stats in task_stats.items():
            durations = stats["durations"]
            if not durations:
                continue

            avg_duration = sum(durations) / len(durations)
            max_duration = max(durations)

            # 병목 임계값 초과 시
            if avg_duration > threshold_ms:
                # 심각도 결정
                if avg_duration > threshold_ms * 10:
                    severity = "critical"
                elif avg_duration > threshold_ms * 5:
                    severity = "high"
                elif avg_duration > threshold_ms * 2:
                    severity = "medium"
                else:
                    severity = "low"

                bottlenecks.append(BottleneckInfo(
                    department=stats["department"],
                    task_name=stats["task_name"],
                    avg_duration_ms=avg_duration,
                    max_duration_ms=max_duration,
                    event_count=stats["count"],
                    severity=severity,
                ))

        # 평균 소요 시간 기준 정렬
        bottlenecks.sort(key=lambda x: x.avg_duration_ms, reverse=True)

        logger.info(f"Detected {len(bottlenecks)} bottlenecks")
        return bottlenecks

    async def analyze_department_metrics(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[DepartmentMetrics]:
        """
        부서별 메트릭스 분석

        Args:
            start_time: 분석 시작 시간
            end_time: 분석 종료 시간

        Returns:
            부서별 메트릭스 목록
        """
        events = await self.fetch_events(start_time, end_time)

        if not events:
            return []

        # 부서별 집계
        dept_stats: Dict[str, Dict[str, Any]] = {}

        for event in events:
            dept = event.get("department", "unknown")

            if dept not in dept_stats:
                dept_stats[dept] = {
                    "events": [],
                    "durations": [],
                    "errors": 0,
                    "handoffs": 0,
                    "tasks": set(),
                }

            dept_stats[dept]["events"].append(event)

            duration = event.get("duration_ms")
            if duration:
                dept_stats[dept]["durations"].append(duration)

            if event.get("error"):
                dept_stats[dept]["errors"] += 1

            if event.get("event_type") == EventType.DEPARTMENT_HANDOFF.value:
                dept_stats[dept]["handoffs"] += 1

            dept_stats[dept]["tasks"].add(event.get("task_name", "unknown"))

        # 메트릭스 계산
        metrics = []
        for dept, stats in dept_stats.items():
            durations = stats["durations"]
            avg_duration = sum(durations) / len(durations) if durations else 0
            total_events = len(stats["events"])
            error_rate = stats["errors"] / total_events if total_events > 0 else 0

            metrics.append(DepartmentMetrics(
                department=dept,
                total_events=total_events,
                avg_processing_time_ms=avg_duration,
                error_rate=error_rate,
                handoff_count=stats["handoffs"],
                tasks=list(stats["tasks"]),
            ))

        return metrics

    async def generate_daily_report(
        self,
        date: Optional[str] = None,
    ) -> DailyReport:
        """
        일일 프로세스 마이닝 리포트 생성

        Args:
            date: 리포트 날짜 (YYYY-MM-DD), None이면 오늘

        Returns:
            일일 리포트
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # 해당 날짜의 시작/종료 시간
        start_time = datetime.fromisoformat(f"{date}T00:00:00+00:00")
        end_time = start_time + timedelta(days=1)

        logger.info(f"Generating daily report for {date}")

        # 이벤트 조회
        events = await self.fetch_events(start_time, end_time)

        # 병목 탐지
        bottlenecks = await self.detect_bottlenecks(
            threshold_ms=500.0,
            start_time=start_time,
            end_time=end_time,
        )

        # 부서별 메트릭스
        dept_metrics = await self.analyze_department_metrics(
            start_time=start_time,
            end_time=end_time,
        )

        # 고유 프로세스 수 (trace_id 기준)
        unique_traces = set(e.get("trace_id") for e in events if e.get("trace_id"))

        # 권장사항 생성
        recommendations = self._generate_recommendations(bottlenecks, dept_metrics)

        report = DailyReport(
            date=date,
            total_events=len(events),
            unique_processes=len(unique_traces),
            bottlenecks=bottlenecks,
            department_metrics=dept_metrics,
            recommendations=recommendations,
        )

        logger.info(f"Daily report generated: {len(events)} events, {len(bottlenecks)} bottlenecks")
        return report

    def _generate_recommendations(
        self,
        bottlenecks: List[BottleneckInfo],
        dept_metrics: List[DepartmentMetrics],
    ) -> List[str]:
        """개선 권장사항 생성"""
        recommendations = []

        # 병목 기반 권장사항
        critical_bottlenecks = [b for b in bottlenecks if b.severity in ["high", "critical"]]
        if critical_bottlenecks:
            recommendations.append(
                f"심각한 병목 {len(critical_bottlenecks)}개 발견. "
                f"우선순위: {', '.join(b.task_name for b in critical_bottlenecks[:3])}"
            )

        # 오류율 기반 권장사항
        high_error_depts = [d for d in dept_metrics if d.error_rate > 0.1]
        if high_error_depts:
            recommendations.append(
                f"높은 오류율 부서: {', '.join(d.department for d in high_error_depts)}. "
                "에러 로그 분석 필요"
            )

        # 처리 시간 기반 권장사항
        slow_depts = [d for d in dept_metrics if d.avg_processing_time_ms > 2000]
        if slow_depts:
            recommendations.append(
                f"처리 시간이 긴 부서: {', '.join(d.department for d in slow_depts)}. "
                "병렬처리 또는 캐싱 적용 검토"
            )

        # 핸드오프 기반 권장사항
        high_handoff_depts = [d for d in dept_metrics if d.handoff_count > 100]
        if high_handoff_depts:
            recommendations.append(
                f"부서간 핸드오프가 많음: {', '.join(d.department for d in high_handoff_depts)}. "
                "비동기 메시징 최적화 필요"
            )

        if not recommendations:
            recommendations.append("현재 시스템이 안정적으로 실행 중입니다.")

        return recommendations

    async def discover_process_model(self) -> Optional[Dict[str, Any]]:
        """
        프로세스 모델 발견 (PM4Py)

        Returns:
            프로세스 모델 정보
        """
        if not PM4PY_AVAILABLE:
            logger.warning("PM4Py not available for process discovery")
            return None

        events = await self.fetch_events()
        log = self._events_to_pm4py_log(events)

        if log is None:
            return None

        try:
            # Heuristics Net 마이너 사용
            heu_net = heuristics_miner.apply_heu(log)

            # 기본 프로세스 모델 정보
            model_info = {
                "activities": list(heu_net.activities) if hasattr(heu_net, 'activities') else [],
                "start_activities": list(heu_net.start_activities) if hasattr(heu_net, 'start_activities') else [],
                "end_activities": list(heu_net.end_activities) if hasattr(heu_net, 'end_activities') else [],
            }

            return model_info

        except Exception as e:
            logger.error(f"Process discovery failed: {e}")
            return None

    async def close(self):
        """연결 종료"""
        if self._es:
            await self._es.close()
            self._es = None


class BottleneckAnalyzer:
    """
    실시간 병목 분석기

    Usage:
        analyzer = BottleneckAnalyzer()

        # 이벤트 스트림에 병목 분석 적용
        async for event in event_stream:
            bottleneck = await analyzer.analyze_event(event)
            if bottleneck:
                alert(bottleneck)
    """

    def __init__(
        self,
        window_size: int = 100,
        threshold_multiplier: float = 3.0,
    ):
        self.window_size = window_size
        self.threshold_multiplier = threshold_multiplier
        self._event_window: List[Dict[str, Any]] = []
        self._baseline_stats: Dict[str, Dict[str, float]] = {}

    async def analyze_event(self, event: Dict[str, Any]) -> Optional[BottleneckInfo]:
        """
        단일 이벤트 분석

        Args:
            event: 이벤트 데이터

        Returns:
            병목 정보 (병목이 아니면 None)
        """
        # 윈도우에 추가
        self._event_window.append(event)

        # 윈도우 크기 유지
        if len(self._event_window) > self.window_size:
            self._event_window.pop(0)

        # 기준 통계 업데이트
        await self._update_baseline()

        # 병목 확인
        duration = event.get("duration_ms", 0) or 0
        key = f"{event.get('department', 'unknown')}_{event.get('task_name', 'unknown')}"

        if key in self._baseline_stats:
            baseline = self._baseline_stats[key]
            threshold = baseline["mean"] + (self.threshold_multiplier * baseline["std"])

            if duration > threshold:
                return BottleneckInfo(
                    department=event.get("department", "unknown"),
                    task_name=event.get("task_name", "unknown"),
                    avg_duration_ms=baseline["mean"],
                    max_duration_ms=duration,
                    event_count=baseline["count"],
                    severity="high" if duration > threshold * 2 else "medium",
                )

        return None

    async def _update_baseline(self):
        """기준 통계 업데이트"""
        # 부서+작업별 집계
        task_durations: Dict[str, List[float]] = {}

        for event in self._event_window:
            key = f"{event.get('department', 'unknown')}_{event.get('task_name', 'unknown')}"
            duration = event.get("duration_ms", 0) or 0

            if key not in task_durations:
                task_durations[key] = []
            task_durations[key].append(duration)

        # 통계 계산
        for key, durations in task_durations.items():
            if len(durations) >= 10:  # 최소 10개 샘플 필요
                import statistics
                self._baseline_stats[key] = {
                    "mean": statistics.mean(durations),
                    "std": statistics.stdev(durations) if len(durations) > 1 else 0,
                    "count": len(durations),
                }

    def get_current_stats(self) -> Dict[str, Dict[str, float]]:
        """현재 통계 조회"""
        return self._baseline_stats.copy()

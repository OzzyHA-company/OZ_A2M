"""
Event Logger

Elasticsearch 기반 이벤트 로그 수집기
- 작업 시작/완료
- API 응답 시간
- 오류 발생 시점
"""

import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk

logger = logging.getLogger(__name__)


class EventType(Enum):
    """이벤트 타입"""
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    TASK_FAILED = "task_failed"
    API_REQUEST = "api_request"
    API_RESPONSE = "api_response"
    ERROR = "error"
    DEPARTMENT_HANDOFF = "department_handoff"
    SIGNAL_GENERATED = "signal_generated"
    ORDER_PLACED = "order_placed"
    MARKET_DATA = "market_data"


@dataclass
class Event:
    """이벤트 데이터클스"""
    event_type: EventType
    department: str
    task_name: str
    timestamp: str
    duration_ms: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Elasticsearch 저장용 딕셔너리 변환"""
        return {
            "event_type": self.event_type.value,
            "department": self.department,
            "task_name": self.task_name,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata or {},
            "error": self.error,
            "trace_id": self.trace_id,
        }


class EventLogger:
    """
    OZ_A2M 이벤트 로거

    Usage:
        event_logger = EventLogger()

        # 이벤트 기록
        await event_logger.log_event(
            event_type=EventType.TASK_START,
            department="dept1",
            task_name="market_analysis"
        )

        # 컨텍스트 매니저로 자동 기록
        async with event_logger.timed_event(
            event_type=EventType.API_REQUEST,
            department="dept2",
            task_name="fetch_market_data"
        ):
            await fetch_data()
    """

    def __init__(
        self,
        es_hosts: Optional[List[str]] = None,
        index_prefix: str = "oz_a2m_events",
        enable_console: bool = True,
    ):
        self.es_hosts = es_hosts or ["http://localhost:9200"]
        self.index_prefix = index_prefix
        self.enable_console = enable_console
        self._es: Optional[AsyncElasticsearch] = None
        self._buffer: List[Dict[str, Any]] = []
        self._buffer_size = 100

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

    def _get_index_name(self) -> str:
        """오늘 날짜의 인덱스 이름 생성"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{self.index_prefix}_{today}"

    async def log_event(
        self,
        event_type: EventType,
        department: str,
        task_name: str,
        duration_ms: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> bool:
        """
        이벤트 기록

        Args:
            event_type: 이벤트 타입
            department: 부서명
            task_name: 작업명
            duration_ms: 소요 시간 (ms)
            metadata: 추가 메타데이터
            error: 오류 메시지
            trace_id: 추적 ID

        Returns:
            bool: 성공 여부
        """
        event = Event(
            event_type=event_type,
            department=department,
            task_name=task_name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_ms=duration_ms,
            metadata=metadata,
            error=error,
            trace_id=trace_id,
        )

        # 버퍼에 추가
        event_dict = event.to_dict()
        event_dict["_index"] = self._get_index_name()
        self._buffer.append(event_dict)

        # 콘솔 출력
        if self.enable_console:
            logger.info(
                f"[Event] {event_type.value} | {department} | {task_name} | "
                f"{duration_ms:.2f}ms" if duration_ms else f"[Event] {event_type.value}"
            )

        # 버퍼가 가득 차면 플러시
        if len(self._buffer) >= self._buffer_size:
            await self.flush()

        return True

    async def flush(self) -> bool:
        """버퍼를 Elasticsearch로 플러시"""
        if not self._buffer:
            return True

        es = await self._get_es_client()
        if es is None:
            logger.warning("Elasticsearch not available, dropping buffered events")
            self._buffer.clear()
            return False

        try:
            # 인덱스가 없으면 생성
            index_name = self._get_index_name()
            if not await es.indices.exists(index=index_name):
                await self._create_index(index_name)

            # 벌크 인덱싱
            success, errors = await async_bulk(es, self._buffer)
            logger.debug(f"Flushed {success} events to {index_name}")

            self._buffer.clear()
            return True

        except Exception as e:
            logger.error(f"Failed to flush events: {e}")
            return False

    async def _create_index(self, index_name: str):
        """인덱스 생성"""
        mapping = {
            "mappings": {
                "properties": {
                    "event_type": {"type": "keyword"},
                    "department": {"type": "keyword"},
                    "task_name": {"type": "keyword"},
                    "timestamp": {"type": "date"},
                    "duration_ms": {"type": "float"},
                    "metadata": {"type": "object"},
                    "error": {"type": "text"},
                    "trace_id": {"type": "keyword"},
                }
            }
        }

        try:
            await self._es.indices.create(index=index_name, body=mapping)
            logger.info(f"Created index: {index_name}")
        except Exception as e:
            logger.warning(f"Index creation failed (may already exist): {e}")

    @contextmanager
    def timed_event(
        self,
        event_type: EventType,
        department: str,
        task_name: str,
        metadata: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ):
        """
        타이밍을 자동 측정하는 컨텍스트 매니저

        Usage:
            with event_logger.timed_event(
                EventType.API_REQUEST,
                "dept1",
                "fetch_data"
            ):
                result = await fetch_data()
        """
        start_time = time.time()
        error_msg = None

        try:
            yield self
        except Exception as e:
            error_msg = str(e)
            # 실패 이벤트로 변경
            event_type = EventType.TASK_FAILED
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000

            # 비동기 이벤트 로깅 (동기 컨텍스트에서 실행)
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 이미 실행 중인 루프가 있으면 create_task 사용
                    asyncio.create_task(
                        self.log_event(
                            event_type=event_type,
                            department=department,
                            task_name=task_name,
                            duration_ms=duration_ms,
                            metadata=metadata,
                            error=error_msg,
                            trace_id=trace_id,
                        )
                    )
                else:
                    loop.run_until_complete(
                        self.log_event(
                            event_type=event_type,
                            department=department,
                            task_name=task_name,
                            duration_ms=duration_ms,
                            metadata=metadata,
                            error=error_msg,
                            trace_id=trace_id,
                        )
                    )
            except Exception as e:
                logger.warning(f"Failed to log timed event: {e}")

    async def get_events(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        department: Optional[str] = None,
        event_type: Optional[EventType] = None,
        size: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        이벤트 조회

        Args:
            start_time: 시작 시간 (ISO format)
            end_time: 종료 시간 (ISO format)
            department: 부서 필터
            event_type: 이벤트 타입 필터
            size: 최대 결과 수

        Returns:
            이벤트 목록
        """
        es = await self._get_es_client()
        if es is None:
            return []

        query = {"bool": {"must": []}}

        if start_time or end_time:
            range_query = {"timestamp": {}}
            if start_time:
                range_query["timestamp"]["gte"] = start_time
            if end_time:
                range_query["timestamp"]["lte"] = end_time
            query["bool"]["must"].append({"range": range_query})

        if department:
            query["bool"]["must"].append({"term": {"department": department}})

        if event_type:
            query["bool"]["must"].append({"term": {"event_type": event_type.value}})

        try:
            response = await es.search(
                index=f"{self.index_prefix}*",
                body={
                    "query": query if query["bool"]["must"] else {"match_all": {}},
                    "sort": [{"timestamp": {"order": "desc"}}],
                    "size": size,
                }
            )

            return [hit["_source"] for hit in response["hits"]["hits"]]

        except Exception as e:
            logger.error(f"Failed to query events: {e}")
            return []

    async def close(self):
        """연결 종료"""
        await self.flush()
        if self._es:
            await self._es.close()
            self._es = None


# 전역 인스턴스
_event_logger: Optional[EventLogger] = None


def get_event_logger(
    es_hosts: Optional[List[str]] = None,
    enable_console: bool = True,
) -> EventLogger:
    """전역 EventLogger 인스턴스 가져오기"""
    global _event_logger
    if _event_logger is None:
        _event_logger = EventLogger(
            es_hosts=es_hosts,
            enable_console=enable_console,
        )
    return _event_logger

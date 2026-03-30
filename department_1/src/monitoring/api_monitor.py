"""
API Monitoring Module
거래소 API 사용량 모니터링 및 Rate Limit 관리
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import deque

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ApiCall:
    """API 호출 기록"""
    timestamp: datetime
    endpoint: str
    status: str  # success, error, rate_limited
    response_time: float  # milliseconds
    weight: int = 1  # API 가중치 (Binance 등)


@dataclass
class ApiMetrics:
    """API 메트릭스"""
    exchange: str
    total_calls: int = 0
    error_calls: int = 0
    rate_limited_count: int = 0
    avg_response_time: float = 0.0
    last_call: Optional[datetime] = None
    limit: int = 1000
    remaining: int = 1000
    reset_time: Optional[datetime] = None


class ApiMonitor:
    """
    API 사용량 모니터

    기능:
    - 실시간 API 호출 추적
    - Rate limit 모니터링
    - 응답 시간 측정
    - 알림 발송 (임계값 초과 시)
    """

    def __init__(self):
        self._calls: Dict[str, deque] = {}  # exchange -> deque of ApiCall
        self._metrics: Dict[str, ApiMetrics] = {}
        self._window_size = 3600  # 1시간 윈도우
        self._lock = asyncio.Lock()

        # 거래소별 설정
        self._exchange_configs = {
            'binance': {
                'limit': 1200,  # 1분당
                'window': 60,
                'warning_threshold': 0.8,
            },
            'bybit': {
                'limit': 100,  # 1분당
                'window': 60,
                'warning_threshold': 0.8,
            },
            'hyperliquid': {
                'limit': 1000,
                'window': 60,
                'warning_threshold': 0.8,
            },
            'polymarket': {
                'limit': 100,
                'window': 60,
                'warning_threshold': 0.8,
            },
        }

        self._running = False
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self):
        """모니터 시작"""
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("API Monitor started")

    async def stop(self):
        """모니터 중지"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
        logger.info("API Monitor stopped")

    async def record_call(
        self,
        exchange: str,
        endpoint: str,
        status: str = 'success',
        response_time: float = 0.0,
        weight: int = 1
    ):
        """API 호출 기록"""
        async with self._lock:
            if exchange not in self._calls:
                self._calls[exchange] = deque(maxlen=10000)
                self._metrics[exchange] = ApiMetrics(exchange=exchange)

            call = ApiCall(
                timestamp=datetime.utcnow(),
                endpoint=endpoint,
                status=status,
                response_time=response_time,
                weight=weight
            )
            self._calls[exchange].append(call)

            # 메트릭스 업데이트
            metrics = self._metrics[exchange]
            metrics.total_calls += 1
            metrics.last_call = datetime.utcnow()

            if status == 'error':
                metrics.error_calls += 1
            elif status == 'rate_limited':
                metrics.rate_limited_count += 1

            # 평균 응답 시간 계산
            recent_calls = [c for c in self._calls[exchange] if c.response_time > 0]
            if recent_calls:
                metrics.avg_response_time = sum(c.response_time for c in recent_calls) / len(recent_calls)

            # Rate limit 체크
            await self._check_rate_limit(exchange)

    async def _check_rate_limit(self, exchange: str):
        """Rate limit 체크 및 경고"""
        config = self._exchange_configs.get(exchange, {})
        if not config:
            return

        metrics = self._metrics[exchange]
        window = config.get('window', 60)
        limit = config.get('limit', 1000)
        threshold = config.get('warning_threshold', 0.8)

        # 현재 윈도우의 호출 수 계산
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=window)

        calls_in_window = sum(
            1 for call in self._calls[exchange]
            if call.timestamp > window_start
        )

        usage_pct = calls_in_window / limit
        metrics.remaining = max(0, limit - calls_in_window)
        metrics.limit = limit

        if usage_pct >= threshold:
            logger.warning(
                f"{exchange.upper()} API rate limit warning: "
                f"{calls_in_window}/{limit} ({usage_pct*100:.1f}%)"
            )

    async def _cleanup_loop(self):
        """오래된 데이터 정리"""
        while self._running:
            try:
                await asyncio.sleep(300)  # 5분마다 정리
                await self._cleanup_old_data()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

    async def _cleanup_old_data(self):
        """오래된 호출 기록 삭제"""
        cutoff = datetime.utcnow() - timedelta(seconds=self._window_size)

        async with self._lock:
            for exchange in self._calls:
                while self._calls[exchange] and self._calls[exchange][0].timestamp < cutoff:
                    self._calls[exchange].popleft()

    def get_metrics(self, exchange: Optional[str] = None) -> Dict:
        """API 메트릭스 조회"""
        if exchange:
            metrics = self._metrics.get(exchange)
            if metrics:
                return {
                    'exchange': metrics.exchange,
                    'total_calls': metrics.total_calls,
                    'error_calls': metrics.error_calls,
                    'error_rate': (metrics.error_calls / metrics.total_calls * 100) if metrics.total_calls > 0 else 0,
                    'rate_limited_count': metrics.rate_limited_count,
                    'avg_response_time': round(metrics.avg_response_time, 2),
                    'last_call': metrics.last_call.isoformat() if metrics.last_call else None,
                    'limit': metrics.limit,
                    'remaining': metrics.remaining,
                }
            return {}

        # 모든 거래소 메트릭스
        return {
            ex: {
                'exchange': m.exchange,
                'total_calls': m.total_calls,
                'error_calls': m.error_calls,
                'error_rate': (m.error_calls / m.total_calls * 100) if m.total_calls > 0 else 0,
                'avg_response_time': round(m.avg_response_time, 2),
                'remaining': m.remaining,
                'limit': m.limit,
            }
            for ex, m in self._metrics.items()
        }

    def get_recent_calls(self, exchange: str, limit: int = 100) -> List[Dict]:
        """최근 API 호출 기록 조회"""
        if exchange not in self._calls:
            return []

        calls = list(self._calls[exchange])[-limit:]
        return [
            {
                'timestamp': c.timestamp.isoformat(),
                'endpoint': c.endpoint,
                'status': c.status,
                'response_time': c.response_time,
            }
            for c in reversed(calls)
        ]


# 전역 API 모니터 인스턴스
api_monitor = ApiMonitor()

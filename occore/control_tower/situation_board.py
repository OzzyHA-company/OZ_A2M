"""
OZ_A2M 제1부서: 관제탑센터 - 실시간 전황판

Single Pane of Glass - 통합 모니터링 대시보드
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from decimal import Decimal
from enum import Enum
import json

from .collector import DataCollector, MarketSnapshot
from .alert_manager import AlertManager, AlertLevel

logger = logging.getLogger(__name__)


class MarketStatus(Enum):
    """시장 상태"""
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    MAINTENANCE = "maintenance"


@dataclass
class SystemHealth:
    """시스템 건강 상태"""
    cpu_usage: float
    memory_usage: float
    disk_usage: float
    network_latency_ms: float
    timestamp: datetime
    status: MarketStatus = MarketStatus.NORMAL


@dataclass
class BotStatus:
    """봇 상태"""
    bot_id: str
    name: str
    status: str  # 'running', 'stopped', 'error'
    last_activity: datetime
    profit_24h: Decimal
    trade_count_24h: int
    error_count: int
    current_position: Optional[str] = None


@dataclass
class SituationReport:
    """전황 보고서"""
    timestamp: datetime
    market_status: MarketStatus
    exchanges_online: int
    exchanges_offline: int
    total_volume_24h: Decimal
    best_performing_bot: Optional[str]
    worst_performing_bot: Optional[str]
    active_alerts: int
    critical_alerts: int
    market_snapshots: Dict[str, MarketSnapshot] = field(default_factory=dict)
    bot_statuses: Dict[str, BotStatus] = field(default_factory=dict)
    system_health: Optional[SystemHealth] = None


class SituationBoard:
    """
    실시간 전황판

    기능:
    - 통합 데이터 수집 현황
    - 봇 상태 모니터링
    - 시스템 건강 상태
    - 알림 집계 및 표시
    """

    def __init__(self, collector: DataCollector, alert_manager: AlertManager,
                 config: Optional[Dict] = None):
        self.config = config or {}
        self.collector = collector
        self.alert_manager = alert_manager

        # 상태 저장
        self._bot_statuses: Dict[str, BotStatus] = {}
        self._system_health_history: List[SystemHealth] = []
        self._current_report: Optional[SituationReport] = None

        # 설정
        self._update_interval = self.config.get('update_interval_seconds', 5)
        self._health_history_limit = self.config.get('health_history_limit', 100)

        # 콜백
        self._callbacks: List[Callable] = []
        self._running = False
        self._update_task: Optional[asyncio.Task] = None

        # 데이터 구독
        self.collector.on_data(self._on_collector_data)

    async def start(self):
        """전황판 업데이트 시작"""
        if self._running:
            return

        self._running = True
        self._update_task = asyncio.create_task(self._update_loop())
        logger.info("Situation board started")

    async def stop(self):
        """전황판 업데이트 중지"""
        self._running = False
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
        logger.info("Situation board stopped")

    async def _update_loop(self):
        """전황판 업데이트 루프"""
        while self._running:
            try:
                await self._refresh_situation()
                await asyncio.sleep(self._update_interval)
            except Exception as e:
                logger.error(f"Situation board update error: {e}")
                await asyncio.sleep(self._update_interval)

    async def _refresh_situation(self):
        """전황 정보 갱신"""
        try:
            # 시장 스냅샷 수집
            market_snapshots = self.collector.get_all_snapshots()

            # 거래소 상태
            exchange_status = self.collector.get_exchange_status()
            online_count = sum(1 for s in exchange_status.values() if s['connection'] == 'connected')
            offline_count = len(exchange_status) - online_count

            # 시장 상태 결정
            market_status = self._determine_market_status(online_count, offline_count, market_snapshots)

            # 24시간 거래량
            total_volume = Decimal('0')
            for snapshot in market_snapshots.values():
                total_volume += snapshot.total_volume

            # 알림 상태
            alerts = self.alert_manager.get_active_alerts()
            critical_alerts = sum(1 for a in alerts if a.level == AlertLevel.CRITICAL)

            # 봇 성과 분석
            best_bot, worst_bot = self._analyze_bot_performance()

            # 시스템 건강 상태
            system_health = await self._check_system_health()

            # 전황 보고서 생성
            self._current_report = SituationReport(
                timestamp=datetime.now(),
                market_status=market_status,
                exchanges_online=online_count,
                exchanges_offline=offline_count,
                total_volume_24h=total_volume,
                best_performing_bot=best_bot,
                worst_performing_bot=worst_bot,
                active_alerts=len(alerts),
                critical_alerts=critical_alerts,
                market_snapshots=market_snapshots,
                bot_statuses=self._bot_statuses.copy(),
                system_health=system_health
            )

            # 콜백 알림
            self._notify('situation_update', self._current_report)

        except Exception as e:
            logger.error(f"Error refreshing situation: {e}")

    def _determine_market_status(self, online: int, offline: int,
                                  snapshots: Dict[str, MarketSnapshot]) -> MarketStatus:
        """시장 상태 결정"""
        if offline > online:
            return MarketStatus.CRITICAL

        if offline > 0:
            return MarketStatus.WARNING

        # 가격 변동성 확인
        high_variance_count = sum(
            1 for s in snapshots.values() if s.price_variance > 5.0
        )

        if high_variance_count > len(snapshots) / 2:
            return MarketStatus.WARNING

        return MarketStatus.NORMAL

    def _analyze_bot_performance(self) -> tuple[Optional[str], Optional[str]]:
        """봇 성과 분석"""
        if not self._bot_statuses:
            return None, None

        sorted_bots = sorted(
            self._bot_statuses.items(),
            key=lambda x: x[1].profit_24h,
            reverse=True
        )

        best = sorted_bots[0][0] if sorted_bots else None
        worst = sorted_bots[-1][0] if sorted_bots else None

        return best, worst

    async def _check_system_health(self) -> SystemHealth:
        """시스템 건강 상태 체크"""
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            # 네트워크 지연 시간 측정
            latency = await self._measure_network_latency()

            # 상태 결정
            status = MarketStatus.NORMAL
            if cpu > 90 or memory.percent > 90 or disk.percent > 90:
                status = MarketStatus.CRITICAL
            elif cpu > 70 or memory.percent > 80 or disk.percent > 80:
                status = MarketStatus.WARNING

            health = SystemHealth(
                cpu_usage=cpu,
                memory_usage=memory.percent,
                disk_usage=disk.percent,
                network_latency_ms=latency,
                timestamp=datetime.now(),
                status=status
            )

            # 히스토리 저장
            self._system_health_history.append(health)
            if len(self._system_health_history) > self._health_history_limit:
                self._system_health_history.pop(0)

            return health

        except Exception as e:
            logger.error(f"Error checking system health: {e}")
            return SystemHealth(
                cpu_usage=0,
                memory_usage=0,
                disk_usage=0,
                network_latency_ms=0,
                timestamp=datetime.now(),
                status=MarketStatus.MAINTENANCE
            )

    async def _measure_network_latency(self) -> float:
        """네트워크 지연 시간 측정"""
        try:
            import aiohttp

            start = asyncio.get_event_loop().time()
            async with aiohttp.ClientSession() as session:
                async with session.get('https://1.1.1.1', timeout=5) as resp:
                    await resp.read()

            elapsed = (asyncio.get_event_loop().time() - start) * 1000
            return elapsed

        except Exception:
            return -1  # 측정 실패

    def _on_collector_data(self, data_type: str, data: Any):
        """데이터 수집 콜백"""
        if data_type == 'market_snapshot':
            # 시장 스냅샷 업데이트
            pass

    def update_bot_status(self, bot_status: BotStatus):
        """봇 상태 업데이트"""
        self._bot_statuses[bot_status.bot_id] = bot_status

    def get_current_report(self) -> Optional[SituationReport]:
        """현재 전황 보고서 조회"""
        return self._current_report

    def get_market_summary(self) -> Dict[str, Any]:
        """시장 요약 정보 조회"""
        if not self._current_report:
            return {}

        snapshots = self._current_report.market_snapshots

        return {
            'timestamp': self._current_report.timestamp.isoformat(),
            'status': self._current_report.market_status.value,
            'exchanges_online': self._current_report.exchanges_online,
            'exchanges_offline': self._current_report.exchanges_offline,
            'total_volume_24h': str(self._current_report.total_volume_24h),
            'tracked_symbols': list(snapshots.keys()),
            'symbol_count': len(snapshots),
            'active_alerts': self._current_report.active_alerts,
            'critical_alerts': self._current_report.critical_alerts
        }

    def get_exchange_comparison(self, symbol: str) -> Dict[str, Any]:
        """거래소별 가격 비교"""
        snapshot = self.collector.get_market_snapshot(symbol)
        if not snapshot:
            return {}

        exchanges = []
        for ex, ticker in snapshot.exchanges.items():
            exchanges.append({
                'exchange': ex,
                'price': float(ticker.last),
                'bid': float(ticker.bid),
                'ask': float(ticker.ask),
                'volume': float(ticker.volume_24h),
                'change_24h': ticker.change_24h_pct
            })

        # 가격 기준 정렬
        exchanges.sort(key=lambda x: x['price'], reverse=True)

        return {
            'symbol': symbol,
            'timestamp': snapshot.timestamp.isoformat(),
            'average_price': float(snapshot.average_price),
            'price_variance_pct': snapshot.price_variance,
            'exchanges': exchanges,
            'arbitrage_opportunities': snapshot.arbitrage_opportunities
        }

    def get_bot_dashboard(self) -> Dict[str, Any]:
        """봇 대시보드 데이터"""
        bots = []
        total_profit = Decimal('0')
        total_trades = 0

        for bot_id, status in self._bot_statuses.items():
            bots.append({
                'bot_id': bot_id,
                'name': status.name,
                'status': status.status,
                'profit_24h': float(status.profit_24h),
                'trades_24h': status.trade_count_24h,
                'error_count': status.error_count,
                'last_activity': status.last_activity.isoformat()
            })
            total_profit += status.profit_24h
            total_trades += status.trade_count_24h

        # 상태별 카운트
        status_count = {}
        for b in bots:
            status_count[b['status']] = status_count.get(b['status'], 0) + 1

        return {
            'timestamp': datetime.now().isoformat(),
            'total_bots': len(bots),
            'total_profit_24h': float(total_profit),
            'total_trades_24h': total_trades,
            'status_summary': status_count,
            'bots': bots
        }

    def on_update(self, callback: Callable):
        """전황 업데이트 콜백 등록"""
        self._callbacks.append(callback)

    def _notify(self, event_type: str, data: Any):
        """콜백 알림"""
        for callback in self._callbacks:
            try:
                callback(event_type, data)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def export_report(self, format: str = 'json') -> str:
        """전황 보고서 내보내기"""
        if not self._current_report:
            return ""

        report = {
            'timestamp': self._current_report.timestamp.isoformat(),
            'market_status': self._current_report.market_status.value,
            'exchanges': {
                'online': self._current_report.exchanges_online,
                'offline': self._current_report.exchanges_offline
            },
            'volume_24h': str(self._current_report.total_volume_24h),
            'bots_performance': {
                'best': self._current_report.best_performing_bot,
                'worst': self._current_report.worst_performing_bot
            },
            'alerts': {
                'active': self._current_report.active_alerts,
                'critical': self._current_report.critical_alerts
            }
        }

        if format == 'json':
            return json.dumps(report, indent=2)

        return str(report)

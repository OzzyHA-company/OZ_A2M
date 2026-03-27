"""
OZ_A2M 제1부서: 관제탑센터 - 알림 관리자

실시간 알림 생성, 집계, 라우팅
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import json

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """알림 수준"""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertCategory(Enum):
    """알림 카테고리"""
    PRICE = "price"
    VOLUME = "volume"
    SYSTEM = "system"
    CONNECTION = "connection"
    SECURITY = "security"
    BOT = "bot"
    ARBITRAGE = "arbitrage"


@dataclass
class Alert:
    """알림 데이터"""
    id: str
    level: AlertLevel
    category: AlertCategory
    title: str
    message: str
    timestamp: datetime
    source: str  # 생성 출처 (exchange, bot, system)
    metadata: Dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    auto_resolve: bool = False
    resolved_at: Optional[datetime] = None


class AlertManager:
    """
    알림 관리자

    기능:
    - 알림 생성 및 저장
    - 중복 알림 방지
    - 알림 집계 및 라우팅
    - 자동 해결 (조건 충족 시)
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._alerts: Dict[str, Alert] = {}
        self._alert_history: List[Alert] = []
        self._callbacks: List[Callable] = []
        self._rules: List[Dict] = []

        # 설정
        self._dedup_window = self.config.get('dedup_window_seconds', 300)  # 5분
        self._history_limit = self.config.get('history_limit', 1000)
        self._auto_resolve_rules = self.config.get('auto_resolve_rules', [])

        # 알림 카운터
        self._alert_counter = 0

    def create_alert(self, level: AlertLevel, category: AlertCategory,
                     title: str, message: str, source: str,
                     metadata: Optional[Dict] = None,
                     auto_resolve: bool = False) -> Optional[Alert]:
        """알림 생성"""
        try:
            # 중복 알림 체크
            if self._is_duplicate(category, title, source):
                logger.debug(f"Duplicate alert suppressed: {title}")
                return None

            self._alert_counter += 1
            alert_id = f"ALT-{datetime.now().strftime('%Y%m%d')}-{self._alert_counter:04d}"

            alert = Alert(
                id=alert_id,
                level=level,
                category=category,
                title=title,
                message=message,
                timestamp=datetime.now(),
                source=source,
                metadata=metadata or {},
                auto_resolve=auto_resolve
            )

            self._alerts[alert_id] = alert
            self._alert_history.append(alert)

            # 히스토리 크기 제한
            if len(self._alert_history) > self._history_limit:
                self._alert_history.pop(0)

            # 알림 발송
            self._notify_alert(alert)

            logger.info(f"Alert created: [{level.value.upper()}] {title}")
            return alert

        except Exception as e:
            logger.error(f"Error creating alert: {e}")
            return None

    def _is_duplicate(self, category: AlertCategory, title: str, source: str) -> bool:
        """중복 알림 체크"""
        cutoff = datetime.now() - timedelta(seconds=self._dedup_window)

        for alert in self._alerts.values():
            if (alert.category == category and
                alert.title == title and
                alert.source == source and
                alert.timestamp > cutoff and
                not alert.resolved_at):
                return True

        return False

    def acknowledge_alert(self, alert_id: str, user: str) -> bool:
        """알림 확인 처리"""
        if alert_id not in self._alerts:
            return False

        alert = self._alerts[alert_id]
        alert.acknowledged = True
        alert.acknowledged_by = user
        alert.acknowledged_at = datetime.now()

        logger.info(f"Alert {alert_id} acknowledged by {user}")
        self._notify_alert_update(alert)
        return True

    def resolve_alert(self, alert_id: str, reason: str = "") -> bool:
        """알림 해결 처리"""
        if alert_id not in self._alerts:
            return False

        alert = self._alerts[alert_id]
        alert.resolved_at = datetime.now()

        logger.info(f"Alert {alert_id} resolved: {reason}")
        self._notify_alert_update(alert)
        return True

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        """특정 알림 조회"""
        return self._alerts.get(alert_id)

    def get_active_alerts(self, level: Optional[AlertLevel] = None,
                          category: Optional[AlertCategory] = None) -> List[Alert]:
        """활성 알림 조회"""
        alerts = [
            a for a in self._alerts.values()
            if not a.resolved_at
        ]

        if level:
            alerts = [a for a in alerts if a.level == level]

        if category:
            alerts = [a for a in alerts if a.category == category]

        # 심각도순 정렬
        level_order = {
            AlertLevel.CRITICAL: 0,
            AlertLevel.HIGH: 1,
            AlertLevel.MEDIUM: 2,
            AlertLevel.LOW: 3,
            AlertLevel.INFO: 4
        }
        alerts.sort(key=lambda x: level_order.get(x.level, 99))

        return alerts

    def get_alert_summary(self) -> Dict[str, Any]:
        """알림 요약 조회"""
        active = self.get_active_alerts()

        by_level = {}
        by_category = {}

        for alert in active:
            level = alert.level.value
            by_level[level] = by_level.get(level, 0) + 1

            category = alert.category.value
            by_category[category] = by_category.get(category, 0) + 1

        critical_unack = sum(
            1 for a in active
            if a.level == AlertLevel.CRITICAL and not a.acknowledged
        )

        return {
            'total_active': len(active),
            'critical_unacknowledged': critical_unack,
            'by_level': by_level,
            'by_category': by_category,
            'recent_alerts': [
                {
                    'id': a.id,
                    'level': a.level.value,
                    'title': a.title,
                    'timestamp': a.timestamp.isoformat(),
                    'acknowledged': a.acknowledged
                }
                for a in active[:10]
            ]
        }

    def on_alert(self, callback: Callable):
        """알림 수신 콜백 등록"""
        self._callbacks.append(callback)

    def _notify_alert(self, alert: Alert):
        """알림 콜백 발송"""
        for callback in self._callbacks:
            try:
                callback('new_alert', alert)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")

    def _notify_alert_update(self, alert: Alert):
        """알림 업데이트 콜백 발송"""
        for callback in self._callbacks:
            try:
                callback('alert_update', alert)
            except Exception as e:
                logger.error(f"Alert update callback error: {e}")

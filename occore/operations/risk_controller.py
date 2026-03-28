"""
OZ_A2M Phase 5: 제7부서 운영팀 - 리스크 관리 및 Kill Switch

리스크 한도 관리, 일일 손실 제한, 포지션 크기 제한, Kill Switch
"""

import asyncio
import json
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
import logging

try:
    from gmqtt import Client as MQTTClient
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    MQTTClient = None

from .models import (
    RiskLimit, Position, Order, PositionSide,
    DailyStats, BotConfig
)
from .position_manager import PositionManager
from .execution_engine import ExecutionEngine

logger = logging.getLogger(__name__)


class RiskEvent:
    """리스크 이벤트"""
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    MAX_DAILY_LOSS = "max_daily_loss"
    MAX_POSITION_SIZE = "max_position_size"
    MAX_LEVERAGE = "max_leverage"
    MAX_ORDERS = "max_orders"
    KILL_SWITCH = "kill_switch"


@dataclass
class RiskAlert:
    """리스크 알림"""
    id: str
    event_type: str
    severity: str  # low, medium, high, critical
    message: str
    bot_id: Optional[str]
    symbol: Optional[str]
    value: Decimal
    limit: Decimal
    timestamp: datetime = field(default_factory=datetime.utcnow)
    acknowledged: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "severity": self.severity,
            "message": self.message,
            "bot_id": self.bot_id,
            "symbol": self.symbol,
            "value": str(self.value),
            "limit": str(self.limit),
            "timestamp": self.timestamp.isoformat(),
            "acknowledged": self.acknowledged
        }


class RiskController:
    """리스크 관리자"""

    def __init__(
        self,
        position_manager: PositionManager,
        execution_engine: ExecutionEngine,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        default_risk_limit: Optional[RiskLimit] = None
    ):
        """
        리스크 관리자 초기화

        Args:
            position_manager: 포지션 관리자
            execution_engine: 주문 실행 엔진
            mqtt_host: MQTT 브로커 호스트
            mqtt_port: MQTT 브로커 포트
            default_risk_limit: 기본 리스크 한도
        """
        self.position_manager = position_manager
        self.execution_engine = execution_engine

        # 리스크 한도 설정
        self.risk_limits: Dict[str, RiskLimit] = {}  # bot_id -> RiskLimit
        self.default_risk_limit = default_risk_limit or RiskLimit(
            id="default",
            bot_id=None,
            exchange=None
        )

        # 알림 히스토리
        self.alerts: List[RiskAlert] = []

        # Kill Switch 상태
        self.kill_switch_triggered: Dict[str, bool] = {}  # bot_id -> triggered
        self.global_kill_switch = False

        # MQTT
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.mqtt_client: Optional[Any] = None
        self._mqtt_connected = False

        # 모니터링
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False

        # 콜백
        self.on_risk_alert: Optional[Callable[[RiskAlert], None]] = None
        self.on_kill_switch: Optional[Callable[[str], None]] = None

        # 주문 카운터 (분당/일일)
        self.order_counter: Dict[str, Dict[str, int]] = {}  # bot_id -> {"minute": 0, "day": 0}
        self.order_counter_reset: Dict[str, datetime] = {}

    async def start(self):
        """리스크 관리자 시작"""
        # MQTT 연결
        if MQTT_AVAILABLE:
            await self._connect_mqtt()

        # 모니터링 시작
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_risk())

        logger.info("Risk controller started")

    async def stop(self):
        """리스크 관리자 중지"""
        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # MQTT 연결 해제
        if self.mqtt_client:
            await self.mqtt_client.disconnect()

        logger.info("Risk controller stopped")

    async def _connect_mqtt(self):
        """MQTT 연결"""
        try:
            self.mqtt_client = MQTTClient("risk_controller")
            await self.mqtt_client.connect(self.mqtt_host, self.mqtt_port)
            self._mqtt_connected = True
            logger.info("MQTT connected for risk alerts")
        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")
            self._mqtt_connected = False

    def set_risk_limit(self, bot_id: str, limit: RiskLimit):
        """봇별 리스크 한도 설정"""
        self.risk_limits[bot_id] = limit
        logger.info(f"Risk limit set for bot {bot_id}")

    def get_risk_limit(self, bot_id: Optional[str] = None) -> RiskLimit:
        """리스크 한도 조회"""
        if bot_id and bot_id in self.risk_limits:
            return self.risk_limits[bot_id]
        return self.default_risk_limit

    async def check_order_risk(
        self,
        order: Order,
        bot_config: Optional[BotConfig] = None
    ) -> tuple[bool, Optional[str]]:
        """
        주문 리스크 검사

        Returns:
            (허용 여부, 거부 이유)
        """
        bot_id = order.bot_id
        limit = self.get_risk_limit(bot_id)

        if not limit.enabled:
            return True, None

        # Kill Switch 확인
        if self.global_kill_switch:
            return False, "Global kill switch triggered"

        if bot_id and self.kill_switch_triggered.get(bot_id, False):
            return False, f"Kill switch triggered for bot {bot_id}"

        # 주문 빈도 제한
        now = datetime.utcnow()
        counter_key = bot_id or "default"

        if counter_key not in self.order_counter:
            self.order_counter[counter_key] = {"minute": 0, "day": 0}
            self.order_counter_reset[counter_key] = now

        # 분당 제한
        if self.order_counter[counter_key]["minute"] >= limit.max_orders_per_minute:
            return False, f"Max orders per minute exceeded: {limit.max_orders_per_minute}"

        # 일일 제한
        if self.order_counter[counter_key]["day"] >= limit.max_orders_per_day:
            return False, f"Max orders per day exceeded: {limit.max_orders_per_day}"

        # 포지션 크기 제한
        if bot_id:
            positions = await self.position_manager.get_open_positions(bot_id)
            total_size = sum(p.amount for p in positions)
            if total_size + order.amount > limit.max_position_size:
                return False, f"Max position size would be exceeded"

        return True, None

    async def check_position_risk(self, position: Position) -> List[RiskAlert]:
        """포지션 리스크 검사"""
        alerts = []
        limit = self.get_risk_limit(position.bot_id)

        if not limit.enabled:
            return alerts

        # 미실현 손실 검사
        if position.unrealized_pnl < 0:
            # 일일 손실 한도
            today = date.today().isoformat()
            stats = await self.position_manager.get_daily_stats(today, position.bot_id)

            if stats.net_pnl < limit.max_daily_loss:
                alert = RiskAlert(
                    id=f"alert-{len(self.alerts)}",
                    event_type=RiskEvent.MAX_DAILY_LOSS,
                    severity="critical",
                    message=f"Daily loss limit exceeded: {stats.net_pnl} < {limit.max_daily_loss}",
                    bot_id=position.bot_id,
                    symbol=position.symbol,
                    value=stats.net_pnl,
                    limit=limit.max_daily_loss
                )
                alerts.append(alert)

        # 레버리지 제한
        if position.leverage > limit.max_leverage:
            alert = RiskAlert(
                id=f"alert-{len(self.alerts)}",
                event_type=RiskEvent.MAX_LEVERAGE,
                severity="high",
                message=f"Max leverage exceeded: {position.leverage} > {limit.max_leverage}",
                bot_id=position.bot_id,
                symbol=position.symbol,
                value=Decimal(str(position.leverage)),
                limit=Decimal(str(limit.max_leverage))
            )
            alerts.append(alert)

        return alerts

    async def trigger_kill_switch(self, bot_id: Optional[str] = None, reason: str = ""):
        """
        Kill Switch 트리거

        Args:
            bot_id: 특정 봇 (None이면 전역)
            reason: 트리거 사유
        """
        if bot_id:
            self.kill_switch_triggered[bot_id] = True
            logger.critical(f"Kill switch triggered for bot {bot_id}: {reason}")
        else:
            self.global_kill_switch = True
            logger.critical(f"Global kill switch triggered: {reason}")

        # 모든 포지션 청산
        if bot_id:
            positions = await self.position_manager.get_open_positions(bot_id)
        else:
            positions = await self.position_manager.get_open_positions()

        for position in positions:
            if bot_id is None or position.bot_id == bot_id:
                await self.position_manager.close_position(position.id)
                logger.info(f"Position closed by kill switch: {position.id}")

        # 모든 미체결 주문 취소
        open_orders = await self.execution_engine.get_open_orders()
        for order in open_orders:
            if bot_id is None or order.bot_id == bot_id:
                await self.execution_engine.cancel_order(order.id)
                logger.info(f"Order cancelled by kill switch: {order.id}")

        # 알림 발송
        alert = RiskAlert(
            id=f"kill-switch-{len(self.alerts)}",
            event_type=RiskEvent.KILL_SWITCH,
            severity="critical",
            message=f"Kill switch triggered: {reason}",
            bot_id=bot_id,
            symbol=None,
            value=Decimal("0"),
            limit=Decimal("0")
        )
        await self._send_alert(alert)

        # 콜백
        if self.on_kill_switch:
            self.on_kill_switch(bot_id or "global")

    async def reset_kill_switch(self, bot_id: Optional[str] = None):
        """Kill Switch 해제"""
        if bot_id:
            self.kill_switch_triggered[bot_id] = False
            logger.info(f"Kill switch reset for bot {bot_id}")
        else:
            self.global_kill_switch = False
            self.kill_switch_triggered.clear()
            logger.info("Global kill switch reset")

    async def _monitor_risk(self):
        """리스크 모니터링 루프"""
        while self._running:
            try:
                # 열린 포지션 모니터링
                positions = await self.position_manager.get_open_positions()

                for position in positions:
                    alerts = await self.check_position_risk(position)

                    for alert in alerts:
                        self.alerts.append(alert)
                        await self._send_alert(alert)

                        if alert.severity == "critical":
                            await self.trigger_kill_switch(
                                position.bot_id,
                                alert.message
                            )

                # 주문 카운터 리셋
                await self._reset_order_counters()

                await asyncio.sleep(5)  # 5초 간격

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Risk monitoring error: {e}")
                await asyncio.sleep(10)

    async def _reset_order_counters(self):
        """주문 카운터 리셋"""
        now = datetime.utcnow()

        for key, reset_time in list(self.order_counter_reset.items()):
            elapsed = (now - reset_time).total_seconds()

            # 분당 카운터 리셋
            if elapsed >= 60:
                if key in self.order_counter:
                    self.order_counter[key]["minute"] = 0

            # 일일 카운터 리셋
            if elapsed >= 86400:  # 24시간
                if key in self.order_counter:
                    self.order_counter[key]["day"] = 0
                    self.order_counter_reset[key] = now

    def increment_order_counter(self, bot_id: Optional[str] = None):
        """주문 카운터 증가"""
        key = bot_id or "default"

        if key not in self.order_counter:
            self.order_counter[key] = {"minute": 0, "day": 0}
            self.order_counter_reset[key] = datetime.utcnow()

        self.order_counter[key]["minute"] += 1
        self.order_counter[key]["day"] += 1

    async def _send_alert(self, alert: RiskAlert):
        """알림 발송"""
        # MQTT 발송
        if self._mqtt_connected and self.mqtt_client:
            try:
                topic = f"risk/alerts/{alert.severity}"
                payload = json.dumps(alert.to_dict())
                self.mqtt_client.publish(topic, payload)
            except Exception as e:
                logger.error(f"MQTT alert error: {e}")

        # 콜백
        if self.on_risk_alert:
            self.on_risk_alert(alert)

        logger.warning(f"Risk alert: {alert.message}")

    def get_risk_summary(self, bot_id: Optional[str] = None) -> Dict[str, Any]:
        """리스크 요약"""
        limit = self.get_risk_limit(bot_id)

        # 주문 카운터
        key = bot_id or "default"
        counters = self.order_counter.get(key, {"minute": 0, "day": 0})

        # Kill Switch 상태
        kill_switch = self.global_kill_switch
        if bot_id:
            kill_switch = kill_switch or self.kill_switch_triggered.get(bot_id, False)

        # 미확인 알림
        unacknowledged = [a for a in self.alerts if not a.acknowledged]
        if bot_id:
            unacknowledged = [a for a in unacknowledged if a.bot_id == bot_id]

        return {
            "bot_id": bot_id,
            "kill_switch_triggered": kill_switch,
            "orders_per_minute": counters["minute"],
            "orders_per_day": counters["day"],
            "max_orders_per_minute": limit.max_orders_per_minute,
            "max_orders_per_day": limit.max_orders_per_day,
            "unacknowledged_alerts": len(unacknowledged),
            "daily_loss_limit": str(limit.max_daily_loss),
            "position_size_limit": str(limit.max_position_size)
        }

    def acknowledge_alert(self, alert_id: str) -> bool:
        """알림 확인"""
        for alert in self.alerts:
            if alert.id == alert_id:
                alert.acknowledged = True
                return True
        return False

    def get_alert_history(
        self,
        bot_id: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100
    ) -> List[RiskAlert]:
        """알림 히스토리"""
        alerts = self.alerts

        if bot_id:
            alerts = [a for a in alerts if a.bot_id == bot_id]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]

        # 시간 역순
        alerts.sort(key=lambda a: a.timestamp, reverse=True)
        return alerts[:limit]


if __name__ == "__main__":
    # 테스트
    async def test():
        engine = ExecutionEngine(dry_run=True)
        await engine.start()

        pm = PositionManager(engine)
        await pm.connect()

        rc = RiskController(pm, engine)
        await rc.start()

        # 리스크 한도 설정
        limit = RiskLimit(
            id="test-limit",
            bot_id="test-bot",
            max_daily_loss=Decimal("-500"),
            max_position_size=Decimal("0.01")
        )
        rc.set_risk_limit("test-bot", limit)

        # 주문 리스크 검사
        order = Order(
            id="test-order",
            order_id=None,
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=Decimal("0.001"),
            bot_id="test-bot"
        )

        allowed, reason = await rc.check_order_risk(order)
        print(f"Order allowed: {allowed}, Reason: {reason}")

        # 리스크 요약
        summary = rc.get_risk_summary("test-bot")
        print(f"Risk summary: {summary}")

        await rc.stop()
        await pm.disconnect()
        await engine.stop()

    asyncio.run(test())

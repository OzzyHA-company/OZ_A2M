"""
OZ_A2M Phase 5: 제7부서 운영팀 - 봇 매니저

봇 생명주기 관리 (시작/중지/재시작), 상태 모니터링, MQTT 연동
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any, Type
from dataclasses import dataclass, field

# Use unified aiomqtt-based MQTT client
import aiomqtt
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.messaging.mqtt_client import MQTTClient, MQTTConfig
MQTT_AVAILABLE = True

from .models import BotConfig, BotStatus, BotStrategy
from .execution_engine import ExecutionEngine
from .position_manager import PositionManager
from .risk_controller import RiskController
from .exchange_connector import ExchangeConnector, MockExchangeConnector

logger = logging.getLogger(__name__)


@dataclass
class BotInstance:
    """봇 인스턴스"""
    config: BotConfig
    task: Optional[asyncio.Task] = None
    engine: Optional[ExecutionEngine] = None
    position_manager: Optional[PositionManager] = None
    risk_controller: Optional[RiskController] = None
    connector: Optional[ExchangeConnector] = None
    logs: List[Dict] = field(default_factory=list)
    start_time: Optional[datetime] = None
    error_count: int = 0
    last_error: Optional[str] = None


class BotManager:
    """봇 매니저"""

    def __init__(
        self,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        dry_run: bool = True
    ):
        """
        봇 매니저 초기화

        Args:
            mqtt_host: MQTT 브로커 호스트
            mqtt_port: MQTT 브로커 포트
            dry_run: 모의 거래 모드
        """
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.dry_run = dry_run

        # 봇 저장소
        self.bots: Dict[str, BotInstance] = {}  # bot_id -> BotInstance
        self.configs: Dict[str, BotConfig] = {}  # bot_id -> BotConfig

        # 봇 클래스 레지스트리
        self.bot_classes: Dict[str, Type] = {}

        # MQTT
        self.mqtt_client: Optional[MQTTClient] = None
        self._mqtt_connected = False

        # 콜백
        self.on_bot_start: Optional[Callable[[str], None]] = None
        self.on_bot_stop: Optional[Callable[[str], None]] = None
        self.on_bot_error: Optional[Callable[[str, str], None]] = None

        # 상태 모니터링
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """봇 매니저 시작"""
        # MQTT 연결
        if MQTT_AVAILABLE:
            await self._connect_mqtt()

        # 상태 모니터링 시작
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_bots())

        logger.info("Bot manager started")

    async def stop(self):
        """봇 매니저 중지 - 모든 봇 정지"""
        self._running = False

        # 모든 봇 중지
        for bot_id in list(self.bots.keys()):
            await self.stop_bot(bot_id)

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # MQTT 연결 해제
        if self.mqtt_client:
            await self.mqtt_client.disconnect()

        logger.info("Bot manager stopped")

    async def _connect_mqtt(self):
        """MQTT 연결"""
        try:
            config = MQTTConfig(
                host=self.mqtt_host,
                port=self.mqtt_port,
                client_id="bot_manager"
            )
            self.mqtt_client = MQTTClient(config)
            await self.mqtt_client.connect()

            # 명령 토픽 구독
            await self.mqtt_client.subscribe("bots/+/command", self._on_mqtt_message)
            self._mqtt_connected = True

            logger.info("MQTT connected for bot management")
        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")
            self._mqtt_connected = False

    async def _on_mqtt_message(self, message: aiomqtt.Message):
        """MQTT 메시지 수신"""
        try:
            topic = message.topic.value
            payload = message.payload.decode()
            msg = json.loads(payload)
            command = msg.get("command")
            bot_id = msg.get("bot_id")

            if command and bot_id:
                await self._handle_command(bot_id, command, msg)
        except Exception as e:
            logger.error(f"MQTT message error: {e}")

    async def _handle_command(self, bot_id: str, command: str, params: Dict):
        """명령 처리"""
        if command == "start":
            await self.start_bot(bot_id)
        elif command == "stop":
            await self.stop_bot(bot_id)
        elif command == "pause":
            await self.pause_bot(bot_id)
        elif command == "resume":
            await self.resume_bot(bot_id)
        elif command == "restart":
            await self.restart_bot(bot_id)

    def register_bot_class(self, strategy: BotStrategy, bot_class: Type):
        """봇 클래스 등록"""
        self.bot_classes[strategy.value] = bot_class
        logger.info(f"Bot class registered for {strategy.value}")

    async def create_bot(self, config: BotConfig) -> str:
        """
        봇 생성

        Args:
            config: 봇 설정

        Returns:
            봇 ID
        """
        self.configs[config.id] = config

        # 봇 인스턴스 생성
        instance = BotInstance(config=config)
        self.bots[config.id] = instance

        logger.info(f"Bot created: {config.id} ({config.name})")
        return config.id

    async def start_bot(self, bot_id: str) -> bool:
        """봇 시작"""
        instance = self.bots.get(bot_id)
        if not instance:
            logger.error(f"Bot not found: {bot_id}")
            return False

        if instance.task and not instance.task.done():
            logger.warning(f"Bot already running: {bot_id}")
            return False

        config = instance.config

        # 실행 엔진 생성
        if self.dry_run or config.dry_run:
            connector = MockExchangeConnector(config.exchange)
        else:
            connector = ExchangeConnector(config.exchange)

        await connector.connect()

        engine = ExecutionEngine(connector, dry_run=self.dry_run or config.dry_run)
        await engine.start()

        position_manager = PositionManager(engine)
        await position_manager.connect()

        risk_controller = RiskController(position_manager, engine)
        await risk_controller.start()

        # 인스턴스 업데이트
        instance.connector = connector
        instance.engine = engine
        instance.position_manager = position_manager
        instance.risk_controller = risk_controller
        instance.start_time = datetime.utcnow()
        instance.error_count = 0
        instance.last_error = None

        # 봇 태스크 시작
        bot_class = self.bot_classes.get(config.strategy.value)
        if bot_class:
            instance.task = asyncio.create_task(
                self._run_bot(bot_id, bot_class, config, instance)
            )
        else:
            logger.error(f"No bot class registered for {config.strategy.value}")
            return False

        # 상태 업데이트
        config.status = BotStatus.RUNNING
        config.last_run_at = datetime.utcnow()

        # MQTT 발송
        await self._publish_status(bot_id, "started")

        # 콜백
        if self.on_bot_start:
            self.on_bot_start(bot_id)

        logger.info(f"Bot started: {bot_id}")
        return True

    async def _run_bot(
        self,
        bot_id: str,
        bot_class: Type,
        config: BotConfig,
        instance: BotInstance
    ):
        """봇 실행 루프"""
        try:
            # 봇 인스턴스 생성
            bot = bot_class(
                config=config,
                engine=instance.engine,
                position_manager=instance.position_manager,
                risk_controller=instance.risk_controller
            )

            # 봇 실행
            await bot.run()

        except asyncio.CancelledError:
            logger.info(f"Bot cancelled: {bot_id}")
            raise

        except Exception as e:
            logger.error(f"Bot error: {bot_id} - {type(e).__name__}: {e}")
            instance.error_count += 1
            instance.last_error = str(e)
            config.status = BotStatus.ERROR

            # 안전한 봇 정지
            try:
                await self._safe_stop_bot(instance)
            except Exception as stop_error:
                logger.error(f"Failed to safely stop bot {bot_id}: {stop_error}")

            # 콜백
            if self.on_bot_error:
                self.on_bot_error(bot_id, str(e))

            # MQTT 발송
            await self._publish_status(bot_id, "error", error=str(e))

    async def _safe_stop_bot(self, instance: BotInstance):
        """봇 인스턴스 안전 정지"""
        try:
            if instance.risk_controller:
                await instance.risk_controller.stop()
        except Exception as e:
            logger.warning(f"Error stopping risk controller: {e}")

        try:
            if instance.position_manager:
                await instance.position_manager.disconnect()
        except Exception as e:
            logger.warning(f"Error disconnecting position manager: {e}")

        try:
            if instance.engine:
                await instance.engine.stop()
        except Exception as e:
            logger.warning(f"Error stopping engine: {e}")

        try:
            if instance.connector:
                await instance.connector.disconnect()
        except Exception as e:
            logger.warning(f"Error disconnecting exchange: {e}")

    async def stop_bot(self, bot_id: str) -> bool:
        """봇 중지"""
        instance = self.bots.get(bot_id)
        if not instance:
            logger.error(f"Bot not found: {bot_id}")
            return False

        # 태스크 취소
        if instance.task and not instance.task.done():
            instance.task.cancel()
            try:
                await instance.task
            except asyncio.CancelledError:
                pass

        # 정리
        if instance.risk_controller:
            await instance.risk_controller.stop()
        if instance.position_manager:
            await instance.position_manager.disconnect()
        if instance.engine:
            await instance.engine.stop()
        if instance.connector:
            await instance.connector.disconnect()

        # 상태 업데이트
        instance.config.status = BotStatus.STOPPED

        # MQTT 발송
        await self._publish_status(bot_id, "stopped")

        # 콜백
        if self.on_bot_stop:
            self.on_bot_stop(bot_id)

        logger.info(f"Bot stopped: {bot_id}")
        return True

    async def pause_bot(self, bot_id: str) -> bool:
        """봇 일시 중지"""
        instance = self.bots.get(bot_id)
        if not instance:
            return False

        instance.config.status = BotStatus.PAUSED
        await self._publish_status(bot_id, "paused")
        logger.info(f"Bot paused: {bot_id}")
        return True

    async def resume_bot(self, bot_id: str) -> bool:
        """봇 재개"""
        instance = self.bots.get(bot_id)
        if not instance:
            return False

        instance.config.status = BotStatus.RUNNING
        await self._publish_status(bot_id, "resumed")
        logger.info(f"Bot resumed: {bot_id}")
        return True

    async def restart_bot(self, bot_id: str) -> bool:
        """봇 재시작"""
        await self.stop_bot(bot_id)
        await asyncio.sleep(1)
        return await self.start_bot(bot_id)

    async def delete_bot(self, bot_id: str) -> bool:
        """봇 삭제"""
        if bot_id in self.bots:
            await self.stop_bot(bot_id)
            del self.bots[bot_id]
            del self.configs[bot_id]
            logger.info(f"Bot deleted: {bot_id}")
            return True
        return False

    def get_bot_status(self, bot_id: str) -> Optional[Dict[str, Any]]:
        """봇 상태 조회"""
        instance = self.bots.get(bot_id)
        if not instance:
            return None

        config = instance.config

        runtime = None
        if instance.start_time:
            runtime = (datetime.utcnow() - instance.start_time).total_seconds()

        return {
            "id": bot_id,
            "name": config.name,
            "strategy": config.strategy.value,
            "status": config.status.value,
            "exchange": config.exchange,
            "symbol": config.symbol,
            "dry_run": config.dry_run,
            "runtime_seconds": runtime,
            "error_count": instance.error_count,
            "last_error": instance.last_error,
            "log_count": len(instance.logs)
        }

    def get_all_status(self) -> List[Dict[str, Any]]:
        """모든 봇 상태 조회"""
        return [
            self.get_bot_status(bot_id)
            for bot_id in self.bots.keys()
        ]

    async def _monitor_bots(self):
        """봇 모니터링 루프"""
        while self._running:
            try:
                for bot_id, instance in self.bots.items():
                    config = instance.config

                    # 자동 재시작
                    if config.auto_restart and config.status == BotStatus.ERROR:
                        if instance.error_count < 3:  # 최대 3회 재시도
                            logger.info(f"Auto-restarting bot: {bot_id}")
                            await self.restart_bot(bot_id)

                    # 최대 실행 시간 체크
                    if config.max_runtime_hours and instance.start_time:
                        runtime = (datetime.utcnow() - instance.start_time).total_seconds() / 3600
                        if runtime >= config.max_runtime_hours:
                            logger.info(f"Max runtime reached for bot: {bot_id}")
                            await self.stop_bot(bot_id)

                    # 상태 발송
                    await self._publish_status(bot_id, "heartbeat")

                await asyncio.sleep(10)  # 10초 간격

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Bot monitoring error: {e}")
                await asyncio.sleep(30)

    async def _publish_status(self, bot_id: str, event: str, **kwargs):
        """MQTT 상태 발송"""
        if not self._mqtt_connected or not self.mqtt_client:
            return

        try:
            payload = {
                "bot_id": bot_id,
                "event": event,
                "timestamp": datetime.utcnow().isoformat(),
                **kwargs
            }
            topic = f"bots/{bot_id}/status"
            await self.mqtt_client.publish(topic, json.dumps(payload))
        except Exception as e:
            logger.error(f"MQTT publish error: {e}")

    def add_log(self, bot_id: str, level: str, message: str):
        """봇 로그 추가"""
        instance = self.bots.get(bot_id)
        if instance:
            instance.logs.append({
                "timestamp": datetime.utcnow().isoformat(),
                "level": level,
                "message": message
            })

            # 로그 제한 (최근 1000개)
            if len(instance.logs) > 1000:
                instance.logs = instance.logs[-1000:]

    def get_logs(self, bot_id: str, limit: int = 100) -> List[Dict]:
        """봇 로그 조회"""
        instance = self.bots.get(bot_id)
        if not instance:
            return []
        return instance.logs[-limit:]


class BaseBot:
    """기본 봇 클래스 (상속용)"""

    def __init__(
        self,
        config: BotConfig,
        engine: ExecutionEngine,
        position_manager: PositionManager,
        risk_controller: RiskController
    ):
        self.config = config
        self.engine = engine
        self.position_manager = position_manager
        self.risk_controller = risk_controller
        self._running = False

    async def run(self):
        """봇 실행 (오버라이드 필요)"""
        self._running = True
        while self._running and self.config.status == BotStatus.RUNNING:
            try:
                await self.tick()
                await asyncio.sleep(60)  # 기본 1분 간격
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Bot tick error: {e}")
                await asyncio.sleep(5)

    async def tick(self):
        """틱 처리 (오버라이드 필요)"""
        pass

    async def stop(self):
        """봇 중지"""
        self._running = False


if __name__ == "__main__":
    # 테스트
    async def test():
        manager = BotManager(dry_run=True)
        await manager.start()

        # 봇 설정 생성
        config = BotConfig(
            id="test-bot-001",
            name="Test Bot",
            strategy=BotStrategy.SCALPING,
            dry_run=True
        )

        bot_id = await manager.create_bot(config)
        print(f"Bot created: {bot_id}")

        # 상태 조회
        status = manager.get_bot_status(bot_id)
        print(f"Bot status: {status}")

        await manager.stop()

    asyncio.run(test())

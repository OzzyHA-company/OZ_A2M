"""
OZ_A2M Unified Bot Manager
제7부서 통합 봇 관리자

P1 작업: occore/operations/bot_manager 통합
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any, Type
from dataclasses import dataclass, field
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from lib.messaging.mqtt_client import MQTTClient, MQTTConfig
from lib.core.logger import get_logger

logger = get_logger(__name__)

# Import bot classes
from department_7.src.bot.scalper import ScalpingBot, BotState as ScalperState


@dataclass
class BotInstance:
    """통합 봇 인스턴스"""
    bot_id: str
    bot_type: str
    config: Dict[str, Any]
    instance: Optional[Any] = None
    task: Optional[asyncio.Task] = None
    state: str = "idle"
    start_time: Optional[datetime] = None
    error_count: int = 0
    last_error: Optional[str] = None
    logs: List[Dict] = field(default_factory=list)


class UnifiedBotManager:
    """
    통합 봇 매니저

    기능:
    - 모든 봇의 생명주기 관리
    - MQTT 명령 수신 및 처리
    - 상태 모니터링 및 보고
    - 자동 재시작 및 에러 복구
    """

    def __init__(
        self,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        dry_run: bool = True
    ):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.dry_run = dry_run

        # 봇 저장소
        self.bots: Dict[str, BotInstance] = {}

        # MQTT
        mqtt_config = MQTTConfig(
            host=mqtt_host,
            port=mqtt_port,
            client_id="unified_bot_manager"
        )
        self.mqtt = MQTTClient(config=mqtt_config)
        self._mqtt_connected = False

        # 상태
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None

        # 콜백
        self.on_bot_start: Optional[Callable[[str], None]] = None
        self.on_bot_stop: Optional[Callable[[str], None]] = None
        self.on_bot_error: Optional[Callable[[str, str], None]] = None

        logger.info("UnifiedBotManager initialized")

    async def start(self):
        """매니저 시작"""
        try:
            await self.mqtt.connect()
            await self.mqtt.subscribe("bots/+/command", self._on_mqtt_command)
            await self.mqtt.subscribe("manager/command", self._on_manager_command)
            self._mqtt_connected = True
            logger.info("MQTT connected for bot management")
        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")
            self._mqtt_connected = False

        # 모니터링 시작
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_bots())
        logger.info("UnifiedBotManager started")

    async def stop(self):
        """매니저 중지"""
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

        if self._mqtt_connected:
            await self.mqtt.disconnect()

        logger.info("UnifiedBotManager stopped")

    async def _on_mqtt_command(self, message):
        """MQTT 명령 처리"""
        try:
            topic = message.topic.value
            payload = message.payload.decode()
            msg = json.loads(payload)

            # 토픽에서 bot_id 추출 (bots/{bot_id}/command)
            parts = topic.split("/")
            if len(parts) >= 2:
                bot_id = parts[1]
                command = msg.get("command")
                await self._handle_command(bot_id, command, msg)
        except Exception as e:
            logger.error(f"Error handling MQTT command: {e}")

    async def _on_manager_command(self, message):
        """매니저 전역 명령 처리"""
        try:
            payload = message.payload.decode()
            msg = json.loads(payload)
            command = msg.get("command")

            if command == "status_all":
                await self._publish_all_status()
            elif command == "stop_all":
                for bot_id in list(self.bots.keys()):
                    await self.stop_bot(bot_id)
        except Exception as e:
            logger.error(f"Error handling manager command: {e}")

    async def _handle_command(self, bot_id: str, command: str, params: Dict):
        """봇 명령 처리"""
        if command == "start":
            bot_type = params.get("bot_type", "scalper")
            config = params.get("config", {})
            await self.create_and_start_bot(bot_id, bot_type, config)
        elif command == "stop":
            await self.stop_bot(bot_id)
        elif command == "pause":
            await self.pause_bot(bot_id)
        elif command == "resume":
            await self.resume_bot(bot_id)
        elif command == "restart":
            await self.restart_bot(bot_id)
        elif command == "status":
            await self._publish_bot_status(bot_id)

    async def create_and_start_bot(
        self,
        bot_id: str,
        bot_type: str = "scalper",
        config: Optional[Dict] = None
    ) -> bool:
        """봇 생성 및 시작"""
        config = config or {}

        if bot_id in self.bots:
            logger.warning(f"Bot {bot_id} already exists")
            return False

        # 봇 인스턴스 생성
        instance = BotInstance(
            bot_id=bot_id,
            bot_type=bot_type,
            config=config
        )

        try:
            if bot_type == "scalper":
                bot = ScalpingBot(
                    bot_id=bot_id,
                    symbol=config.get("symbol", "BTC/USDT"),
                    exchange_id=config.get("exchange", "binance"),
                    mqtt_host=self.mqtt_host,
                    mqtt_port=self.mqtt_port,
                    sandbox=self.dry_run
                )
                instance.instance = bot
            else:
                logger.error(f"Unknown bot type: {bot_type}")
                return False

            self.bots[bot_id] = instance

            # 봇 태스크 시작
            instance.task = asyncio.create_task(
                self._run_bot(bot_id, instance)
            )
            instance.start_time = datetime.utcnow()
            instance.state = "running"

            if self.on_bot_start:
                self.on_bot_start(bot_id)

            await self._publish_status(bot_id, "started")
            logger.info(f"Bot {bot_id} ({bot_type}) started")
            return True

        except Exception as e:
            logger.error(f"Failed to start bot {bot_id}: {e}")
            instance.last_error = str(e)
            instance.state = "error"
            return False

    async def _run_bot(self, bot_id: str, instance: BotInstance):
        """봇 실행 루프"""
        try:
            if isinstance(instance.instance, ScalpingBot):
                await instance.instance.run()

        except asyncio.CancelledError:
            logger.info(f"Bot {bot_id} cancelled")
            raise
        except Exception as e:
            logger.error(f"Bot {bot_id} error: {e}")
            instance.error_count += 1
            instance.last_error = str(e)
            instance.state = "error"

            # 안전 정지
            try:
                if isinstance(instance.instance, ScalpingBot):
                    await instance.instance.stop()
            except Exception as stop_error:
                logger.error(f"Error stopping bot {bot_id}: {stop_error}")

            if self.on_bot_error:
                self.on_bot_error(bot_id, str(e))

            await self._publish_status(bot_id, "error", error=str(e))

    async def stop_bot(self, bot_id: str) -> bool:
        """봇 중지"""
        instance = self.bots.get(bot_id)
        if not instance:
            logger.warning(f"Bot {bot_id} not found")
            return False

        # 태스크 취소
        if instance.task and not instance.task.done():
            instance.task.cancel()
            try:
                await instance.task
            except asyncio.CancelledError:
                pass

        # 봇 정지
        try:
            if isinstance(instance.instance, ScalpingBot):
                await instance.instance.stop()
        except Exception as e:
            logger.error(f"Error stopping bot {bot_id}: {e}")

        instance.state = "stopped"

        if self.on_bot_stop:
            self.on_bot_stop(bot_id)

        await self._publish_status(bot_id, "stopped")
        logger.info(f"Bot {bot_id} stopped")
        return True

    async def pause_bot(self, bot_id: str) -> bool:
        """봇 일시 중지"""
        instance = self.bots.get(bot_id)
        if not instance:
            return False

        instance.state = "paused"
        await self._publish_status(bot_id, "paused")
        logger.info(f"Bot {bot_id} paused")
        return True

    async def resume_bot(self, bot_id: str) -> bool:
        """봇 재개"""
        instance = self.bots.get(bot_id)
        if not instance:
            return False

        instance.state = "running"
        await self._publish_status(bot_id, "resumed")
        logger.info(f"Bot {bot_id} resumed")
        return True

    async def restart_bot(self, bot_id: str) -> bool:
        """봇 재시작"""
        instance = self.bots.get(bot_id)
        if not instance:
            return False

        config = instance.config.copy()
        bot_type = instance.bot_type

        await self.stop_bot(bot_id)
        await asyncio.sleep(1)

        # 인스턴스 제거 후 재생성
        if bot_id in self.bots:
            del self.bots[bot_id]

        return await self.create_and_start_bot(bot_id, bot_type, config)

    async def delete_bot(self, bot_id: str) -> bool:
        """봇 삭제"""
        if bot_id in self.bots:
            await self.stop_bot(bot_id)
            del self.bots[bot_id]
            logger.info(f"Bot {bot_id} deleted")
            return True
        return False

    def get_bot_status(self, bot_id: str) -> Optional[Dict[str, Any]]:
        """봇 상태 조회"""
        instance = self.bots.get(bot_id)
        if not instance:
            return None

        runtime = None
        if instance.start_time and instance.state == "running":
            runtime = (datetime.utcnow() - instance.start_time).total_seconds()

        # 봇별 상세 상태
        detail = {}
        if isinstance(instance.instance, ScalpingBot):
            try:
                detail = instance.instance.get_status()
            except Exception as e:
                logger.warning(f"Failed to get bot detail: {e}")

        return {
            "bot_id": bot_id,
            "bot_type": instance.bot_type,
            "state": instance.state,
            "runtime_seconds": runtime,
            "error_count": instance.error_count,
            "last_error": instance.last_error,
            "log_count": len(instance.logs),
            "detail": detail
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
                    # 자동 재시작
                    if instance.state == "error":
                        if instance.error_count < 3:
                            logger.info(f"Auto-restarting bot: {bot_id}")
                            await self.restart_bot(bot_id)

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
        if not self._mqtt_connected:
            return

        try:
            payload = {
                "bot_id": bot_id,
                "event": event,
                "timestamp": datetime.utcnow().isoformat(),
                **kwargs
            }
            topic = f"bots/{bot_id}/status"
            await self.mqtt.publish(topic, json.dumps(payload))
        except Exception as e:
            logger.error(f"MQTT publish error: {e}")

    async def _publish_bot_status(self, bot_id: str):
        """특정 봇 상태 발송"""
        status = self.get_bot_status(bot_id)
        if status:
            await self._publish_status(bot_id, "status", data=status)

    async def _publish_all_status(self):
        """모든 봇 상태 발송"""
        statuses = self.get_all_status()
        try:
            payload = {
                "bots": statuses,
                "timestamp": datetime.utcnow().isoformat()
            }
            await self.mqtt.publish("manager/status_all", json.dumps(payload))
        except Exception as e:
            logger.error(f"Failed to publish all status: {e}")

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


# 싱글톤 인스턴스
_manager_instance: Optional[UnifiedBotManager] = None


def get_bot_manager(
    mqtt_host: str = "localhost",
    mqtt_port: int = 1883,
    dry_run: bool = True
) -> UnifiedBotManager:
    """전역 매니저 인스턴스 가져오기"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = UnifiedBotManager(
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            dry_run=dry_run
        )
    return _manager_instance


async def main():
    """메인 실행"""
    manager = get_bot_manager(dry_run=True)

    # 콜백 설정
    def on_start(bot_id):
        print(f"🚀 Bot started: {bot_id}")

    def on_stop(bot_id):
        print(f"🛑 Bot stopped: {bot_id}")

    def on_error(bot_id, error):
        print(f"❌ Bot error: {bot_id} - {error}")

    manager.on_bot_start = on_start
    manager.on_bot_stop = on_stop
    manager.on_bot_error = on_error

    await manager.start()

    try:
        # 테스트 봇 생성
        await manager.create_and_start_bot(
            bot_id="scalper_1",
            bot_type="scalper",
            config={"symbol": "BTC/USDT", "exchange": "binance"}
        )

        # 60초 실행
        await asyncio.sleep(60)

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await manager.stop()


if __name__ == "__main__":
    asyncio.run(main())

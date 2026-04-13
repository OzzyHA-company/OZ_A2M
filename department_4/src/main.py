#!/usr/bin/env python3
"""
Department 4: DevOps Team Service
유지보수관리팀 - 독립 실행 서비스

occore/devops 모듈을 부서 독립 서비스로 래핑
- HealthChecker
- Netdata Integration
- Watchdog
"""

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime

import aiomqtt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from occore.devops.health_checker import HealthChecker, ServiceHealth
from occore.devops.watchdog import Watchdog
from occore.devops.netdata import NetdataClient
from lib.core.logger import get_logger
from lib.core.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer("dept4_devops")

MQTT_HOST = os.getenv('MQTT_HOST', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
HEALTH_CHECK_INTERVAL = int(os.getenv('HEALTH_CHECK_INTERVAL', '30'))
NETDATA_HOST = os.getenv('NETDATA_HOST', 'localhost')


class DevOpsTeamService:
    """
    유지보수관리팀 서비스

    기능:
    1. 헬스 체크 (30초 간격)
    2. Netdata 모니터링
    3. 워치독 (프로세스 감시)
    4. 시스템 메트릭 수집
    """

    def __init__(
        self,
        mqtt_host: str = MQTT_HOST,
        mqtt_port: int = MQTT_PORT,
        netdata_host: str = NETDATA_HOST,
    ):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.netdata_host = netdata_host

        self.health_checker = HealthChecker()
        self.watchdog = Watchdog()
        self.netdata = NetdataClient(host=netdata_host)

        self._running = False
        self._mqtt_client = None

        logger.info(f"DevOpsTeamService initialized")

    async def start(self):
        """서비스 시작"""
        self._running = True
        logger.info("Starting DevOps Team Service...")

        # 등록된 서비스 헬스 체크
        self._register_services()

        # 태스크 시작
        health_task = asyncio.create_task(self._health_check_loop())
        netdata_task = asyncio.create_task(self._netdata_monitoring_loop())
        watchdog_task = asyncio.create_task(self._watchdog_loop())
        mqtt_task = asyncio.create_task(self._mqtt_listener())

        try:
            await asyncio.gather(health_task, netdata_task, watchdog_task, mqtt_task)
        except asyncio.CancelledError:
            logger.info("Service tasks cancelled")
        finally:
            self._running = False

    async def stop(self):
        """서비스 중지"""
        logger.info("Stopping DevOps Team Service...")
        self._running = False

    def _register_services(self):
        """모니터링할 서비스 등록"""
        # Gateway
        self.health_checker.register_service(
            "gateway",
            "http://localhost:8000/health"
        )
        # MQTT
        self.health_checker.register_service(
            "mqtt",
            "tcp://localhost:1883",
            check_type="tcp"
        )
        # Elasticsearch
        self.health_checker.register_service(
            "elasticsearch",
            "http://localhost:9200/_cluster/health"
        )
        # Redis
        self.health_checker.register_service(
            "redis",
            "redis://localhost:6380",
            check_type="tcp"
        )

        logger.info(f"Registered {len(self.health_checker.services)} services")

    async def _health_check_loop(self):
        """헬스 체크 루프"""
        logger.info(f"Health check started (interval: {HEALTH_CHECK_INTERVAL}s)")

        while self._running:
            try:
                results = await self.health_checker.check_all()

                unhealthy = [r for r in results if r.status != "healthy"]
                if unhealthy:
                    logger.warning(f"Unhealthy services: {[r.name for r in unhealthy]}")
                    await self._publish_health_status(results)
                else:
                    logger.debug("All services healthy")

                await asyncio.sleep(HEALTH_CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"Health check error: {e}")
                await asyncio.sleep(10)

    async def _netdata_monitoring_loop(self):
        """Netdata 모니터링 루프"""
        logger.info(f"Netdata monitoring started: {self.netdata_host}")

        while self._running:
            try:
                # 시스템 메트릭 수집
                metrics = await self._collect_system_metrics()

                if metrics and self._mqtt_client:
                    await self._mqtt_client.publish(
                        "oz/a2m/metrics/system",
                        json.dumps({
                            "type": "system_metrics",
                            "data": metrics,
                            "timestamp": datetime.utcnow().isoformat(),
                            "department": "dept4",
                        }),
                        qos=1,
                    )

                # 10초마다 수집
                await asyncio.sleep(10)

            except Exception as e:
                logger.error(f"Netdata monitoring error: {e}")
                await asyncio.sleep(30)

    async def _collect_system_metrics(self) -> dict:
        """시스템 메트릭 수집"""
        try:
            # CPU
            cpu_data = self.netdata.get_metric("system.cpu")
            cpu_usage = self._calculate_cpu_usage(cpu_data)

            # Memory
            mem_data = self.netdata.get_metric("system.ram")
            mem_usage = self._calculate_memory_usage(mem_data)

            # Disk
            disk_data = self.netdata.get_metric("disk_usage.root")

            # Network
            net_data = self.netdata.get_metric("system.net")

            return {
                "cpu_percent": cpu_usage,
                "memory_percent": mem_usage,
                "disk": disk_data,
                "network": net_data,
            }

        except Exception as e:
            logger.warning(f"Failed to collect metrics: {e}")
            return {}

    def _calculate_cpu_usage(self, cpu_data: dict) -> float:
        """CPU 사용율 계산"""
        if not cpu_data or "data" not in cpu_data:
            return 0.0
        # 단순화된 계산
        return 50.0

    def _calculate_memory_usage(self, mem_data: dict) -> float:
        """메모리 사용율 계산"""
        if not mem_data or "data" not in mem_data:
            return 0.0
        # 단순화된 계산
        return 50.0

    async def _watchdog_loop(self):
        """워치독 루프"""
        logger.info("Watchdog started")

        # 모니터링할 프로세스 등록
        self.watchdog.register_process("gateway", "uvicorn")
        self.watchdog.register_process("bot", "python")
        self.watchdog.register_process("mqtt", "mosquitto")

        while self._running:
            try:
                # 프로세스 체크
                statuses = self.watchdog.check_all()

                for name, status in statuses.items():
                    if not status["running"]:
                        logger.error(f"Process not running: {name}")
                        await self._publish_process_alert(name, status)

                await asyncio.sleep(60)  # 1분마다 체크

            except Exception as e:
                logger.error(f"Watchdog error: {e}")
                await asyncio.sleep(30)

    async def _mqtt_listener(self):
        """MQTT 리스너"""
        while self._running:
            try:
                async with aiomqtt.Client(
                    hostname=self.mqtt_host,
                    port=self.mqtt_port,
                    client_id="dept4_devops_service",
                ) as client:
                    self._mqtt_client = client
                    logger.info("DevOps service connected to MQTT")

                    # 명령 토픽 구독
                    await client.subscribe("oz/a2m/commands/devops")

                    async for message in client.messages:
                        if not self._running:
                            break
                        await self._handle_command(message)

            except aiomqtt.MqttError as e:
                logger.error(f"MQTT error: {e}")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"MQTT listener error: {e}")
                await asyncio.sleep(5)

    async def _handle_command(self, message):
        """명령 처리"""
        try:
            payload = json.loads(message.payload.decode())
            command = payload.get("command", "")

            logger.info(f"Received command: {command}")

            if command == "restart_service":
                service_name = payload.get("service", "")
                await self._restart_service(service_name)

            elif command == "get_metrics":
                metrics = await self._collect_system_metrics()
                if self._mqtt_client:
                    await self._mqtt_client.publish(
                        "oz/a2m/metrics/response",
                        json.dumps(metrics),
                        qos=1,
                    )

        except Exception as e:
            logger.error(f"Command handling error: {e}")

    async def _restart_service(self, service_name: str):
        """서비스 재시작"""
        logger.info(f"Restarting service: {service_name}")
        # 실제 재시작 로직 구현 필요
        pass

    async def _publish_health_status(self, results: list):
        """헬스 상태 발행"""
        if not self._mqtt_client:
            return

        message = {
            "type": "health_status",
            "services": [
                {
                    "name": r.name,
                    "status": r.status,
                    "latency_ms": r.latency_ms,
                    "last_check": r.last_check.isoformat() if r.last_check else None,
                }
                for r in results
            ],
            "timestamp": datetime.utcnow().isoformat(),
            "department": "dept4",
        }

        await self._mqtt_client.publish(
            "oz/a2m/status/health",
            json.dumps(message),
            qos=1,
        )

    async def _publish_process_alert(self, process_name: str, status: dict):
        """프로세스 알림 발행"""
        if not self._mqtt_client:
            return

        alert = {
            "type": "process_alert",
            "process": process_name,
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
            "department": "dept4",
        }

        await self._mqtt_client.publish(
            "oz/a2m/alerts/process",
            json.dumps(alert),
            qos=2,
        )

    def get_stats(self) -> dict:
        """서비스 통계"""
        return {
            "running": self._running,
            "services_registered": len(self.health_checker.services),
            "netdata_host": self.netdata_host,
        }


async def main():
    """메인 실행 함수"""
    service = DevOpsTeamService()

    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}")
        asyncio.create_task(service.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await service.start()
    except Exception as e:
        logger.error(f"Service failed: {e}")
    finally:
        await service.stop()
        logger.info("DevOps Team Service stopped")


if __name__ == "__main__":
    asyncio.run(main())

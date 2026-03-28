#!/usr/bin/env python3
"""
Department 3: Security Team Service
정병보호처 (보안팀) - 독립 실행 서비스

occore/security 모듈을 부서 독립 서비스로 래핑
- ThreatMonitor
- AuditLogger
- ComplianceChecker
"""

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime

import aiomqtt

# 프로젝트 루트 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from occore.security.threat_monitor import ThreatMonitor, ThreatLevel
from occore.security.audit_logger import AuditLogger
from occore.security.compliance_checker import ComplianceChecker
from lib.core.logger import get_logger
from lib.core.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer("dept3_security")

# 설정
MQTT_HOST = os.getenv('MQTT_HOST', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
THREAT_CHECK_INTERVAL = int(os.getenv('THREAT_CHECK_INTERVAL', '60'))


class SecurityTeamService:
    """
    보안팀 서비스

    기능:
    1. 위협 모니터링 (실시간)
    2. 감사 로깅
    3. 컴플라이언스 체크
    4. MQTT를 통한 보안 이벤트 발행
    """

    def __init__(
        self,
        mqtt_host: str = MQTT_HOST,
        mqtt_port: int = MQTT_PORT,
    ):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port

        # 보안 모듈 초기화
        self.threat_monitor = ThreatMonitor()
        self.audit_logger = AuditLogger()
        self.compliance_checker = ComplianceChecker()

        self._running = False
        self._mqtt_client = None

        logger.info(f"SecurityTeamService initialized: {mqtt_host}:{mqtt_port}")

    async def start(self):
        """서비스 시작"""
        self._running = True
        logger.info("Starting Security Team Service...")

        # 위협 모니터링 태스크
        threat_task = asyncio.create_task(self._threat_monitoring_loop())
        # 컴플라이언스 체크 태스크
        compliance_task = asyncio.create_task(self._compliance_loop())
        # MQTT 이벤트 리스너
        mqtt_task = asyncio.create_task(self._mqtt_listener())

        try:
            await asyncio.gather(threat_task, compliance_task, mqtt_task)
        except asyncio.CancelledError:
            logger.info("Service tasks cancelled")
        finally:
            self._running = False

    async def stop(self):
        """서비스 중지"""
        logger.info("Stopping Security Team Service...")
        self._running = False

    async def _threat_monitoring_loop(self):
        """위협 모니터링 루프"""
        logger.info(f"Threat monitoring started (interval: {THREAT_CHECK_INTERVAL}s)")

        while self._running:
            try:
                # 위협 검사
                threats = await self._check_threats()

                if threats:
                    for threat in threats:
                        logger.warning(f"Threat detected: {threat}")
                        await self._publish_threat_alert(threat)

                await asyncio.sleep(THREAT_CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"Threat monitoring error: {e}")
                await asyncio.sleep(10)

    async def _check_threats(self) -> list:
        """위협 검사 실행"""
        threats = []

        # 시스템 리소스 확인
        import psutil

        # CPU 사용율
        cpu_percent = psutil.cpu_percent(interval=1)
        if cpu_percent > 90:
            threats.append({
                "type": "high_cpu_usage",
                "level": ThreatLevel.HIGH.value,
                "value": cpu_percent,
                "message": f"CPU 사용율 높음: {cpu_percent}%",
            })

        # 메모리 사용율
        memory = psutil.virtual_memory()
        if memory.percent > 90:
            threats.append({
                "type": "high_memory_usage",
                "level": ThreatLevel.HIGH.value,
                "value": memory.percent,
                "message": f"메모리 사용율 높음: {memory.percent}%",
            })

        # 디스크 사용율
        disk = psutil.disk_usage('/')
        if disk.percent > 90:
            threats.append({
                "type": "high_disk_usage",
                "level": ThreatLevel.MEDIUM.value,
                "value": disk.percent,
                "message": f"디스크 사용율 높음: {disk.percent}%",
            })

        return threats

    async def _compliance_loop(self):
        """컴플라이언스 체크 루프"""
        logger.info("Compliance checking started")

        while self._running:
            try:
                # 5분마다 컴플라이언스 체크
                await asyncio.sleep(300)

                if not self._running:
                    break

                # 컴플라이언스 검사
                issues = self.compliance_checker.check_all()

                if issues:
                    logger.warning(f"Compliance issues found: {len(issues)}")
                    await self._publish_compliance_issues(issues)
                else:
                    logger.info("Compliance check passed")

            except Exception as e:
                logger.error(f"Compliance check error: {e}")

    async def _mqtt_listener(self):
        """MQTT 이벤트 리스너"""
        while self._running:
            try:
                async with aiomqtt.Client(
                    hostname=self.mqtt_host,
                    port=self.mqtt_port,
                    client_id="dept3_security_service",
                ) as client:
                    self._mqtt_client = client
                    logger.info("Security service connected to MQTT")

                    # 보안 관련 토픽 구독
                    await client.subscribe("oz/a2m/security/audit")
                    await client.subscribe("oz/a2m/security/investigate")

                    async for message in client.messages:
                        if not self._running:
                            break
                        await self._handle_security_message(message)

            except aiomqtt.MqttError as e:
                logger.error(f"MQTT error: {e}")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"MQTT listener error: {e}")
                await asyncio.sleep(5)

    async def _handle_security_message(self, message):
        """보안 메시지 처리"""
        try:
            payload = json.loads(message.payload.decode())
            topic = message.topic.value

            if "audit" in topic:
                # 감사 로그 기록
                await self._log_audit_event(payload)
            elif "investigate" in topic:
                # 조사 이벤트 처리
                await self._handle_investigation(payload)

        except Exception as e:
            logger.error(f"Security message handling error: {e}")

    async def _log_audit_event(self, payload: dict):
        """감사 이벤트 로깅"""
        try:
            self.audit_logger.log(
                event_type=payload.get("event_type", "unknown"),
                user=payload.get("user", "system"),
                action=payload.get("action", ""),
                resource=payload.get("resource", ""),
                status=payload.get("status", "success"),
                details=payload.get("details", {}),
            )
            logger.debug(f"Audit event logged: {payload.get('event_type')}")
        except Exception as e:
            logger.error(f"Audit logging error: {e}")

    async def _handle_investigation(self, payload: dict):
        """조사 이벤트 처리"""
        logger.info(f"Investigation requested: {payload}")
        # 조사 로직 구현
        pass

    async def _publish_threat_alert(self, threat: dict):
        """위협 알림 발행"""
        if not self._mqtt_client:
            return

        alert = {
            "type": "threat_alert",
            "threat": threat,
            "timestamp": datetime.utcnow().isoformat(),
            "department": "dept3",
        }

        await self._mqtt_client.publish(
            "oz/a2m/alerts/security",
            json.dumps(alert),
            qos=2,
        )

    async def _publish_compliance_issues(self, issues: list):
        """컴플라이언스 이슈 발행"""
        if not self._mqtt_client:
            return

        message = {
            "type": "compliance_issues",
            "issues": issues,
            "timestamp": datetime.utcnow().isoformat(),
            "department": "dept3",
        }

        await self._mqtt_client.publish(
            "oz/a2m/alerts/compliance",
            json.dumps(message),
            qos=1,
        )

    def get_stats(self) -> dict:
        """서비스 통계"""
        return {
            "running": self._running,
            "mqtt_host": self.mqtt_host,
            "audit_logger_stats": self.audit_logger.get_stats(),
            "compliance_checker_stats": self.compliance_checker.get_stats(),
        }


async def main():
    """메인 실행 함수"""
    service = SecurityTeamService()

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
        logger.info("Security Team Service stopped")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Department 5: Performance Analysis Team Service
성과분석팀 - 독립 실행 서비스

occore/pnl 모듈을 부서 독립 서비스로 래핑
- 일일 PnL 계산
- 리포트 생성 스케줄러
- 성과 메트릭 분석
"""

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timedelta
from typing import Dict, Any, List

import aiomqtt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from occore.pnl.calculator import PnLCalculator
from occore.pnl.performance_metrics import PerformanceAnalyzer
from occore.pnl.risk_metrics import RiskMetricsCalculator
from lib.core.logger import get_logger
from lib.core.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer("dept5_pnl")

MQTT_HOST = os.getenv('MQTT_HOST', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
REPORT_SCHEDULE_HOUR = int(os.getenv('REPORT_SCHEDULE_HOUR', '0'))  # 자정


class PerformanceTeamService:
    """
    성과분석팀 서비스

    기능:
    1. 실시간 PnL 계산
    2. 일일 리포트 생성 (00:00)
    3. 위험 메트릭스 계산
    4. 성과 분석 및 알림
    """

    def __init__(
        self,
        mqtt_host: str = MQTT_HOST,
        mqtt_port: int = MQTT_PORT,
    ):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port

        self.pnl_calculator = PnLCalculator()
        self.performance_analyzer = PerformanceAnalyzer()
        self.risk_calculator = RiskMetricsCalculator()

        self._running = False
        self._mqtt_client = None
        self._daily_pnl: Dict[str, float] = {}
        self._trades: List[Dict[str, Any]] = []

        logger.info(f"PerformanceTeamService initialized")

    async def start(self):
        """서비스 시작"""
        self._running = True
        logger.info("Starting Performance Team Service...")

        pnl_task = asyncio.create_task(self._pnl_tracking_loop())
        report_task = asyncio.create_task(self._daily_report_scheduler())
        mqtt_task = asyncio.create_task(self._mqtt_listener())

        try:
            await asyncio.gather(pnl_task, report_task, mqtt_task)
        except asyncio.CancelledError:
            logger.info("Service tasks cancelled")
        finally:
            self._running = False

    async def stop(self):
        """서비스 중지"""
        logger.info("Stopping Performance Team Service...")
        self._running = False

    async def _pnl_tracking_loop(self):
        """PnL 추적 루프"""
        logger.info("PnL tracking started")

        while self._running:
            try:
                # 5분마다 PnL 계산
                await self._calculate_current_pnl()
                await asyncio.sleep(300)

            except Exception as e:
                logger.error(f"PnL tracking error: {e}")
                await asyncio.sleep(60)

    async def _calculate_current_pnl(self):
        """현재 PnL 계산"""
        try:
            # 거래 데이터 기반 PnL 계산
            pnl_data = self.pnl_calculator.calculate_daily_pnl(
                date=datetime.utcnow().date()
            )

            self._daily_pnl = pnl_data

            # MQTT 발행
            if self._mqtt_client:
                await self._mqtt_client.publish(
                    "oz/a2m/pnl/current",
                    json.dumps({
                        "type": "pnl_update",
                        "data": pnl_data,
                        "timestamp": datetime.utcnow().isoformat(),
                        "department": "dept5",
                    }),
                    qos=1,
                )

        except Exception as e:
            logger.error(f"PnL calculation error: {e}")

    async def _daily_report_scheduler(self):
        """일일 리포트 스케줄러"""
        logger.info(f"Daily report scheduler started (hour: {REPORT_SCHEDULE_HOUR})")

        while self._running:
            try:
                now = datetime.utcnow()
                next_run = now.replace(hour=REPORT_SCHEDULE_HOUR, minute=0, second=0, microsecond=0)

                if next_run <= now:
                    next_run += timedelta(days=1)

                wait_seconds = (next_run - now).total_seconds()
                logger.info(f"Next report in {wait_seconds/3600:.1f} hours")

                await asyncio.sleep(wait_seconds)

                if not self._running:
                    break

                # 리포트 생성
                await self._generate_daily_report()

            except Exception as e:
                logger.error(f"Report scheduler error: {e}")
                await asyncio.sleep(3600)

    async def _generate_daily_report(self):
        """일일 리포트 생성"""
        logger.info("Generating daily report...")

        try:
            yesterday = datetime.utcnow().date() - timedelta(days=1)

            # 성과 분석
            performance = self.performance_analyzer.analyze_period(
                start_date=yesterday,
                end_date=yesterday,
            )

            # 위험 메트릭스
            risk_metrics = self.risk_calculator.calculate_metrics(
                trades=self._trades,
            )

            # 리포트 생성
            report = {
                "type": "daily_report",
                "date": yesterday.isoformat(),
                "performance": performance,
                "risk": risk_metrics,
                "pnl": self._daily_pnl,
                "timestamp": datetime.utcnow().isoformat(),
                "department": "dept5",
            }

            # 발행
            if self._mqtt_client:
                await self._mqtt_client.publish(
                    "oz/a2m/reports/daily",
                    json.dumps(report),
                    qos=2,
                )

            logger.info(f"Daily report generated: {yesterday}")

            # 거래 기록 초기화
            self._trades = []

        except Exception as e:
            logger.error(f"Report generation error: {e}")

    async def _mqtt_listener(self):
        """MQTT 리스너"""
        while self._running:
            try:
                async with aiomqtt.Client(
                    hostname=self.mqtt_host,
                    port=self.mqtt_port,
                    client_id="dept5_performance_service",
                ) as client:
                    self._mqtt_client = client
                    logger.info("Performance service connected to MQTT")

                    # 거래 데이터 구독
                    await client.subscribe("oz/a2m/trades/executed")

                    async for message in client.messages:
                        if not self._running:
                            break
                        await self._handle_trade_message(message)

            except aiomqtt.MqttError as e:
                logger.error(f"MQTT error: {e}")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"MQTT listener error: {e}")
                await asyncio.sleep(5)

    async def _handle_trade_message(self, message):
        """거래 메시지 처리"""
        try:
            payload = json.loads(message.payload.decode())

            # 거래 기록
            trade = {
                "trade_id": payload.get("trade_id"),
                "symbol": payload.get("symbol"),
                "side": payload.get("side"),
                "quantity": payload.get("quantity"),
                "price": payload.get("price"),
                "pnl": payload.get("pnl", 0),
                "timestamp": payload.get("timestamp"),
            }

            self._trades.append(trade)
            logger.debug(f"Trade recorded: {trade['trade_id']}")

        except Exception as e:
            logger.error(f"Trade message handling error: {e}")

    def get_stats(self) -> dict:
        """서비스 통계"""
        return {
            "running": self._running,
            "daily_pnl": self._daily_pnl,
            "trades_count": len(self._trades),
            "next_report_hour": REPORT_SCHEDULE_HOUR,
        }


async def main():
    """메인 실행 함수"""
    service = PerformanceTeamService()

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
        logger.info("Performance Team Service stopped")


if __name__ == "__main__":
    asyncio.run(main())

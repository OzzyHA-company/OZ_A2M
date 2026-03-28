#!/usr/bin/env python3
"""
Department 6: R&D Team Service
연구개발팀 - 독립 실행 서비스

occore/rnd + strategy_db 연동
- 일일 분석 루프
- 전략 평가
- 성과 DB 저장
- 개선 신호 생성
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

from occore.rnd.strategy_db import StrategyDB
from occore.rnd.strategy_evaluator import StrategyEvaluator
from occore.rnd.strategy_generator import StrategyGenerator
from occore.rnd.backtest_engine import BacktestEngine
from lib.core.logger import get_logger
from lib.core.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer("dept6_rnd")

MQTT_HOST = os.getenv('MQTT_HOST', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
ANALYSIS_SCHEDULE_HOUR = int(os.getenv('ANALYSIS_SCHEDULE_HOUR', '1'))  # 새벽 1시


class RDTeamService:
    """
    연구개발팀 서비스

    기능:
    1. 일일 전략 분석 (01:00)
    2. 백테스트 실행
    3. 전략 성과 DB 저장
    4. 개선 신호 생성
    """

    def __init__(
        self,
        mqtt_host: str = MQTT_HOST,
        mqtt_port: int = MQTT_PORT,
        db_path: str = "data/strategy_performance.db",
    ):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port

        self.strategy_db = StrategyDB(db_path=db_path)
        self.evaluator = StrategyEvaluator()
        self.generator = StrategyGenerator()
        self.backtest = BacktestEngine()

        self._running = False
        self._mqtt_client = None

        logger.info(f"RDTeamService initialized")

    async def start(self):
        """서비스 시작"""
        self._running = True
        logger.info("Starting R&D Team Service...")

        analysis_task = asyncio.create_task(self._daily_analysis_scheduler())
        mqtt_task = asyncio.create_task(self._mqtt_listener())

        try:
            await asyncio.gather(analysis_task, mqtt_task)
        except asyncio.CancelledError:
            logger.info("Service tasks cancelled")
        finally:
            self._running = False

    async def stop(self):
        """서비스 중지"""
        logger.info("Stopping R&D Team Service...")
        self._running = False

    async def _daily_analysis_scheduler(self):
        """일일 분석 스케줄러"""
        logger.info(f"Daily analysis scheduler started (hour: {ANALYSIS_SCHEDULE_HOUR})")

        while self._running:
            try:
                now = datetime.utcnow()
                next_run = now.replace(
                    hour=ANALYSIS_SCHEDULE_HOUR,
                    minute=0,
                    second=0,
                    microsecond=0
                )

                if next_run <= now:
                    next_run += timedelta(days=1)

                wait_seconds = (next_run - now).total_seconds()
                logger.info(f"Next analysis in {wait_seconds/3600:.1f} hours")

                await asyncio.sleep(wait_seconds)

                if not self._running:
                    break

                # 분석 실행
                await self._run_daily_analysis()

            except Exception as e:
                logger.error(f"Analysis scheduler error: {e}")
                await asyncio.sleep(3600)

    async def _run_daily_analysis(self):
        """일일 분석 실행"""
        logger.info("Running daily strategy analysis...")

        try:
            yesterday = datetime.utcnow().date() - timedelta(days=1)

            # 1. 전략 평가
            evaluations = await self._evaluate_strategies(yesterday)

            # 2. 성과 DB 저장
            await self._save_performances(evaluations)

            # 3. 개선 신호 생성
            signals = await self._generate_improvement_signals(evaluations)

            # 4. 결과 발행
            await self._publish_analysis_results(evaluations, signals)

            logger.info(f"Daily analysis completed: {len(evaluations)} strategies evaluated")

        except Exception as e:
            logger.error(f"Daily analysis error: {e}")

    async def _evaluate_strategies(self, date) -> List[Dict[str, Any]]:
        """전략 평가"""
        evaluations = []

        # 활성 전략 목록 가져오기
        strategies = self.strategy_db.get_active_strategies()

        for strategy in strategies:
            try:
                # 백테스트 실행
                backtest_result = self.backtest.run(
                    strategy_code=strategy["code"],
                    start_date=date - timedelta(days=30),
                    end_date=date,
                )

                # 성과 계산
                performance = self.evaluator.evaluate(backtest_result)

                evaluation = {
                    "strategy_id": strategy["id"],
                    "strategy_name": strategy["name"],
                    "date": date.isoformat(),
                    "pnl": performance.get("total_pnl", 0),
                    "sharpe_ratio": performance.get("sharpe_ratio", 0),
                    "max_drawdown": performance.get("max_drawdown", 0),
                    "win_rate": performance.get("win_rate", 0),
                    "trades_count": performance.get("trades_count", 0),
                }

                evaluations.append(evaluation)

            except Exception as e:
                logger.error(f"Strategy evaluation error for {strategy.get('id')}: {e}")

        return evaluations

    async def _save_performances(self, evaluations: List[Dict[str, Any]]):
        """성과 저장"""
        for eval_data in evaluations:
            try:
                self.strategy_db.save_performance(
                    strategy_id=eval_data["strategy_id"],
                    date=datetime.fromisoformat(eval_data["date"]).date(),
                    pnl=eval_data["pnl"],
                    sharpe_ratio=eval_data["sharpe_ratio"],
                    max_drawdown=eval_data["max_drawdown"],
                    win_rate=eval_data["win_rate"],
                    trades_count=eval_data["trades_count"],
                )
                logger.debug(f"Performance saved: {eval_data['strategy_id']}")

            except Exception as e:
                logger.error(f"Performance save error: {e}")

    async def _generate_improvement_signals(
        self,
        evaluations: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """개선 신호 생성"""
        signals = []

        for eval_data in evaluations:
            # 성과 기준 판단
            if eval_data["sharpe_ratio"] < 0.5:
                signals.append({
                    "type": "deprecate",
                    "strategy_id": eval_data["strategy_id"],
                    "reason": f"Low Sharpe ratio: {eval_data['sharpe_ratio']:.2f}",
                })
            elif eval_data["sharpe_ratio"] > 2.0:
                signals.append({
                    "type": "strengthen",
                    "strategy_id": eval_data["strategy_id"],
                    "reason": f"High Sharpe ratio: {eval_data['sharpe_ratio']:.2f}",
                })
            elif eval_data["max_drawdown"] > 0.2:
                signals.append({
                    "type": "investigate",
                    "strategy_id": eval_data["strategy_id"],
                    "reason": f"High drawdown: {eval_data['max_drawdown']:.2%}",
                })
            else:
                signals.append({
                    "type": "maintain",
                    "strategy_id": eval_data["strategy_id"],
                    "reason": "Stable performance",
                })

        return signals

    async def _publish_analysis_results(
        self,
        evaluations: List[Dict[str, Any]],
        signals: List[Dict[str, Any]],
    ):
        """분석 결과 발행"""
        if not self._mqtt_client:
            return

        message = {
            "type": "strategy_analysis",
            "date": (datetime.utcnow().date() - timedelta(days=1)).isoformat(),
            "evaluations": evaluations,
            "signals": signals,
            "timestamp": datetime.utcnow().isoformat(),
            "department": "dept6",
        }

        await self._mqtt_client.publish(
            "oz/a2m/rnd/analysis",
            json.dumps(message),
            qos=2,
        )

        # 개선 신호 개별 발행
        for signal in signals:
            if signal["type"] in ["deprecate", "investigate"]:
                await self._mqtt_client.publish(
                    "oz/a2m/alerts/strategy",
                    json.dumps({
                        "type": "strategy_alert",
                        "signal": signal,
                        "timestamp": datetime.utcnow().isoformat(),
                    }),
                    qos=2,
                )

    async def _mqtt_listener(self):
        """MQTT 리스너"""
        while self._running:
            try:
                async with aiomqtt.Client(
                    hostname=self.mqtt_host,
                    port=self.mqtt_port,
                    client_id="dept6_rd_service",
                ) as client:
                    self._mqtt_client = client
                    logger.info("R&D service connected to MQTT")

                    # 명령 구독
                    await client.subscribe("oz/a2m/commands/rnd")

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

            if command == "run_analysis":
                await self._run_daily_analysis()
            elif command == "generate_strategy":
                await self._generate_new_strategy(payload)

        except Exception as e:
            logger.error(f"Command handling error: {e}")

    async def _generate_new_strategy(self, payload: Dict[str, Any]):
        """새 전략 생성"""
        try:
            strategy = self.generator.generate(
                prompt=payload.get("prompt", "trend following strategy")
            )

            if self._mqtt_client:
                await self._mqtt_client.publish(
                    "oz/a2m/rnd/strategy_generated",
                    json.dumps({
                        "type": "new_strategy",
                        "strategy": strategy,
                        "timestamp": datetime.utcnow().isoformat(),
                    }),
                    qos=1,
                )

            logger.info(f"New strategy generated: {strategy.get('id')}")

        except Exception as e:
            logger.error(f"Strategy generation error: {e}")

    def get_stats(self) -> dict:
        """서비스 통계"""
        return {
            "running": self._running,
            "next_analysis_hour": ANALYSIS_SCHEDULE_HOUR,
        }


async def main():
    """메인 실행 함수"""
    service = RDTeamService()

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
        logger.info("R&D Team Service stopped")


if __name__ == "__main__":
    asyncio.run(main())

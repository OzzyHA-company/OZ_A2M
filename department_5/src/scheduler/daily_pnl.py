"""
OZ_A2M 제5부서: 성과분석팀 - 일일 PnL 스케줄러

매일 장 마감 후 자동으로 PnL 집계 및 리포트 생성
- strategy_db 저장
- D6 R&D 피드백 루프 연결
- Telegram 알림 발송
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from decimal import Decimal

from occore.pnl import (
    ProfitCalculator,
    PerformanceAnalyzer,
    ReportGenerator,
    get_calculator,
    get_analyzer,
    get_report_generator,
)
from lib.core import get_logger
from lib.messaging import get_mqtt_client
from lib.db.strategy import get_strategy_db

logger = get_logger(__name__)


class DailyPnLScheduler:
    """일일 PnL 집계 스케줄러"""

    def __init__(
        self,
        market_close_time: str = "16:00",  # EST
        timezone: str = "America/New_York",
        enable_telegram: bool = True,
        enable_rnd_feedback: bool = True
    ):
        self.market_close_time = market_close_time
        self.timezone = timezone
        self.enable_telegram = enable_telegram
        self.enable_rnd_feedback = enable_rnd_feedback

        self.calculator = get_calculator()
        self.analyzer = get_analyzer()
        self.reporter = get_report_generator()
        self.mqtt = get_mqtt_client()
        self.strategy_db = get_strategy_db()

        self._running = False
        self._scheduler_task: Optional[asyncio.Task] = None

    async def start(self):
        """스케줄러 시작"""
        self._running = True

        # MQTT 연결
        await self.mqtt.connect()

        # 스케줄러 태스크 시작
        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(),
            name="daily_pnl_scheduler"
        )

        logger.info(f"Daily PnL scheduler started (market close: {self.market_close_time})")

    async def stop(self):
        """스케줄러 중지"""
        self._running = False

        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass

        await self.mqtt.disconnect()
        logger.info("Daily PnL scheduler stopped")

    async def _scheduler_loop(self):
        """스케줄링 루프"""
        while self._running:
            try:
                now = datetime.now()

                # 다음 장 마감 시간 계산
                next_close = self._get_next_market_close(now)
                wait_seconds = (next_close - now).total_seconds()

                logger.info(f"Next market close: {next_close}, waiting {wait_seconds/3600:.1f} hours")

                # 대기
                await asyncio.sleep(wait_seconds)

                # 장 마감 후 PnL 집계 실행
                if self._running:
                    await self._run_daily_aggregation()

                # 다음 날까지 대기
                await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                await asyncio.sleep(60)

    def _get_next_market_close(self, now: datetime) -> datetime:
        """다음 장 마감 시간 계산"""
        hour, minute = map(int, self.market_close_time.split(":"))

        # 오늘 장 마감 시간
        close_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # 이미 지났으면 다음 날
        if close_time <= now:
            close_time += timedelta(days=1)

        # 주말 스킵 (간단한 구현)
        while close_time.weekday() >= 5:  # 5=토요일, 6=일요일
            close_time += timedelta(days=1)

        return close_time

    async def _run_daily_aggregation(self):
        """일일 집계 실행"""
        logger.info("Running daily PnL aggregation...")

        try:
            # 어제 날짜 기준
            yesterday = datetime.now() - timedelta(days=1)

            # 1. PnL 계산
            pnl_summary = self.calculator.calculate_daily_pnl(yesterday)

            # 2. 성과 지표 분석
            metrics = self.analyzer.analyze_period(
                start_date=yesterday.replace(hour=0, minute=0, second=0),
                end_date=yesterday.replace(hour=23, minute=59, second=59)
            )

            # 3. strategy_db 저장
            await self._save_to_strategy_db(pnl_summary, metrics, yesterday)

            # 4. 리포트 생성
            report = self.reporter.generate_daily_report(
                date=yesterday,
                pnl_summary=pnl_summary,
                metrics=metrics
            )

            # 5. Telegram 알림
            if self.enable_telegram:
                await self._send_telegram_notification(pnl_summary, metrics)

            # 6. D6 R&D 피드백
            if self.enable_rnd_feedback:
                await self._send_rnd_feedback(pnl_summary, metrics)

            # 7. MQTT 브로드캐스트
            await self._broadcast_daily_result(pnl_summary, metrics)

            logger.info(
                f"Daily aggregation completed: "
                f"PnL=${pnl_summary.total_pnl}, "
                f"Trades={pnl_summary.total_trades}, "
                f"WinRate={pnl_summary.win_rate*100:.1f}%"
            )

        except Exception as e:
            logger.error(f"Daily aggregation failed: {e}")
            await self._notify_error(str(e))

    async def _save_to_strategy_db(
        self,
        pnl_summary,
        metrics,
        date: datetime
    ):
        """strategy_db에 저장"""
        try:
            record = {
                "date": date.strftime("%Y-%m-%d"),
                "total_pnl": float(pnl_summary.total_pnl),
                "realized_pnl": float(pnl_summary.realized_pnl),
                "total_trades": pnl_summary.total_trades,
                "winning_trades": pnl_summary.winning_trades,
                "losing_trades": pnl_summary.losing_trades,
                "win_rate": pnl_summary.win_rate,
                "total_fees": float(pnl_summary.total_fees),
                "sharpe_ratio": getattr(metrics, 'sharpe_ratio', 0),
                "max_drawdown": float(getattr(metrics, 'max_drawdown', 0)),
                "symbol_pnl": {k: float(v) for k, v in pnl_summary.symbol_pnl.items()},
                "created_at": datetime.utcnow().isoformat()
            }

            # DB 저장
            await self.strategy_db.insert_daily_pnl(record)
            logger.info(f"PnL saved to strategy_db: {date.strftime('%Y-%m-%d')}")

        except Exception as e:
            logger.error(f"Failed to save to strategy_db: {e}")

    async def _send_telegram_notification(self, pnl_summary, metrics):
        """Telegram 알림 발송"""
        try:
            from department_6.src.notifications import get_telegram_notifier

            notifier = get_telegram_notifier()
            await notifier.send_pnl_report(
                daily_pnl=pnl_summary.total_pnl,
                total_pnl=Decimal("0"),  # TODO: 누적 PnL 조회
                win_rate=pnl_summary.win_rate,
                open_positions=0  # TODO: 미체결 포지션 조회
            )

        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")

    async def _send_rnd_feedback(self, pnl_summary, metrics):
        """D6 R&D 피드백 전송"""
        try:
            feedback = {
                "type": "daily_performance",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "data": {
                    "pnl": float(pnl_summary.total_pnl),
                    "win_rate": pnl_summary.win_rate,
                    "total_trades": pnl_summary.total_trades,
                    "sharpe_ratio": getattr(metrics, 'sharpe_ratio', 0),
                    "max_drawdown": float(getattr(metrics, 'max_drawdown', 0)),
                },
                "insights": self._generate_insights(pnl_summary, metrics),
                "timestamp": datetime.utcnow().isoformat()
            }

            await self.mqtt.publish("oz_a2m/feedback/rnd", feedback)
            logger.info("R&D feedback sent")

        except Exception as e:
            logger.error(f"Failed to send R&D feedback: {e}")

    def _generate_insights(self, pnl_summary, metrics) -> Dict[str, Any]:
        """성과 인사이트 생성"""
        insights = []

        # 승률 분석
        if pnl_summary.win_rate < 0.4:
            insights.append("Win rate below 40%. Review entry criteria.")
        elif pnl_summary.win_rate > 0.7:
            insights.append("Excellent win rate. Consider increasing position size.")

        # 손익 비율
        if pnl_summary.total_pnl < 0:
            insights.append("Negative PnL. Risk management review needed.")

        # 샤프 비율
        sharpe = getattr(metrics, 'sharpe_ratio', 0)
        if sharpe < 1:
            insights.append("Low Sharpe ratio. Risk-adjusted returns need improvement.")

        return {
            "summary": insights,
            "top_performers": sorted(
                pnl_summary.symbol_pnl.items(),
                key=lambda x: x[1],
                reverse=True
            )[:3],
            "worst_performers": sorted(
                pnl_summary.symbol_pnl.items(),
                key=lambda x: x[1]
            )[:3]
        }

    async def _broadcast_daily_result(self, pnl_summary, metrics):
        """MQTT로 일일 결과 브로드캐스트"""
        try:
            message = {
                "type": "daily_pnl",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "summary": {
                    "total_pnl": float(pnl_summary.total_pnl),
                    "win_rate": pnl_summary.win_rate,
                    "total_trades": pnl_summary.total_trades,
                },
                "timestamp": datetime.utcnow().isoformat()
            }

            await self.mqtt.publish("oz_a2m/pnl/daily", message)

        except Exception as e:
            logger.error(f"Failed to broadcast daily result: {e}")

    async def _notify_error(self, error_message: str):
        """에러 알림"""
        logger.error(f"Daily aggregation error: {error_message}")

        try:
            from department_6.src.notifications import get_telegram_notifier
            notifier = get_telegram_notifier()
            await notifier.send_system_alert(
                level="error",
                message=f"Daily PnL aggregation failed: {error_message}"
            )
        except Exception:
            pass

    async def trigger_manual_aggregation(self, date: Optional[datetime] = None):
        """수동 집계 트리거"""
        logger.info("Manual aggregation triggered")
        await self._run_daily_aggregation()


async def main():
    """메인 실행"""
    logging.basicConfig(level=logging.INFO)

    scheduler = DailyPnLScheduler()
    await scheduler.start()

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())

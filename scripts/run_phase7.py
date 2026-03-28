#!/usr/bin/env python3
"""
Phase 7 통합 실행 스크립트
LLM Gateway + Signal Generator + Scalping Bot
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "department_1" / "src"))
sys.path.insert(0, str(project_root / "department_7" / "src"))
sys.path.insert(0, str(project_root / "lib"))

import signal
from typing import List

from lib.core.logger import get_logger, setup_logging

logger = get_logger(__name__)

# 전역 상태
running = True
tasks: List[asyncio.Task] = []


def signal_handler(sig, frame):
    """시그널 핸들러"""
    global running
    logger.info("Shutdown signal received...")
    running = False


async def run_llm_gateway():
    """LLM Gateway 실행"""
    try:
        from gateway.api_server import app
        import uvicorn

        logger.info("Starting LLM Gateway on port 8000...")
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=8000,
            log_level="info",
            access_log=False
        )
        server = uvicorn.Server(config)
        await server.serve()
    except Exception as e:
        logger.error(f"LLM Gateway error: {e}")


async def run_signal_generator():
    """Signal Generator 실행"""
    try:
        from signal_generator import SignalGenerator

        logger.info("Starting Signal Generator...")
        generator = SignalGenerator(
            symbol="BTC/USDT",
            mqtt_host="localhost",
            mqtt_port=1883
        )

        def on_signal(signal):
            print(f"\n🚨 SIGNAL: {signal.type.value.upper()} {signal.symbol} @ {signal.price:.2f}")
            print(f"   Confidence: {signal.confidence:.1%} | RSI: {signal.indicators.get('rsi', 0):.2f}")

        generator.on_signal = on_signal
        await generator.start()

    except Exception as e:
        logger.error(f"Signal Generator error: {e}")


async def run_scalping_bot():
    """Scalping Bot 실행"""
    try:
        from bot.scalper import ScalpingBot

        logger.info("Starting Scalping Bot...")
        bot = ScalpingBot(
            bot_id="scalper_1",
            symbol="BTC/USDT",
            sandbox=True,
            mqtt_host="localhost",
            mqtt_port=1883
        )

        def on_trade(trade):
            print(f"\n💰 TRADE: {trade.side.upper()} {trade.amount} @ {trade.price}")
            if trade.pnl:
                emoji = "🟢" if trade.pnl > 0 else "🔴"
                print(f"   PnL: {emoji} {trade.pnl:.4f} USDT")

        def on_position_change(pos):
            if pos:
                print(f"\n📊 POSITION: {pos.side.value.upper()} {pos.amount} @ {pos.entry_price:.2f}")
            else:
                print("\n📊 POSITION: Closed")

        bot.on_trade = on_trade
        bot.on_position_change = on_position_change

        await bot.run()

    except Exception as e:
        logger.error(f"Scalping Bot error: {e}")


async def health_reporter():
    """상태 리포터"""
    while running:
        await asyncio.sleep(60)
        logger.info("=== Phase 7 System Health ===")
        logger.info("Components: LLM Gateway, Signal Generator, Scalping Bot")
        logger.info("Status: Running")


async def main():
    """메인 함수"""
    global tasks

    setup_logging()
    logger.info("=" * 50)
    logger.info("OZ_A2M Phase 7 - Starting...")
    logger.info("=" * 50)

    # 시그널 핸들러 등록
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 태스크 생성
    tasks = [
        asyncio.create_task(run_llm_gateway(), name="llm_gateway"),
        asyncio.create_task(run_signal_generator(), name="signal_generator"),
        asyncio.create_task(run_scalping_bot(), name="scalping_bot"),
        asyncio.create_task(health_reporter(), name="health_reporter"),
    ]

    # 실행 및 모니터링
    try:
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED
        )

        # 완료된 태스크 확인
        for task in done:
            if task.exception():
                logger.error(f"Task {task.get_name()} failed: {task.exception()}")

        # 남은 태스크 취소
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except Exception as e:
        logger.error(f"Main loop error: {e}")

    finally:
        logger.info("Phase 7 shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nShutdown by user")
        sys.exit(0)

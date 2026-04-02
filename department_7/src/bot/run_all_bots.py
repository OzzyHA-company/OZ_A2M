#!/usr/bin/env python3
"""
OZ_A2M 전체 봇 실행기 - 완결판
11개 봇 순차 가동 + CEO 대시보드

실행 방법:
  python3 run_all_bots.py
"""

import asyncio
import sys
import signal
from pathlib import Path
from datetime import datetime

# 환경변수 로드 (API 키 등) - 기존 환경변수 덮어쓰기
from dotenv import load_dotenv
load_dotenv('/home/ozzy-claw/.ozzy-secrets/master.env', override=True)

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger, setup_logging
from lib.messaging.event_bus import get_event_bus
from lib.cache.redis_client import get_redis_cache

# 봇 임포트
from grid_bot import BinanceGridBot
from dca_bot import BinanceDCABot
from triangular_arb_bot import TriangularArbBot
from funding_rate_bot import FundingRateBot
from scalper import BybitScalpingBot
from hyperliquid_bot import HyperliquidMarketMakerBot
from polymarket_bot import PolymarketAIBot
from pump_sniper_bot import PumpSniperBot
from copy_trade_bot import GMGNCopyBot
from ibkr_forecast_bot import IBKRForecastTraderBot

logger = get_logger(__name__)

# 전역 봇 레지스트리
bots = {}
bot_tasks = []

# 봇 설정
BOT_CONFIGS = [
    # 봇-02: Binance DCA (Grid보다 먼저 실행 - USDT 선점 방지)
    {
        'id': 'dca_binance_001',
        'name': 'Binance DCA',
        'class': BinanceDCABot,
        'kwargs': {
            'bot_id': 'dca_binance_001',
            'symbol': 'SOL/USDT',
            'exchange_id': 'binance',
            'capital': 13.0,  # 2026-04-02 업데이트: $32.71 재분배
            'dca_drop_pct': 0.02,
            'take_profit_pct': 0.03,
            'sandbox': False,
            'telegram_alerts': True
        }
    },
    # 봇-01: Binance Grid (DCA 후 실행 - 남은 USDT로 sell 위주)
    {
        'id': 'grid_binance_001',
        'name': 'Binance Grid',
        'class': BinanceGridBot,
        'kwargs': {
            'bot_id': 'grid_binance_001',
            'symbol': 'SOL/USDT',
            'exchange_id': 'binance',
            'capital': 10.0,  # 2026-04-02 업데이트: $32.71 재분배
            'grid_count': 20,
            'grid_spacing_pct': 0.005,
            'sandbox': False,
            'telegram_alerts': True
        }
    },
    # 봇-03: Triangular Arbitrage
    {
        'id': 'triarb_binance_001',
        'name': 'Triangular Arb',
        'class': TriangularArbBot,
        'kwargs': {
            'bot_id': 'triarb_binance_001',
            'exchange_id': 'binance',
            'capital': 9.71,  # 2026-04-02 업데이트: $32.71 재분배 (13+10+9.71=32.71)
            'min_profit_pct': 0.001,
            'sandbox': False,
            'telegram_alerts': True
        }
    },
    # 봇-04: Funding Rate
    {
        'id': 'funding_binance_bybit_001',
        'name': 'Funding Rate',
        'class': FundingRateBot,
        'kwargs': {
            'bot_id': 'funding_binance_bybit_001',
            'capital': 5.00,  # 2026-04-02 업데이트: $23.32 재분배
            'min_funding_rate': 0.0001,
            'sandbox': False,
            'telegram_alerts': True
        }
    },
    # 봇-05: Bybit Grid
    {
        'id': 'grid_bybit_001',
        'name': 'Bybit Grid',
        'class': BinanceGridBot,
        'kwargs': {
            'bot_id': 'grid_bybit_001',
            'symbol': 'SOL/USDT',
            'exchange_id': 'bybit',
            'capital': 10.32,  # 2026-04-02 업데이트: $23.32 재분배 (5+10.32+8=23.32)
            'grid_count': 15,
            'grid_spacing_pct': 0.005,
            'sandbox': False,
            'telegram_alerts': True
        }
    },
    # 봇-06: Bybit Scalping
    {
        'id': 'scalper_bybit_001',
        'name': 'Bybit Scalping',
        'class': BybitScalpingBot,
        'kwargs': {
            'bot_id': 'scalper_bybit_001',
            'symbol': 'SOL/USDT',
            'exchange_id': 'bybit',
            'capital': 8.00,  # 2026-04-02 유지
            'sandbox': False,
            'telegram_alerts': True
        }
    },
    # 봇-07: Hyperliquid (도파민봇)
    {
        'id': 'hyperliquid_mm_001',
        'name': 'Hyperliquid MM',
        'class': HyperliquidMarketMakerBot,
        'kwargs': {
            'bot_id': 'hyperliquid_mm_001',
            'symbol': 'SOL-PERP',
            'capital': 4.43,  # 2026-04-02: Phantom A $4.44 SOL - $0.01 사용분
            'base_spread_bps': 10.0,
            'sandbox': False,
            'mock_mode': False,
            'telegram_alerts': True
        }
    },
    # 봇-08: IBKR Forecast (Mock)
    {
        'id': 'ibkr_forecast_001',
        'name': 'IBKR Forecast',
        'class': IBKRForecastTraderBot,
        'kwargs': {
            'bot_id': 'ibkr_forecast_001',
            'symbols': ['AAPL', 'MSFT'],
            'capital': 10.0,
            'mock_mode': True,
            'telegram_alerts': True
        }
    },
    # 봇-09: Polymarket AI
    {
        'id': 'polymarket_ai_001',
        'name': 'Polymarket AI',
        'class': PolymarketAIBot,
        'kwargs': {
            'bot_id': 'polymarket_ai_001',
            'capital': 19.84,  # MetaMask (Polygon) USDC 자본
            'min_edge': 0.05,
            'mock_mode': False,
            'telegram_alerts': True
        }
    },
    # 봇-10: Pump.fun Sniper (도파민봇)
    {
        'id': 'pump_sniper_001',
        'name': 'Pump.fun Sniper',
        'class': PumpSniperBot,
        'kwargs': {
            'bot_id': 'pump_sniper_001',
            'capital_sol': 0.1,
            'take_profit_low': 2.0,
            'take_profit_high': 5.0,
            'stop_loss': 0.5,
            'mock_mode': False,
            'telegram_alerts': True
        }
    },
    # 봇-11: GMGN Copy (도파민봇)
    {
        'id': 'gmgn_copy_001',
        'name': 'GMGN Copy',
        'class': GMGNCopyBot,
        'kwargs': {
            'bot_id': 'gmgn_copy_001',
            'capital_sol': 0.067,
            'copy_percentage': 0.1,
            'mock_mode': False,
            'telegram_alerts': True
        }
    },
]


async def start_bot(config: dict) -> bool:
    """개별 봇 시작"""
    bot_id = config['id']
    bot_name = config['name']

    try:
        logger.info(f"Starting {bot_name} ({bot_id})...")

        # 봇 인스턴스 생성
        bot = config['class'](**config['kwargs'])
        bots[bot_id] = bot

        # 봇 실행 (백그라운드 태스크로)
        task = asyncio.create_task(bot.run(), name=f"bot_{bot_id}")
        bot_tasks.append(task)

        # 시작 성공 알림
        logger.info(f"✅ {bot_name} started successfully")

        # 첫 시그널 대기 (최대 10초)
        await asyncio.sleep(2)

        return True

    except Exception as e:
        logger.error(f"❌ Failed to start {bot_name}: {e}")
        return False


async def update_bot_status_to_redis():
    """봇 상태를 Redis에 주기적 저장"""
    redis_cache = get_redis_cache()
    try:
        await redis_cache.connect()
        logger.info("Redis connected for bot status updates")
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        return

    while True:
        try:
            for bot_id, bot in bots.items():
                try:
                    if hasattr(bot, 'get_status'):
                        status = bot.get_status()
                        # 봇 타입 결정
                        bot_type = 'stable'
                        if bot_id in ['hyperliquid_mm_001', 'pump_sniper_001', 'gmgn_copy_001']:
                            bot_type = 'dopamine'

                        # 거래소 결정
                        exchange = 'Unknown'
                        if 'binance' in bot_id:
                            exchange = 'Binance'
                        elif 'bybit' in bot_id:
                            exchange = 'Bybit'
                        elif 'hyperliquid' in bot_id:
                            exchange = 'Hyperliquid'
                        elif 'polymarket' in bot_id:
                            exchange = 'Polymarket'
                        elif 'pump' in bot_id or 'gmgn' in bot_id:
                            exchange = 'Solana'
                        elif 'ibkr' in bot_id:
                            exchange = 'IBKR'

                        await redis_cache.set_bot_status(
                            bot_id=bot_id,
                            status=status.get('status', 'unknown'),
                            bot_type=bot_type,
                            capital=status.get('capital', status.get('capital_sol', 0)),
                            pnl=status.get('total_pnl', status.get('total_pnl_sol', 0)),
                            trades=status.get('total_trades', status.get('total_bets', 0)),
                            mock_mode=status.get('mock_mode', False),
                            exchange=exchange,
                            symbol=status.get('symbol', 'Multi'),
                            ttl_seconds=60
                        )
                except Exception as e:
                    logger.debug(f"Failed to update status for {bot_id}: {e}")

            await asyncio.sleep(5)  # 5초마다 업데이트
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Status update loop error: {e}")
            await asyncio.sleep(10)

    await redis_cache.disconnect()


async def stop_all_bots():
    """모든 봇 중지"""
    logger.info("🛑 Stopping all bots...")

    for bot_id, bot in bots.items():
        try:
            if hasattr(bot, 'stop'):
                await bot.stop()
                logger.info(f"Stopped {bot_id}")
        except Exception as e:
            logger.error(f"Error stopping {bot_id}: {e}")

    # 모든 태스크 취소
    for task in bot_tasks:
        if not task.done():
            task.cancel()

    logger.info("All bots stopped")


async def print_status():
    """전체 봇 상태 출력"""
    print("\n" + "="*60)
    print("📊 OZ_A2M 전체 봇 상태")
    print("="*60)

    total_capital = 0
    total_pnl = 0
    running_count = 0

    for bot_id, bot in bots.items():
        try:
            status = bot.get_status() if hasattr(bot, 'get_status') else {'status': 'unknown'}
            capital = getattr(bot, 'capital', 0)
            total_capital += capital
            total_pnl += status.get('total_pnl', 0)

            status_icon = "🟢" if status.get('status') in ['running', 'RUNNING'] else "🔴"
            running_count += 1 if status.get('status') in ['running', 'RUNNING'] else 0

            print(f"{status_icon} {bot_id}: {status.get('status', 'unknown')} | "
                  f"Capital: ${capital} | PnL: ${status.get('total_pnl', 0):.4f}")
        except Exception as e:
            print(f"⚠️ {bot_id}: Error getting status - {e}")

    print("-"*60)
    print(f"총 자본: ${total_capital:.2f}")
    print(f"총 수익: ${total_pnl:.4f}")
    print(f"가동 봇: {running_count}/{len(bots)}")
    print("="*60 + "\n")

    return running_count


async def run_all():
    """모든 봇 실행"""
    setup_logging()

    print("\n" + "="*60)
    print("🚀 OZ_A2M 전체 봇 실행기 - 완결판")
    print("="*60)
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"총 봇 수: {len(BOT_CONFIGS)}")
    print("="*60 + "\n")

    # 순차적으로 봇 시작
    success_count = 0
    for config in BOT_CONFIGS:
        success = await start_bot(config)
        if success:
            success_count += 1
        await asyncio.sleep(1)  # 봇 간 간격

    print(f"\n✅ {success_count}/{len(BOT_CONFIGS)}개 봇 시작 완료\n")

    # 상태 출력
    running = await print_status()

    # Redis 상태 업데이트 태스크 시작
    redis_task = asyncio.create_task(update_bot_status_to_redis())
    logger.info("Redis status update task started")

    # Dashboard URL
    print(f"\n🌐 CEO 대시보드: http://100.77.207.113:8080")
    print("\n💡 명령어:")
    print("  - Ctrl+C: 모든 봇 중지")
    print("  - 상태 확인: 대시보드 접속")
    print("")

    # 계속 실행 (인터럽트 대기)
    try:
        while True:
            await asyncio.sleep(30)
            await print_status()

    except asyncio.CancelledError:
        logger.info("Main loop cancelled")
    finally:
        await stop_all_bots()


def signal_handler(sig, frame):
    """시그널 핸들러"""
    print("\n\n🛑 종료 신호 수신. 모든 봇을 중지합니다...")
    asyncio.create_task(stop_all_bots())
    sys.exit(0)


if __name__ == "__main__":
    # 시그널 핸들러 등록
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 실행
    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        print("\n\n👋 사용자에 의해 종료됨")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

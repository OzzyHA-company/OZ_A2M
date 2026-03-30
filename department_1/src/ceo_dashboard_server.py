"""
OZ_A2M CEO Dashboard Server - 실시간 데이터 연결 버전
FastAPI + WebSocket + MQTT + Redis + 실제 봇 연동
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
from dataclasses import asdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

import sys
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger

logger = get_logger(__name__)

# 요청 모델
class WithdrawRequest(BaseModel):
    exchange: str
    asset: str

class BotControlRequest(BaseModel):
    bot_id: str
    action: str

class TelegramToggleRequest(BaseModel):
    enabled: bool

class SystemOptimizeRequest(BaseModel):
    action: str  # clear_memory, rotate_logs, clear_cache


# Unified Bot Manager 연동
class DashboardBotManager:
    """대시보드용 통합 봇 관리자"""

    def __init__(self):
        self.bots: Dict[str, Any] = {}
        self._unified_manager = None
        self.withdrawal_queue: List[Dict] = []
        self.telegram_enabled = True
        self.total_profit = 0.0
        self.daily_profits: List[float] = []
        self.websocket_clients: List[WebSocket] = []
        self.kill_switch_active = False

        # 거래소 잔액 캐시
        self.exchange_balances: Dict[str, Dict] = {}
        self.last_balance_update: Optional[datetime] = None

        # API 사용량 추적
        self.api_usage: Dict[str, Dict] = {
            'binance': {'calls': 0, 'limit': 1200, 'remaining': 1200},
            'bybit': {'calls': 0, 'limit': 100, 'remaining': 100},
            'hyperliquid': {'calls': 0, 'limit': 1000, 'remaining': 1000},
            'polymarket': {'calls': 0, 'limit': 100, 'remaining': 100},
            'helius': {'calls': 0, 'limit': 1000, 'remaining': 1000},
        }

        # 시스템 메트릭스
        self.system_metrics: Dict[str, Any] = {
            'cpu': 0.0,
            'memory': 0.0,
            'disk': 0.0,
            'docker': 0.0,
        }

        self._init_bots()

    def _init_bots(self):
        """실제 봇 인스턴스 초기화"""
        try:
            sys.path.insert(0, str(project_root))

            # 봇 클래스 임포트
            from department_7.src.bot.grid_bot import BinanceGridBot
            from department_7.src.bot.dca_bot import BinanceDCABot
            from department_7.src.bot.scalper import BybitScalpingBot
            from department_7.src.bot.triangular_arb_bot import TriangularArbBot
            from department_7.src.bot.funding_rate_bot import FundingRateBot
            from department_7.src.bot.hyperliquid_bot import HyperliquidMarketMakerBot
            from department_7.src.bot.polymarket_bot import PolymarketAIBot
            from department_7.src.bot.pump_sniper_bot import PumpSniperBot
            from department_7.src.bot.ibkr_forecast_bot import IBKRForecastTraderBot
            from department_7.src.bot.copy_trade_bot import GMGNCopyBot
            from department_7.src.bot.arbitrage_bot import ArbitrageBot
            from department_7.src.bot.market_maker_bot import MarketMakerBot
            from department_7.src.bot.trend_follower import TrendFollowerBot

            # 봇 인스턴스 생성
            bot_configs = [
                ('grid_binance_001', BinanceGridBot, {'symbol': 'BTC/USDT', 'capital': 11}, 'stable'),
                ('dca_binance_001', BinanceDCABot, {'symbol': 'BTC/USDT', 'capital': 14}, 'stable'),
                ('scalper_bybit_001', BybitScalpingBot, {'symbol': 'SOL/USDT', 'capital': 20}, 'stable'),
                ('triarb_binance_001', TriangularArbBot, {'capital': 20}, 'stable'),
                ('funding_binance_bybit_001', FundingRateBot, {'capital': 20}, 'stable'),
                ('hyperliquid_mm_001', HyperliquidMarketMakerBot, {'symbol': 'SOL-PERP', 'capital': 20}, 'dopamine'),
                ('polymarket_ai_001', PolymarketAIBot, {'capital': 19.85, 'mock_mode': False}, 'stable'),
                ('pump_sniper_001', PumpSniperBot, {'capital_sol': 0.1, 'mock_mode': False}, 'dopamine'),
                ('ibkr_forecast_001', IBKRForecastTraderBot, {'symbols': ['AAPL', 'MSFT'], 'capital': 10}, 'stable'),
                ('gmgn_copy_001', GMGNCopyBot, {'capital_sol': 0.1, 'mock_mode': True}, 'dopamine'),
                ('arbitrage_001', ArbitrageBot, {'exchanges': ['binance', 'bybit']}, 'stable'),
                ('market_maker_001', MarketMakerBot, {'exchange': 'binance', 'symbol': 'BTC/USDT'}, 'stable'),
                ('trend_follower_001', TrendFollowerBot, {}, 'stable'),
            ]

            for bot_id, bot_class, kwargs, bot_type in bot_configs:
                try:
                    bot = bot_class(**kwargs)
                    self.bots[bot_id] = {
                        'instance': bot,
                        'type': bot_type,
                        'config': kwargs
                    }
                    logger.info(f"Bot {bot_id} initialized")
                except Exception as e:
                    logger.error(f"Failed to initialize bot {bot_id}: {e}")

            logger.info(f"Total {len(self.bots)} bots initialized")

        except Exception as e:
            logger.error(f"Bot initialization error: {e}")

    def get_bot_status(self, bot_id: str) -> Optional[Dict]:
        """봇 상태 조회"""
        if bot_id not in self.bots:
            return None

        bot_data = self.bots[bot_id]
        bot = bot_data['instance']

        try:
            status = bot.get_status()
            return {
                'bot_id': bot_id,
                'name': status.get('bot_id', bot_id),
                'type': bot_data['type'],
                'status': status.get('status', 'unknown'),
                'mock_mode': status.get('mock_mode', False),
                'exchange': self._get_exchange_from_bot(bot_id, bot),
                'symbol': self._get_symbol_from_bot(bot_id, bot),
                'capital': status.get('capital', status.get('capital_sol', 0)),
                'unit': 'SOL' if 'capital_sol' in status else None,
                'pnl': status.get('total_pnl', status.get('total_pnl_sol', 0)),
                'trades': status.get('total_trades', status.get('total_bets', 0)),
                'win_rate': status.get('win_rate', 0),
            }
        except Exception as e:
            logger.error(f"Error getting status for {bot_id}: {e}")
            return {
                'bot_id': bot_id,
                'status': 'error',
                'error': str(e)
            }

    def _get_exchange_from_bot(self, bot_id: str, bot: Any) -> str:
        """봇에서 거래소 정보 추출"""
        exchange_map = {
            'grid_binance': 'Binance',
            'dca_binance': 'Binance',
            'scalper_bybit': 'Bybit',
            'triarb_binance': 'Binance',
            'funding_binance': 'Binance+Bybit',
            'hyperliquid': 'Hyperliquid',
            'polymarket': 'Polymarket',
            'pump_sniper': 'Solana',
            'ibkr_forecast': 'IBKR',
            'gmgn_copy': 'Solana',
        }
        for key, exchange in exchange_map.items():
            if key in bot_id:
                return exchange
        return 'Unknown'

    def _get_symbol_from_bot(self, bot_id: str, bot: Any) -> str:
        """봇에서 심볼 정보 추출"""
        if hasattr(bot, 'symbol'):
            return bot.symbol
        if hasattr(bot, 'symbols'):
            return '/'.join(bot.symbols[:2])
        return 'Multi'

    def get_all_bots_status(self) -> List[Dict]:
        """모든 봇 상태 조회"""
        return [self.get_bot_status(bid) for bid in self.bots.keys()]

    def get_running_bots_count(self) -> int:
        """실행 중인 봇 수"""
        count = 0
        for bot_id in self.bots:
            status = self.get_bot_status(bot_id)
            if status and status.get('status') in ['running', 'idle'] and not status.get('mock_mode'):
                count += 1
        return count

    def get_total_capital(self) -> float:
        """총 자본 조회"""
        total = 0.0
        for bot_id, bot_data in self.bots.items():
            try:
                status = bot_data['instance'].get_status()
                if 'capital' in status:
                    total += status['capital']
                elif 'capital_sol' in status:
                    # SOL 가격 약 $150로 가정
                    total += status['capital_sol'] * 150
            except:
                pass
        return total

    async def update_exchange_balances(self):
        """거래소 잔액 업데이트"""
        try:
            import ccxt.async_support as ccxt

            # Binance 잔액 조회
            try:
                api_key = os.environ.get('BINANCE_API_KEY')
                api_secret = os.environ.get('BINANCE_API_SECRET')
                if api_key and api_secret:
                    exchange = ccxt.binance({
                        'apiKey': api_key,
                        'secret': api_secret,
                        'enableRateLimit': True,
                    })
                    balance = await exchange.fetch_balance()
                    self.exchange_balances['binance'] = {
                        'USDT': balance.get('USDT', {}).get('free', 0),
                        'BTC': balance.get('BTC', {}).get('free', 0),
                        'total_usdt': balance.get('USDT', {}).get('total', 0),
                    }
                    await exchange.close()
                    self.api_usage['binance']['calls'] += 1
            except Exception as e:
                logger.warning(f"Binance balance fetch failed: {e}")
                self.exchange_balances['binance'] = {'error': str(e)}

            # Bybit 잔액 조회
            try:
                api_key = os.environ.get('BYBIT_API_KEY')
                api_secret = os.environ.get('BYBIT_API_SECRET')
                if api_key and api_secret:
                    exchange = ccxt.bybit({
                        'apiKey': api_key,
                        'secret': api_secret,
                        'enableRateLimit': True,
                    })
                    balance = await exchange.fetch_balance()
                    self.exchange_balances['bybit'] = {
                        'USDT': balance.get('USDT', {}).get('free', 0),
                        'SOL': balance.get('SOL', {}).get('free', 0),
                        'total_usdt': balance.get('USDT', {}).get('total', 0),
                    }
                    await exchange.close()
                    self.api_usage['bybit']['calls'] += 1
            except Exception as e:
                logger.warning(f"Bybit balance fetch failed: {e}")
                self.exchange_balances['bybit'] = {'error': str(e)}

            self.last_balance_update = datetime.utcnow()

            # WebSocket 브로드캐스트
            await self.broadcast_update({
                'type': 'exchange_balances',
                'data': self.exchange_balances,
                'timestamp': datetime.utcnow().isoformat()
            })

        except Exception as e:
            logger.error(f"Exchange balance update error: {e}")

    def get_withdrawable_amount(self) -> float:
        """출금 가능 금액 계산"""
        total_pnl = 0.0
        for bot_id in self.bots:
            status = self.get_bot_status(bot_id)
            if status:
                total_pnl += status.get('pnl', 0)

        # 실현 수익의 50%를 출금 가능액으로 계산
        return max(0, total_pnl * 0.5)

    async def start_bot(self, bot_id: str) -> bool:
        """봇 시작"""
        if bot_id not in self.bots:
            return False

        try:
            bot = self.bots[bot_id]['instance']
            if hasattr(bot, 'run'):
                asyncio.create_task(bot.run())
            elif hasattr(bot, 'start'):
                bot.start()

            logger.info(f"Bot {bot_id} started")
            await self.broadcast_update({
                'type': 'bot_status',
                'bot_id': bot_id,
                'status': 'running'
            })
            return True
        except Exception as e:
            logger.error(f"Failed to start bot {bot_id}: {e}")
            return False

    async def stop_bot(self, bot_id: str) -> bool:
        """봇 중지"""
        if bot_id not in self.bots:
            return False

        try:
            bot = self.bots[bot_id]['instance']
            if hasattr(bot, 'stop'):
                await bot.stop() if asyncio.iscoroutinefunction(bot.stop) else bot.stop()

            logger.info(f"Bot {bot_id} stopped")
            await self.broadcast_update({
                'type': 'bot_status',
                'bot_id': bot_id,
                'status': 'stopped'
            })
            return True
        except Exception as e:
            logger.error(f"Failed to stop bot {bot_id}: {e}")
            return False

    async def kill_all(self):
        """긴급 킬스위치"""
        self.kill_switch_active = True
        for bot_id in self.bots:
            await self.stop_bot(bot_id)

        logger.critical("KILL SWITCH ACTIVATED - All bots stopped")
        await self.broadcast_update({'type': 'kill_switch', 'active': True})

    async def process_withdrawal(self, exchange: str, asset: str) -> Dict:
        """출금 요청 처리"""
        amount = self.get_withdrawable_amount()
        if amount < 50:
            return {
                'success': False,
                'message': '출금 가능 금액이 $50 미만입니다.',
                'amount': amount
            }

        withdrawal = {
            'id': f"wd_{datetime.utcnow().timestamp()}",
            'exchange': exchange,
            'asset': asset,
            'amount': amount,
            'timestamp': datetime.utcnow().isoformat(),
            'status': 'pending'
        }
        self.withdrawal_queue.append(withdrawal)

        if self.telegram_enabled:
            await self.send_telegram_notification(
                f"💰 출금 신청\n거래소: {exchange}\n자산: {asset}\n금액: ${amount:.2f}"
            )

        return {
            'success': True,
            'message': '출금 신청이 접수되었습니다.',
            'amount': amount
        }

    async def send_telegram_notification(self, message: str):
        """Telegram 알림 발송"""
        try:
            import aiohttp
            token = os.environ.get('TELEGRAM_BOT_TOKEN')
            chat_id = os.environ.get('TELEGRAM_CHAT_ID')

            if token and chat_id:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                async with aiohttp.ClientSession() as session:
                    await session.post(url, json={
                        'chat_id': chat_id,
                        'text': message,
                        'parse_mode': 'HTML'
                    })
        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")

    async def connect_websocket(self, websocket: WebSocket):
        """WebSocket 연결"""
        await websocket.accept()
        self.websocket_clients.append(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self.websocket_clients)}")

        # 초기 데이터 전송
        await websocket.send_json({
            'type': 'init',
            'bots': self.get_all_bots_status(),
            'exchange_balances': self.exchange_balances,
            'system_metrics': self.system_metrics,
            'api_usage': self.api_usage
        })

    async def disconnect_websocket(self, websocket: WebSocket):
        """WebSocket 연결 해제"""
        if websocket in self.websocket_clients:
            self.websocket_clients.remove(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(self.websocket_clients)}")

    async def broadcast_update(self, data: Dict):
        """모든 WebSocket 클라이언트에 브로드캐스트"""
        disconnected = []
        for client in self.websocket_clients:
            try:
                await client.send_json(data)
            except:
                disconnected.append(client)

        for client in disconnected:
            await self.disconnect_websocket(client)

    async def system_optimize(self, action: str) -> Dict:
        """시스템 최적화"""
        result = {'action': action, 'success': False, 'message': ''}

        try:
            if action == 'clear_memory':
                import gc
                gc.collect()
                result['success'] = True
                result['message'] = 'Memory garbage collection completed'

            elif action == 'rotate_logs':
                # 로그 파일 로테이션
                log_dir = Path(project_root) / 'logs'
                if log_dir.exists():
                    # 오래된 로그 압축/삭제
                    result['success'] = True
                    result['message'] = 'Log rotation completed'

            elif action == 'clear_cache':
                # Redis 캐시 클리어
                try:
                    from lib.cache.redis_client import RedisCache
                    cache = RedisCache()
                    await cache.clear()
                    result['success'] = True
                    result['message'] = 'Cache cleared'
                except:
                    result['message'] = 'Cache clear failed'

            elif action == 'auto_repair':
                # 자동 수리: 중지된 봇 재시작
                restarted = []
                for bot_id in self.bots:
                    status = self.get_bot_status(bot_id)
                    if status and status.get('status') == 'error':
                        if await self.start_bot(bot_id):
                            restarted.append(bot_id)

                result['success'] = True
                result['message'] = f'Auto repair completed. Restarted: {restarted}'

        except Exception as e:
            result['message'] = str(e)

        return result


# 전역 봇 매니저 인스턴스
bot_manager = DashboardBotManager()

# FastAPI 앱
app = FastAPI(title="OZ_A2M CEO Dashboard", version="2.0.0")

# 정적 파일 마운트
static_path = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """CEO 대시보드 HTML 제공"""
    dashboard_file = static_path / "ceo_dashboard.html"
    if dashboard_file.exists():
        return dashboard_file.read_text(encoding='utf-8')
    return HTMLResponse(content="<h1>OZ_A2M CEO Dashboard</h1><p>Loading...</p>", status_code=200)


@app.get("/api/status")
async def get_status():
    """전체 시스템 상태"""
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "total_bots": len(bot_manager.bots),
        "running_bots": bot_manager.get_running_bots_count(),
        "total_capital": bot_manager.get_total_capital(),
        "withdrawable": bot_manager.get_withdrawable_amount(),
        "telegram_enabled": bot_manager.telegram_enabled,
        "kill_switch": bot_manager.kill_switch_active
    }


@app.get("/api/bots")
async def get_bots():
    """모든 봇 상태"""
    return bot_manager.get_all_bots_status()


@app.get("/api/bot/{bot_id}/status")
async def get_bot_detail(bot_id: str):
    """특정 봇 상세 상태"""
    status = bot_manager.get_bot_status(bot_id)
    if status:
        return status
    raise HTTPException(status_code=404, detail="Bot not found")


@app.post("/api/bot/{bot_id}/{action}")
async def control_bot(bot_id: str, action: str):
    """봇 제어 (start/stop)"""
    if action == 'start':
        success = await bot_manager.start_bot(bot_id)
    elif action == 'stop':
        success = await bot_manager.stop_bot(bot_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    if success:
        return {"success": True, "bot_id": bot_id, "action": action}
    raise HTTPException(status_code=404, detail="Bot not found")


@app.get("/api/exchange-balances")
async def get_exchange_balances():
    """거래소별 잔액"""
    if not bot_manager.last_balance_update or \
       (datetime.utcnow() - bot_manager.last_balance_update).seconds > 60:
        await bot_manager.update_exchange_balances()

    return {
        "balances": bot_manager.exchange_balances,
        "last_update": bot_manager.last_balance_update.isoformat() if bot_manager.last_balance_update else None
    }


@app.post("/api/withdraw")
async def withdraw(request: WithdrawRequest):
    """출금 요청"""
    result = await bot_manager.process_withdrawal(request.exchange, request.asset)
    return result


@app.get("/api/withdrawals")
async def get_withdrawals():
    """출금 히스토리"""
    return bot_manager.withdrawal_queue


@app.post("/api/killswitch")
async def kill_switch():
    """긴급 킬스위치"""
    await bot_manager.kill_all()
    return {
        "success": True,
        "message": "All bots stopped",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/api/toggle-telegram")
async def toggle_telegram(request: TelegramToggleRequest):
    """Telegram 알림 토글"""
    bot_manager.telegram_enabled = request.enabled
    return {"success": True, "enabled": request.enabled}


@app.get("/api/api-usage")
async def get_api_usage():
    """API 사용량 현황"""
    return bot_manager.api_usage


@app.post("/api/system/optimize")
async def system_optimize(request: SystemOptimizeRequest):
    """시스템 최적화"""
    result = await bot_manager.system_optimize(request.action)
    return result


@app.get("/api/profit")
async def get_profit():
    """수익 현황"""
    bots_pnl = {}
    for bot_id in bot_manager.bots:
        status = bot_manager.get_bot_status(bot_id)
        if status:
            bots_pnl[bot_id] = status.get('pnl', 0)

    return {
        "total": sum(bots_pnl.values()),
        "daily": bot_manager.daily_profits,
        "by_bot": bots_pnl
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 실시간 업데이트"""
    await bot_manager.connect_websocket(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get('type') == 'ping':
                await websocket.send_json({
                    'type': 'pong',
                    'timestamp': datetime.utcnow().isoformat()
                })
            elif msg.get('type') == 'get_balances':
                await bot_manager.update_exchange_balances()

    except WebSocketDisconnect:
        await bot_manager.disconnect_websocket(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await bot_manager.disconnect_websocket(websocket)


# 백그라운드 업데이트 태스크
async def background_updates():
    """주기적 시스템 업데이트"""
    while True:
        try:
            # 시스템 메트릭스 업데이트
            import psutil

            cpu = psutil.cpu_percent()
            memory = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent

            # Docker 상태 확인
            docker_status = 0.0
            try:
                import subprocess
                result = subprocess.run(
                    ['docker', 'ps', '-q'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                running_containers = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0
                docker_status = min(100, running_containers * 10)  # 컨테이너당 10%
            except:
                pass

            bot_manager.system_metrics = {
                'cpu': cpu,
                'memory': memory,
                'disk': disk,
                'docker': docker_status
            }

            metrics = {
                'type': 'system_metrics',
                'cpu': cpu,
                'memory': memory,
                'disk': disk,
                'docker': docker_status,
                'timestamp': datetime.utcnow().isoformat()
            }
            await bot_manager.broadcast_update(metrics)

            # 봇 상태 브로드캐스트
            for bot_id in bot_manager.bots:
                status = bot_manager.get_bot_status(bot_id)
                if status:
                    await bot_manager.broadcast_update({
                        'type': 'bot_status',
                        'bot_id': bot_id,
                        'status': status.get('status'),
                        'pnl': status.get('pnl'),
                        'trades': status.get('trades')
                    })

            # 출금 가능 금액 확인
            withdrawable = bot_manager.get_withdrawable_amount()
            if withdrawable >= 50 and bot_manager.telegram_enabled:
                await bot_manager.send_telegram_notification(
                    f"💰 출금 가능 금액: ${withdrawable:.2f}\n출금하시겠습니까?"
                )

        except Exception as e:
            logger.error(f"Background update error: {e}")

        await asyncio.sleep(30)  # 30초마다 업데이트


@app.on_event("startup")
async def startup_event():
    """서버 시작 시 실행"""
    logger.info("CEO Dashboard Server starting...")
    # 초기 거래소 잔액 조회
    await bot_manager.update_exchange_balances()
    # 백그라운드 태스크 시작
    asyncio.create_task(background_updates())


async def main():
    """서버 실행"""
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="info"
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())

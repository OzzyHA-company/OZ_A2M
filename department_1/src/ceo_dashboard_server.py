"""
OZ_A2M CEO Dashboard Server - 완결판
FastAPI + WebSocket + 정적 파일 서빙
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path

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
    action: str  # start, stop, restart

class TelegramToggleRequest(BaseModel):
    enabled: bool

# 봇 상태 관리
class BotManager:
    def __init__(self):
        self.bots: Dict[str, Dict] = {
            # 안정봇 8개
            'grid_binance_001': {'name': '봇-01 Binance Grid', 'exchange': 'Binance', 'capital': 11.0, 'type': 'stable', 'status': 'stopped', 'pnl': 0.0},
            'dca_binance_001': {'name': '봇-02 Binance DCA', 'exchange': 'Binance', 'capital': 14.0, 'type': 'stable', 'status': 'stopped', 'pnl': 0.0},
            'triarb_binance_001': {'name': '봇-03 삼각아비트라지', 'exchange': 'Binance', 'capital': 10.35, 'type': 'stable', 'status': 'stopped', 'pnl': 0.0},
            'funding_binance_bybit_001': {'name': '봇-04 Funding Rate', 'exchange': 'Binance+Bybit', 'capital': 16.0, 'type': 'stable', 'status': 'stopped', 'pnl': 0.0},
            'grid_bybit_001': {'name': '봇-05 Bybit Grid', 'exchange': 'Bybit', 'capital': 8.44, 'type': 'stable', 'status': 'stopped', 'pnl': 0.0},
            'scalper_bybit_001': {'name': '봇-06 Bybit 스캘핑', 'exchange': 'Bybit', 'capital': 20.0, 'type': 'stable', 'status': 'stopped', 'pnl': 0.0},
            'ibkr_forecast_001': {'name': '봇-08 IBKR Forecast', 'exchange': 'IBKR', 'capital': 10.0, 'type': 'stable', 'status': 'mock', 'pnl': 0.0},
            'polymarket_ai_001': {'name': '봇-09 Polymarket AI', 'exchange': 'Polymarket', 'capital': 19.85, 'type': 'stable', 'status': 'stopped', 'pnl': 0.0},
            # 도파민봇 3개
            'hyperliquid_mm_001': {'name': '봇-07 Hyperliquid', 'exchange': 'Hyperliquid', 'capital': 10.12, 'type': 'dopamine', 'status': 'stopped', 'pnl': 0.0, 'leverage': 5},
            'pump_sniper_001': {'name': '봇-11 Pump.fun 스나이퍼', 'exchange': 'Solana', 'capital': 0.1, 'type': 'dopamine', 'status': 'stopped', 'pnl': 0.0, 'unit': 'SOL'},
            'gmgn_copy_001': {'name': '봇-12 GMGN 카피', 'exchange': 'Solana', 'capital': 0.067, 'type': 'dopamine', 'status': 'stopped', 'pnl': 0.0, 'unit': 'SOL'},
        }
        self.withdrawal_queue: List[Dict] = []
        self.telegram_enabled = True
        self.total_profit = 0.0
        self.daily_profits: List[float] = []
        self.websocket_clients: List[WebSocket] = []
        self.kill_switch_active = False

    async def start_bot(self, bot_id: str) -> bool:
        if bot_id in self.bots:
            self.bots[bot_id]['status'] = 'running'
            logger.info(f"Bot {bot_id} started")
            await self.broadcast_update({'type': 'bot_status', 'bot_id': bot_id, 'status': 'running'})
            return True
        return False

    async def stop_bot(self, bot_id: str) -> bool:
        if bot_id in self.bots:
            self.bots[bot_id]['status'] = 'stopped'
            logger.info(f"Bot {bot_id} stopped")
            await self.broadcast_update({'type': 'bot_status', 'bot_id': bot_id, 'status': 'stopped'})
            return True
        return False

    async def kill_all(self):
        self.kill_switch_active = True
        for bot_id in self.bots:
            self.bots[bot_id]['status'] = 'stopped'
        logger.critical("KILL SWITCH ACTIVATED - All bots stopped")
        await self.broadcast_update({'type': 'kill_switch', 'active': True})

    def get_total_capital(self) -> float:
        return sum(b['capital'] for b in self.bots.values() if not b.get('unit'))

    def get_withdrawable_amount(self) -> float:
        # 일일 수익의 50%가 출금 대기
        today_profit = sum(self.daily_profits[-1:]) if self.daily_profits else 0
        return max(0, today_profit * 0.5)

    async def process_withdrawal(self, exchange: str, asset: str) -> Dict:
        amount = self.get_withdrawable_amount()
        if amount < 50:
            return {'success': False, 'message': '출금 가능 금액이 $50 미만입니다.', 'amount': amount}

        withdrawal = {
            'id': f"wd_{datetime.utcnow().timestamp()}",
            'exchange': exchange,
            'asset': asset,
            'amount': amount,
            'timestamp': datetime.utcnow().isoformat(),
            'status': 'pending'
        }
        self.withdrawal_queue.append(withdrawal)

        # Telegram 알림
        if self.telegram_enabled:
            await self.send_telegram_notification(
                f"💰 출금 신청\n거래소: {exchange}\n자산: {asset}\n금액: ${amount:.2f}"
            )

        return {'success': True, 'message': '출금 신청이 접수되었습니다.', 'amount': amount}

    async def send_telegram_notification(self, message: str):
        # TODO: 실제 Telegram API 연동
        logger.info(f"[Telegram] {message}")

    async def connect_websocket(self, websocket: WebSocket):
        await websocket.accept()
        self.websocket_clients.append(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self.websocket_clients)}")

    async def disconnect_websocket(self, websocket: WebSocket):
        if websocket in self.websocket_clients:
            self.websocket_clients.remove(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(self.websocket_clients)}")

    async def broadcast_update(self, data: Dict):
        disconnected = []
        for client in self.websocket_clients:
            try:
                await client.send_json(data)
            except:
                disconnected.append(client)

        for client in disconnected:
            await self.disconnect_websocket(client)

# 전역 봇 매니저
bot_manager = BotManager()

# FastAPI 앱
app = FastAPI(title="OZ_A2M CEO Dashboard", version="1.0.0")

# 정적 파일 마운트
static_path = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """CEO 대시보드 HTML 제공"""
    dashboard_file = static_path / "ceo_dashboard.html"
    if dashboard_file.exists():
        return dashboard_file.read_text(encoding='utf-8')
    return HTMLResponse(content="<h1>OZ_A2M CEO Dashboard</h1><p>Dashboard loading...</p>", status_code=200)

@app.get("/api/status")
async def get_status():
    """전체 시스템 상태"""
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "total_bots": len(bot_manager.bots),
        "running_bots": sum(1 for b in bot_manager.bots.values() if b['status'] == 'running'),
        "total_capital": bot_manager.get_total_capital(),
        "withdrawable": bot_manager.get_withdrawable_amount(),
        "telegram_enabled": bot_manager.telegram_enabled,
        "kill_switch": bot_manager.kill_switch_active
    }

@app.get("/api/bots")
async def get_bots():
    """모든 봇 상태"""
    return bot_manager.bots

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
    return {"success": True, "message": "All bots stopped", "timestamp": datetime.utcnow().isoformat()}

@app.post("/api/toggle-telegram")
async def toggle_telegram(request: TelegramToggleRequest):
    """Telegram 알림 토글"""
    bot_manager.telegram_enabled = request.enabled
    return {"success": True, "enabled": request.enabled}

@app.post("/api/restart")
async def restart_system():
    """시스템 재시작"""
    logger.info("System restart requested")
    # TODO: 실제 재시작 로직
    return {"success": True, "message": "System restart initiated"}

@app.get("/api/profit")
async def get_profit():
    """수익 현황"""
    return {
        "total": bot_manager.total_profit,
        "daily": bot_manager.daily_profits,
        "by_bot": {k: v['pnl'] for k, v in bot_manager.bots.items()}
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 실시간 업데이트"""
    await bot_manager.connect_websocket(websocket)
    try:
        while True:
            # 클라이언트로부터 메시지 수신 (ping 등)
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get('type') == 'ping':
                await websocket.send_json({'type': 'pong', 'timestamp': datetime.utcnow().isoformat()})

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
            metrics = {
                'type': 'system_metrics',
                'cpu': psutil.cpu_percent(),
                'memory': psutil.virtual_memory().percent,
                'disk': psutil.disk_usage('/').percent,
                'timestamp': datetime.utcnow().isoformat()
            }
            await bot_manager.broadcast_update(metrics)

            # 출금 가능 금액 확인 및 알림
            withdrawable = bot_manager.get_withdrawable_amount()
            if withdrawable >= 50 and bot_manager.telegram_enabled:
                await bot_manager.send_telegram_notification(
                    f"💰 출금 가능 금액: ${withdrawable:.2f}\n출금하시겠습니까? 대시보드에서 확인해주세요."
                )

        except Exception as e:
            logger.error(f"Background update error: {e}")

        await asyncio.sleep(30)  # 30초마다 업데이트

@app.on_event("startup")
async def startup_event():
    """서버 시작 시 실행"""
    logger.info("CEO Dashboard Server starting...")
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

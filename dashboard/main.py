#!/usr/bin/env python3
"""
OZ_A2M Real-time Trading Dashboard
FastAPI + WebSocket + Redis
Port: 8083
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, Any, Optional

import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Redis connection
redis_client: Optional[redis.Redis] = None

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

# System state
system_state = {
    "trading_active": True,
    "live_trading": True,
    "pnl_today": 0.0,
    "pnl_pct": 0.0,
    "position": "LONG BTC",
    "position_size": 0.001,
    "capital": 97.79,
    "bots_active": 11,
    "timestamp": datetime.now().isoformat()
}

# Infrastructure status
infra_status = {
    "redis": {"status": "active", "port": 6379},
    "kafka": {"status": "active", "port": 9092},
    "mqtt": {"status": "active", "port": 1883},
    "api_gateway": {"status": "active", "port": 8000},
    "grafana": {"status": "active", "port": 3000},
    "elasticsearch": {"status": "active", "port": 9200},
    "netdata": {"status": "active", "port": 19999},
    "prometheus": {"status": "active", "port": 9090},
}

# Bot statuses
bots = [
    {"name": "Grid Bot", "exchange": "Binance", "status": "active", "allocation": 11.00, "pnl": 0.0},
    {"name": "DCA Bot", "exchange": "Binance", "status": "active", "allocation": 14.00, "pnl": 0.0},
    {"name": "Triarb Bot", "exchange": "Binance", "status": "active", "allocation": 10.35, "pnl": 0.0},
    {"name": "Funding Bot", "exchange": "Bybit", "status": "active", "allocation": 8.00, "pnl": 0.0},
    {"name": "Grid Bot", "exchange": "Bybit", "status": "active", "allocation": 8.44, "pnl": 0.0},
    {"name": "Scalper Bot", "exchange": "Bybit", "status": "active", "allocation": 7.94, "pnl": 0.0},
    {"name": "Polymarket", "exchange": "Polygon", "status": "active", "allocation": 19.84, "pnl": 0.0},
    {"name": "Hyperliquid", "exchange": "Phantom A", "status": "active", "allocation": 6.19, "pnl": 0.0},
    {"name": "Pump.fun", "exchange": "Phantom B", "status": "active", "allocation": 6.19, "pnl": 0.0},
    {"name": "GMGN", "exchange": "Phantom C", "status": "active", "allocation": 6.18, "pnl": 0.0},
    {"name": "Solana MEV", "exchange": "Jito", "status": "active", "allocation": 0.00, "pnl": 0.0},
]

# AI Brain status
ai_brain = {
    "pi_mono": {"status": "active", "model": "gemini-2.5-flash"},
    "gemini_pro": {"status": "active", "session_valid": "2026-04-08"},
    "ant_colony": {
        "queen": 1,
        "scouts": 5,
        "workers": 10,
        "soldiers": 3
    }
}

# Jito MEV status
jito_status = {
    "shredstream": {
        "status": "active",
        "tx_rate": "10,000+",
        "mempool_feed": "connected"
    },
    "block_engine": {
        "status": "active",
        "bundle_builder": "ready",
        "mev_protection": "enabled"
    }
}

async def redis_listener():
    """Listen for Redis updates and broadcast to WebSocket clients"""
    global redis_client
    while True:
        try:
            if redis_client is None:
                redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

            # Subscribe to channels
            pubsub = redis_client.pubsub()
            await pubsub.subscribe('oz_a2m:trades', 'oz_a2m:pnl', 'oz_a2m:status')

            async for message in pubsub.listen():
                if message['type'] == 'message':
                    data = json.loads(message['data'])
                    await manager.broadcast({
                        "type": "redis_update",
                        "channel": message['channel'],
                        "data": data,
                        "timestamp": datetime.now().isoformat()
                    })
        except Exception as e:
            logger.error(f"Redis listener error: {e}")
            await asyncio.sleep(5)

async def heartbeat():
    """Send periodic heartbeat with full state"""
    while True:
        try:
            # Update timestamp
            system_state["timestamp"] = datetime.now().isoformat()

            # Try to get real data from Redis
            try:
                if redis_client:
                    pnl = await redis_client.get('oz_a2m:pnl:today')
                    if pnl:
                        system_state["pnl_today"] = float(pnl)
            except:
                pass

            await manager.broadcast({
                "type": "heartbeat",
                "state": system_state,
                "infra": infra_status,
                "bots": bots,
                "ai": ai_brain,
                "jito": jito_status,
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")

        await asyncio.sleep(5)  # Update every 5 seconds

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup/shutdown"""
    # Startup
    logger.info("Starting OZ_A2M Dashboard...")
    asyncio.create_task(redis_listener())
    asyncio.create_task(heartbeat())
    yield
    # Shutdown
    logger.info("Shutting down...")

app = FastAPI(lifespan=lifespan, title="OZ_A2M Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard HTML"""
    with open('/home/ozzy-claw/OZ_A2M/dashboard/index.html', 'r') as f:
        return f.read()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial state
        await websocket.send_json({
            "type": "init",
            "state": system_state,
            "infra": infra_status,
            "bots": bots,
            "ai": ai_brain,
            "jito": jito_status
        })

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("action") == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/api/status")
async def api_status():
    """REST API endpoint for status"""
    return {
        "state": system_state,
        "infra": infra_status,
        "bots": bots,
        "ai": ai_brain,
        "jito": jito_status
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8083)

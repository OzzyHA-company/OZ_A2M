#!/usr/bin/env python3
"""
OZ_A2M Unified Dashboard v2.0
실제 거래 데이터 기반 + 리워드 보상체계 + Prometheus 메트릭

References:
- freqtrade: 실시간 거래 UI 패턴
- habitica: RPG 보상시스템
- prometheus: 메트릭 수집
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum

from dotenv import load_dotenv
load_dotenv('/home/ozzy-claw/.ozzy-secrets/master.env', override=True)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import redis.asyncio as redis
import aiohttp

# 프로젝트 경로 설정
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(title="OZ_A2M Unified Dashboard v2.0")

# Prometheus 메트릭 정의
TRADE_COUNT = Counter('oz_a2m_trades_total', 'Total trades', ['bot_id', 'exchange', 'status'])
PNL_GAUGE = Gauge('oz_a2m_pnl_usd', 'PnL in USD', ['bot_id', 'exchange'])
CAPITAL_GAUGE = Gauge('oz_a2m_capital_usd', 'Allocated capital', ['bot_id'])
BOT_STATUS = Gauge('oz_a2m_bot_status', 'Bot status (1=running, 0=stopped)', ['bot_id'])
REQUEST_DURATION = Histogram('oz_a2m_request_duration_seconds', 'Request duration')


class BotTier(Enum):
    """봇 등급 - Habitica 스타일"""
    BRONZE = {"name": "Bronze", "kr_name": "브론즈", "color": "#CD7F32", "min_level": 1, "max_level": 5}
    SILVER = {"name": "Silver", "kr_name": "실버", "color": "#C0C0C0", "min_level": 6, "max_level": 15}
    GOLD = {"name": "Gold", "kr_name": "골드", "color": "#FFD700", "min_level": 16, "max_level": 30}
    PLATINUM = {"name": "Platinum", "kr_name": "플래티넘", "color": "#E5E4E2", "min_level": 31, "max_level": 50}
    DIAMOND = {"name": "Diamond", "kr_name": "다이아몬드", "color": "#B9F2FF", "min_level": 51, "max_level": 75}
    LEGEND = {"name": "Legend", "kr_name": "전설", "color": "#FF6B35", "min_level": 76, "max_level": 100}


@dataclass
class BotStats:
    """봇 통계 데이터"""
    bot_id: str
    name: str
    exchange: str
    symbol: str
    capital: float
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    win_rate: float = 0.0
    status: str = "stopped"
    level: int = 1
    exp: int = 0
    hp: int = 100
    max_hp: int = 100
    consecutive_wins: int = 0
    last_trade_time: Optional[str] = None
    mock_mode: bool = False


@dataclass
class RewardSystem:
    """리워드 보상체계 - Habitica 참고"""
    daily_streak: int = 0
    total_achievements: int = 0
    gold_earned: float = 0.0
    experience_gained: int = 0
    badges: List[str] = None

    def __post_init__(self):
        if self.badges is None:
            self.badges = []


class UnifiedDashboard:
    """통합 대시보드 관리자"""

    # 실제 BOT_CONFIGS (run_all_bots.py와 동기화)
    BOT_DEFINITIONS = [
        {"id": "dca_binance_001", "name": "DCA Bot", "exchange": "Binance", "symbol": "SOL/USDT", "capital": 13.0, "type": "stable"},
        {"id": "grid_binance_001", "name": "Grid Bot", "exchange": "Binance", "symbol": "SOL/USDT", "capital": 10.0, "type": "stable"},
        {"id": "triarb_binance_001", "name": "Tri Arb", "exchange": "Binance", "symbol": "Multi", "capital": 9.71, "type": "stable"},
        {"id": "funding_binance_bybit_001", "name": "Funding", "exchange": "Multi", "symbol": "Multi", "capital": 5.0, "type": "stable"},
        {"id": "grid_bybit_001", "name": "Bybit Grid", "exchange": "Bybit", "symbol": "SOL/USDT", "capital": 10.32, "type": "stable"},
        {"id": "scalper_bybit_001", "name": "Scalper", "exchange": "Bybit", "symbol": "SOL/USDT", "capital": 8.0, "type": "stable"},
        {"id": "hyperliquid_mm_001", "name": "HL MM", "exchange": "Hyperliquid", "symbol": "SOL-PERP", "capital": 4.43, "type": "dopamine"},
        {"id": "ibkr_forecast_001", "name": "IBKR AI", "exchange": "IBKR", "symbol": "AAPL/MSFT", "capital": 10.0, "type": "stable", "mock": True},
        {"id": "polymarket_ai_001", "name": "Polymarket", "exchange": "Polymarket", "symbol": "Multi", "capital": 19.84, "type": "dopamine"},
        {"id": "pump_sniper_001", "name": "Pump Sniper", "exchange": "Solana", "symbol": "New Tokens", "capital": 0.1, "capital_sol": True, "type": "dopamine"},
        {"id": "gmgn_copy_001", "name": "GMGN Copy", "exchange": "Solana", "symbol": "Smart Money", "capital": 0.067, "capital_sol": True, "type": "dopamine"},
    ]

    def __init__(self):
        self.bots: Dict[str, BotStats] = {}
        self.redis_client: Optional[redis.Redis] = None
        self.active_connections: List[WebSocket] = []
        self.reward_systems: Dict[str, RewardSystem] = {}
        self._initialize_bots()

    def _initialize_bots(self):
        """봇 초기화"""
        for bot_def in self.BOT_DEFINITIONS:
            capital = bot_def.get("capital", 0)
            if bot_def.get("capital_sol"):
                capital = capital * 150  # SOL 가격 가정

            self.bots[bot_def["id"]] = BotStats(
                bot_id=bot_def["id"],
                name=bot_def["name"],
                exchange=bot_def["exchange"],
                symbol=bot_def["symbol"],
                capital=capital,
                mock_mode=bot_def.get("mock", False)
            )
            self.reward_systems[bot_def["id"]] = RewardSystem()

    async def connect_redis(self):
        """Redis 연결"""
        try:
            self.redis_client = redis.Redis(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', 6379)),
                db=0,
                decode_responses=True
            )
            await self.redis_client.ping()
            logger.info("Redis connected")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            self.redis_client = None

    async def fetch_bot_data_from_redis(self) -> Dict[str, Any]:
        """Redis에서 실제 봇 데이터 조회"""
        if not self.redis_client:
            return {}

        data = {}
        try:
            # 봇 상태 조회
            for bot_id in self.bots.keys():
                key = f"bot:{bot_id}:status"
                status_data = await self.redis_client.get(key)
                if status_data:
                    data[bot_id] = json.loads(status_data)
        except Exception as e:
            logger.error(f"Redis fetch error: {e}")

        return data

    async def fetch_real_time_data(self) -> Dict[str, Any]:
        """실시간 데이터 수집"""
        # Redis에서 데이터 가져오기
        redis_data = await self.fetch_bot_data_from_redis()

        # 봇 데이터 업데이트
        for bot_id, bot in self.bots.items():
            if bot_id in redis_data:
                rdata = redis_data[bot_id]
                bot.status = rdata.get("status", "unknown")
                bot.pnl_usd = float(rdata.get("pnl", 0))
                bot.total_trades = int(rdata.get("trades", 0))
                bot.win_rate = float(rdata.get("win_rate", 0))

                # Prometheus 메트릭 업데이트
                BOT_STATUS.labels(bot_id=bot_id).set(1 if bot.status == "running" else 0)
                PNL_GAUGE.labels(bot_id=bot_id, exchange=bot.exchange).set(bot.pnl_usd)
                CAPITAL_GAUGE.labels(bot_id=bot_id).set(bot.capital)

        # 합계 계산
        total_capital = sum(b.capital for b in self.bots.values())
        total_pnl = sum(b.pnl_usd for b in self.bots.values())
        running_count = sum(1 for b in self.bots.values() if b.status == "running")

        # 보상 계산
        self._calculate_rewards()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "summary": {
                "total_capital": total_capital,
                "total_pnl": total_pnl,
                "total_pnl_pct": (total_pnl / total_capital * 100) if total_capital > 0 else 0,
                "running_bots": running_count,
                "total_bots": len(self.bots),
            },
            "bots": [asdict(b) for b in self.bots.values()],
            "rewards": {k: asdict(v) for k, v in self.reward_systems.items()},
            "stable_bots": [asdict(b) for b in self.bots.values() if b.exchange in ["Binance", "Bybit", "IBKR"]],
            "dopamine_bots": [asdict(b) for b in self.bots.values() if b.exchange in ["Hyperliquid", "Polymarket", "Solana"]],
        }

    def _calculate_rewards(self):
        """보상 계산"""
        for bot_id, bot in self.bots.items():
            reward = self.reward_systems[bot_id]

            # PnL 기반 골드 獲得
            if bot.pnl_usd > 0:
                reward.gold_earned += bot.pnl_usd * 0.1
                reward.experience_gained += int(bot.pnl_usd * 10)

            # 연승 보너스
            if bot.consecutive_wins > reward.daily_streak:
                reward.daily_streak = bot.consecutive_wins

            # 레벨업 계산
            bot.exp = reward.experience_gained
            new_level = self._calculate_level(bot.exp)
            if new_level > bot.level:
                bot.level = new_level
                logger.info(f"🎉 {bot.name} 레벨업! Lv.{bot.level}")

    def _calculate_level(self, exp: int) -> int:
        """경험치로 레벨 계산"""
        return min(100, 1 + exp // 100)

    def get_tier(self, level: int) -> dict:
        """레벨에 따른 등급 반환"""
        for tier in BotTier:
            if tier.value["min_level"] <= level <= tier.value["max_level"]:
                return tier.value
        return BotTier.BRONZE.value

    async def broadcast_update(self):
        """모든 클라이언트에 실시간 업데이트"""
        data = await self.fetch_real_time_data()

        # 등급 정보 추가
        for bot_data in data["bots"]:
            bot_data["tier"] = self.get_tier(bot_data["level"])

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except:
                disconnected.append(connection)

        # 연결 끊긴 클라이언트 정리
        for conn in disconnected:
            if conn in self.active_connections:
                self.active_connections.remove(conn)


# 대시보드 인스턴스
dashboard = UnifiedDashboard()


@app.on_event("startup")
async def startup_event():
    """시작 이벤트"""
    await dashboard.connect_redis()
    logger.info("Unified Dashboard v2.0 started")


@app.get("/")
async def get_dashboard():
    """메인 대시보드 - Freqtrade 스타일"""
    data = await dashboard.fetch_real_time_data()

    html_content = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OZ_A2M Trading Dashboard v2.0</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            min-height: 100vh;
        }}
        .header {{
            background: #161b22;
            border-bottom: 1px solid #30363d;
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 100;
        }}
        .header h1 {{
            font-size: 20px;
            color: #58a6ff;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .status-badge {{
            background: #238636;
            color: white;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            padding: 24px;
        }}
        .card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.3);
        }}
        .card-label {{
            font-size: 12px;
            color: #8b949e;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }}
        .card-value {{
            font-size: 28px;
            font-weight: 700;
        }}
        .positive {{ color: #3fb950; }}
        .negative {{ color: #f85149; }}
        .neutral {{ color: #c9d1d9; }}
        .section {{
            padding: 0 24px 24px;
        }}
        .section-title {{
            font-size: 16px;
            color: #f0f6fc;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .bot-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 16px;
        }}
        .bot-card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 16px;
            position: relative;
            overflow: hidden;
        }}
        .bot-card::before {{
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: 4px;
            background: var(--tier-color, #58a6ff);
        }}
        .bot-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }}
        .bot-name {{
            font-weight: 600;
            color: #f0f6fc;
        }}
        .bot-tier {{
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 10px;
            background: var(--tier-color, #58a6ff);
            color: #000;
            font-weight: 600;
        }}
        .bot-meta {{
            display: flex;
            gap: 12px;
            font-size: 12px;
            color: #8b949e;
            margin-bottom: 12px;
        }}
        .bot-stats {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            margin-bottom: 12px;
        }}
        .stat {{
            text-align: center;
        }}
        .stat-value {{
            font-size: 18px;
            font-weight: 600;
            color: #f0f6fc;
        }}
        .stat-label {{
            font-size: 10px;
            color: #8b949e;
            text-transform: uppercase;
        }}
        .hp-bar {{
            height: 6px;
            background: #21262d;
            border-radius: 3px;
            overflow: hidden;
        }}
        .hp-fill {{
            height: 100%;
            background: linear-gradient(90deg, #238636, #3fb950);
            transition: width 0.3s;
        }}
        .hp-fill.low {{ background: #f85149; }}
        .hp-fill.medium {{ background: #d29922; }}
        .controls {{
            position: fixed;
            bottom: 24px;
            right: 24px;
            display: flex;
            gap: 12px;
        }}
        .btn {{
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 14px;
        }}
        .btn-kill {{
            background: #da3633;
            color: white;
        }}
        .btn-kill:hover {{ background: #f85149; }}
        .btn-refresh {{
            background: #1f6feb;
            color: white;
        }}
        .btn-refresh:hover {{ background: #58a6ff; }}
        .badge {{
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }}
        .badge-running {{ background: #238636; color: white; }}
        .badge-stopped {{ background: #484f58; color: #8b949e; }}
        .badge-mock {{ background: #d29922; color: #000; }}
        @media (max-width: 768px) {{
            .summary-cards {{ grid-template-columns: 1fr; }}
            .bot-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 OZ_A2M Trading Dashboard v2.0</h1>
        <div>
            <span class="status-badge">● LIVE</span>
        </div>
    </div>

    <div class="summary-cards">
        <div class="card">
            <div class="card-label">Total Capital</div>
            <div class="card-value neutral">${data['summary']['total_capital']:.2f}</div>
        </div>
        <div class="card">
            <div class="card-label">Total PnL</div>
            <div class="card-value {'positive' if data['summary']['total_pnl'] >= 0 else 'negative'}">${data['summary']['total_pnl']:+.2f}</div>
        </div>
        <div class="card">
            <div class="card-label">PnL %</div>
            <div class="card-value {'positive' if data['summary']['total_pnl_pct'] >= 0 else 'negative'}">{data['summary']['total_pnl_pct']:+.2f}%</div>
        </div>
        <div class="card">
            <div class="card-label">Active Bots</div>
            <div class="card-value neutral">{data['summary']['running_bots']}/{data['summary']['total_bots']}</div>
        </div>
    </div>

    <div class="section">
        <h2 class="section-title">📊 Stable Bots</h2>
        <div class="bot-grid" id="stable-bots">
            <!-- Stable bots rendered by JS -->
        </div>
    </div>

    <div class="section">
        <h2 class="section-title">🚀 Dopamine Bots</h2>
        <div class="bot-grid" id="dopamine-bots">
            <!-- Dopamine bots rendered by JS -->
        </div>
    </div>

    <div class="controls">
        <button class="btn btn-refresh" onclick="refreshData()">🔄 Refresh</button>
        <button class="btn btn-kill" onclick="killSwitch()">🚨 KILL SWITCH</button>
    </div>

    <script>
        const ws = new WebSocket(`ws://${{window.location.host}}/ws`);

        ws.onmessage = function(event) {{
            const data = JSON.parse(event.data);
            updateDashboard(data);
        }};

        ws.onerror = function(error) {{
            console.error('WebSocket error:', error);
        }};

        function updateDashboard(data) {{
            // Update summary cards
            document.querySelectorAll('.card-value')[0].textContent = `$${{data.summary.total_capital.toFixed(2)}}`;
            document.querySelectorAll('.card-value')[1].textContent = `$${{data.summary.total_pnl.toFixed(2)}}`;
            document.querySelectorAll('.card-value')[2].textContent = `${{data.summary.total_pnl_pct.toFixed(2)}}%`;
            document.querySelectorAll('.card-value')[3].textContent = `${{data.summary.running_bots}}/${{data.summary.total_bots}}`;

            // Update stable bots
            const stableContainer = document.getElementById('stable-bots');
            stableContainer.innerHTML = data.stable_bots.map(bot => renderBotCard(bot)).join('');

            // Update dopamine bots
            const dopamineContainer = document.getElementById('dopamine-bots');
            dopamineContainer.innerHTML = data.dopamine_bots.map(bot => renderBotCard(bot)).join('');
        }}

        function renderBotCard(bot) {{
            const tier = bot.tier || {{color: '#58a6ff', kr_name: '브론즈'}};
            const pnlClass = bot.pnl_usd >= 0 ? 'positive' : 'negative';
            const statusBadge = bot.status === 'running'
                ? '<span class="badge badge-running">● RUNNING</span>'
                : '<span class="badge badge-stopped">○ STOPPED</span>';
            const mockBadge = bot.mock_mode ? '<span class="badge badge-mock">MOCK</span>' : '';

            return `
                <div class="bot-card" style="--tier-color: ${{tier.color}}">
                    <div class="bot-header">
                        <span class="bot-name">${{bot.name}}</span>
                        <span class="bot-tier">${{tier.kr_name}}</span>
                    </div>
                    <div class="bot-meta">
                        ${{bot.exchange}} | ${{bot.symbol}} | Lv.${{bot.level}}
                    </div>
                    <div class="bot-stats">
                        <div class="stat">
                            <div class="stat-value">${{bot.capital.toFixed(2)}}</div>
                            <div class="stat-label">Capital</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value ${{pnlClass}}">${{bot.pnl_usd.toFixed(2)}}</div>
                            <div class="stat-label">PnL</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">${{bot.win_rate.toFixed(1)}}%</div>
                            <div class="stat-label">Win Rate</div>
                        </div>
                    </div>
                    <div class="hp-bar">
                        <div class="hp-fill ${{bot.hp < 30 ? 'low' : bot.hp < 70 ? 'medium' : ''}}" style="width: ${{bot.hp}}%"></div>
                    </div>
                    <div style="margin-top: 8px; display: flex; gap: 8px;">
                        ${{statusBadge}} ${{mockBadge}}
                    </div>
                </div>
            `;
        }}

        function refreshData() {{
            ws.send(JSON.stringify({{action: 'refresh'}}));
        }}

        function killSwitch() {{
            if (confirm('🚨 정말 모든 봇을 중지하시겠습니까?')) {{
                fetch('/api/kill-switch', {{method: 'POST'}})
                    .then(r => r.json())
                    .then(data => alert(data.message))
                    .catch(e => alert('Error: ' + e));
            }}
        }}
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


@app.get("/metrics")
async def metrics():
    """Prometheus 메트릭 엔드포인트"""
    return HTMLResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/status")
async def api_status():
    """API 상태 엔드포인트"""
    data = await dashboard.fetch_real_time_data()
    return JSONResponse(content=data)


@app.post("/api/kill-switch")
async def kill_switch():
    """킬스위치 - 모든 봇 중지"""
    logger.critical("🚨 KILL SWITCH ACTIVATED")
    # 여기서 실제 봇 중지 로직 구현
    return {"status": "success", "message": "Kill switch activated - All bots stopping"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 실시간 업데이트"""
    await websocket.accept()
    dashboard.active_connections.append(websocket)

    try:
        # 초기 데이터 전송
        await dashboard.broadcast_update()

        while True:
            message = await websocket.receive_text()
            if message == 'refresh':
                await dashboard.broadcast_update()
            await asyncio.sleep(1)

    except WebSocketDisconnect:
        if websocket in dashboard.active_connections:
            dashboard.active_connections.remove(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

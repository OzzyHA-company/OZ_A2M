"""
OZ_A2M RPG Style Dashboard
RPGUI 기반 게이미피케이션 대시보드

Reference: https://github.com/RonenNess/RPGUI

Features:
- 봇 카드 (HP/EXP/등급 시각화)
- 리그 테이블 (10봇 경쟁)
- 마스터 금고 현황
- 실시간 자본 이동 컨트롤
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import json
import logging

from ...lib.core.profit import get_vault_manager, get_settlement_system
from ...lib.core.reward_system import RPGSystem, BotGrade
from ...department_7.src.bot.run_all_bots import BOT_CONFIGS

logger = logging.getLogger(__name__)

app = FastAPI(title="OZ_A2M RPG Dashboard")

# 정적 파일 마운트
app.mount("/static", StaticFiles(directory="static"), name="static")


class RPGDashboard:
    """RPG 스타일 대시보드 관리자"""

    def __init__(self):
        self.vault_manager = get_vault_manager()
        self.settlement_system = get_settlement_system()
        self.rpg = RPGSystem()
        self.active_connections: List[WebSocket] = []

    async def get_bot_cards(self) -> List[Dict]:
        """RPG 스타일 봇 카드 데이터"""
        cards = []

        for config in BOT_CONFIGS:
            bot_id = config['id']
            bot_name = config['name']

            # RPG 상태 조회
            rpg_state = self.rpg.get_or_create_state(bot_id, bot_name)

            # 수익 데이터 조회
            profit_data = await self._get_bot_profit_data(bot_id)

            # 등급 스타일
            tier_style = self._get_tier_style(rpg_state.grade)

            card = {
                'bot_id': bot_id,
                'bot_name': bot_name,
                'tier': {
                    'name': rpg_state.grade.kr_name,
                    'color': tier_style['color'],
                    'glow': tier_style['glow'],
                    'border': tier_style['border'],
                },
                'level': {
                    'current': rpg_state.level.current,
                    'progress_pct': rpg_state.level.progress_pct,
                    'next_exp': rpg_state.level._required_exp_for_next(),
                },
                'hp': {
                    'current': rpg_state.hp.current,
                    'max': rpg_state.hp.max_hp,
                    'pct': (rpg_state.hp.current / rpg_state.hp.max_hp) * 100,
                    'status': 'critical' if rpg_state.hp.is_critical else 'healthy' if rpg_state.hp.is_healthy else 'normal',
                },
                'stats': {
                    'total_trades': rpg_state.total_trades,
                    'win_rate': rpg_state.win_trades / rpg_state.total_trades * 100 if rpg_state.total_trades > 0 else 0,
                    'consecutive_wins': rpg_state.consecutive_wins,
                },
                'profit': profit_data,
                'capital': config['kwargs'].get('capital', 0),
            }
            cards.append(card)

        return cards

    async def get_league_table(self) -> List[Dict]:
        """10봇 리그 테이블"""
        bots = await self.get_bot_cards()

        # 점수 계산
        for bot in bots:
            bot['score'] = (
                bot['profit']['profit_pct'] * 0.4 +
                bot['stats']['win_rate'] * 0.3 +
                bot['level']['current'] * 2 +
                (bot['hp']['pct'] / 100) * 10
            )

        # 정렬
        bots.sort(key=lambda x: x['score'], reverse=True)

        # 순위 추가
        for i, bot in enumerate(bots, 1):
            bot['rank'] = i
            bot['rank_emoji'] = ['🥇', '🥈', '🥉'][i-1] if i <= 3 else f'{i}위'

        return bots

    async def get_vault_summary(self) -> Dict:
        """마스터 금고 요약"""
        return await self.vault_manager.get_vault_summary()

    def _get_tier_style(self, grade: BotGrade) -> Dict:
        """등급별 스타일"""
        styles = {
            BotGrade.BRONZE: {'color': '#CD7F32', 'glow': 'bronze', 'border': '2px solid #CD7F32'},
            BotGrade.SILVER: {'color': '#C0C0C0', 'glow': 'silver', 'border': '3px solid #C0C0C0'},
            BotGrade.GOLD: {'color': '#FFD700', 'glow': 'gold', 'border': '3px solid #FFD700'},
            BotGrade.PLATINUM: {'color': '#E5E4E2', 'glow': 'platinum', 'border': '3px solid #E5E4E2'},
            BotGrade.DIAMOND: {'color': '#B9F2FF', 'glow': 'diamond', 'border': '4px solid #B9F2FF'},
            BotGrade.LEGEND: {'color': '#FF6B35', 'glow': 'legend', 'border': '5px double #FF6B35'},
        }
        return styles.get(grade, styles[BotGrade.BRONZE])

    async def _get_bot_profit_data(self, bot_id: str) -> Dict:
        """봇 수익 데이터"""
        # TODO: 실제 수익 데이터 조회
        return {
            'realized_profit': 0.0,
            'profit_pct': 0.0,
            'today_pnl': 0.0,
        }

    async def broadcast_update(self):
        """모든 연결된 클라이언트에 실시간 업데이트"""
        data = {
            'timestamp': datetime.utcnow().isoformat(),
            'bots': await self.get_bot_cards(),
            'league': await self.get_league_table(),
            'vault': await self.get_vault_summary(),
        }

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except:
                disconnected.append(connection)

        # 연결 끊긴 클라이언트 정리
        for conn in disconnected:
            self.active_connections.remove(conn)


# 대시보드 인스턴스
dashboard = RPGDashboard()


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """메인 대시보드 페이지"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>OZ_A2M RPG Dashboard</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="/static/rpgui.css">
        <style>
            body {
                background: #1a1a2e;
                color: #eee;
                font-family: 'Courier New', monospace;
                margin: 0;
                padding: 20px;
            }
            .header {
                text-align: center;
                padding: 20px;
                background: linear-gradient(135deg, #16213e 0%, #0f3460 100%);
                border: 3px solid #e94560;
                border-radius: 10px;
                margin-bottom: 20px;
            }
            .header h1 {
                margin: 0;
                color: #e94560;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
            }
            .vault-summary {
                display: flex;
                justify-content: space-around;
                padding: 15px;
                background: #16213e;
                border: 2px solid #533483;
                border-radius: 8px;
                margin-bottom: 20px;
            }
            .vault-item {
                text-align: center;
            }
            .vault-item .label {
                font-size: 12px;
                color: #888;
            }
            .vault-item .value {
                font-size: 24px;
                font-weight: bold;
                color: #ffd700;
            }
            .bot-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                gap: 20px;
                margin-bottom: 20px;
            }
            .bot-card {
                background: #16213e;
                border-radius: 10px;
                padding: 15px;
                position: relative;
                transition: transform 0.2s;
            }
            .bot-card:hover {
                transform: translateY(-5px);
            }
            .bot-card.bronze { border: 2px solid #CD7F32; box-shadow: 0 0 10px #CD7F32; }
            .bot-card.silver { border: 3px solid #C0C0C0; box-shadow: 0 0 15px #C0C0C0; }
            .bot-card.gold { border: 3px solid #FFD700; box-shadow: 0 0 20px #FFD700; }
            .bot-card.platinum { border: 3px solid #E5E4E2; box-shadow: 0 0 25px #E5E4E2; }
            .bot-card.diamond { border: 4px solid #B9F2FF; box-shadow: 0 0 30px #B9F2FF; animation: pulse 2s infinite; }
            .bot-card.legend { border: 5px double #FF6B35; box-shadow: 0 0 35px #FF6B35; animation: rainbow 3s infinite; }

            @keyframes pulse {
                0%, 100% { box-shadow: 0 0 30px #B9F2FF; }
                50% { box-shadow: 0 0 50px #B9F2FF; }
            }
            @keyframes rainbow {
                0% { box-shadow: 0 0 35px #ff0000; }
                25% { box-shadow: 0 0 35px #00ff00; }
                50% { box-shadow: 0 0 35px #0000ff; }
                75% { box-shadow: 0 0 35px #ff00ff; }
                100% { box-shadow: 0 0 35px #ff0000; }
            }

            .bot-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 10px;
            }
            .bot-name {
                font-size: 18px;
                font-weight: bold;
            }
            .bot-tier {
                font-size: 12px;
                padding: 3px 8px;
                border-radius: 5px;
                background: rgba(255,255,255,0.1);
            }
            .hp-bar, .exp-bar {
                height: 20px;
                background: #0a0a0a;
                border: 2px solid #333;
                border-radius: 10px;
                overflow: hidden;
                margin-bottom: 8px;
                position: relative;
            }
            .hp-fill {
                height: 100%;
                background: linear-gradient(90deg, #e74c3c, #f39c12, #27ae60);
                transition: width 0.3s;
            }
            .hp-fill.critical { background: #e74c3c; }
            .hp-fill.low { background: #f39c12; }
            .hp-fill.healthy { background: #27ae60; }
            .exp-fill {
                height: 100%;
                background: linear-gradient(90deg, #3498db, #9b59b6);
                transition: width 0.3s;
            }
            .bar-label {
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                font-size: 11px;
                font-weight: bold;
                text-shadow: 1px 1px 2px rgba(0,0,0,0.8);
            }
            .bot-stats {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 10px;
                margin-top: 10px;
                font-size: 12px;
            }
            .stat-item {
                text-align: center;
                background: rgba(0,0,0,0.3);
                padding: 5px;
                border-radius: 5px;
            }
            .stat-label {
                color: #888;
                font-size: 10px;
            }
            .stat-value {
                font-weight: bold;
                color: #fff;
            }
            .league-table {
                background: #16213e;
                border: 2px solid #e94560;
                border-radius: 10px;
                padding: 20px;
                margin-top: 20px;
            }
            .league-table h2 {
                text-align: center;
                color: #e94560;
                margin-bottom: 15px;
            }
            .league-row {
                display: flex;
                justify-content: space-between;
                padding: 10px;
                border-bottom: 1px solid #333;
                align-items: center;
            }
            .league-row:hover {
                background: rgba(255,255,255,0.05);
            }
            .rank { font-size: 20px; width: 40px; }
            .bot-info { flex: 1; }
            .bot-tier-small { font-size: 10px; color: #888; }
            .score { font-weight: bold; color: #ffd700; }
            .control-panel {
                position: fixed;
                right: 20px;
                top: 50%;
                transform: translateY(-50%);
                background: #16213e;
                border: 2px solid #533483;
                border-radius: 10px;
                padding: 15px;
                width: 200px;
            }
            .control-btn {
                width: 100%;
                padding: 10px;
                margin-bottom: 10px;
                background: #e94560;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-weight: bold;
            }
            .control-btn:hover {
                background: #ff6b6b;
            }
            .control-btn.secondary {
                background: #533483;
            }
            .control-btn.secondary:hover {
                background: #7b68ee;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🏆 OZ_A2M RPG Trading Arena</h1>
            <p>11 Bots Competing for Glory</p>
        </div>

        <div class="vault-summary" id="vault-summary">
            <div class="vault-item">
                <div class="label">Total Profit</div>
                <div class="value" id="total-profit">$0.00</div>
            </div>
            <div class="vault-item">
                <div class="label">Today's PnL</div>
                <div class="value" id="today-pnl">$0.00</div>
            </div>
            <div class="vault-item">
                <div class="label">Best Bot</div>
                <div class="value" id="best-bot">-</div>
            </div>
        </div>

        <div class="bot-grid" id="bot-grid">
            <!-- Bot cards will be inserted here -->
        </div>

        <div class="league-table">
            <h2>⚔️ Daily League Rankings</h2>
            <div id="league-rows">
                <!-- League rows will be inserted here -->
            </div>
        </div>

        <div class="control-panel">
            <h3>🎮 Master Controls</h3>
            <button class="control-btn" onclick="manualSettle()">📊 Daily Settlement</button>
            <button class="control-btn secondary" onclick="reinvest()">💰 Reinvest</button>
            <button class="control-btn secondary" onclick="withdraw()">🏦 Withdraw</button>
            <button class="control-btn secondary" onclick="refreshData()">🔄 Refresh</button>
        </div>

        <script>
            let ws = new WebSocket(`wss://${window.location.host}/ws`);

            ws.onmessage = function(event) {
                const data = JSON.parse(event.data);
                updateDashboard(data);
            };

            function updateDashboard(data) {
                // Update vault summary
                document.getElementById('total-profit').textContent =
                    '$' + data.vault.total_profit_usd.toFixed(2);
                document.getElementById('today-pnl').textContent =
                    '$' + data.vault.today_profit_usd.toFixed(2);

                if (data.league.length > 0) {
                    document.getElementById('best-bot').textContent = data.league[0].bot_name;
                }

                // Update bot cards
                const botGrid = document.getElementById('bot-grid');
                botGrid.innerHTML = data.bots.map(bot => `
                    <div class="bot-card ${bot.tier.name.toLowerCase()}">
                        <div class="bot-header">
                            <span class="bot-name">${bot.bot_name}</span>
                            <span class="bot-tier">${bot.tier.name}</span>
                        </div>
                        <div>Level ${bot.level.current}</div>
                        <div class="hp-bar">
                            <div class="hp-fill ${bot.hp.status}" style="width: ${bot.hp.pct}%"></div>
                            <div class="bar-label">HP ${bot.hp.current}/${bot.hp.max}</div>
                        </div>
                        <div class="exp-bar">
                            <div class="exp-fill" style="width: ${bot.level.progress_pct}%"></div>
                            <div class="bar-label">EXP ${bot.level.progress_pct.toFixed(1)}%</div>
                        </div>
                        <div class="bot-stats">
                            <div class="stat-item">
                                <div class="stat-label">Trades</div>
                                <div class="stat-value">${bot.stats.total_trades}</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-label">Win Rate</div>
                                <div class="stat-value">${bot.stats.win_rate.toFixed(1)}%</div>
                            </div>
                            <div class="stat-item">
                                <div class="stat-label">Streak</div>
                                <div class="stat-value">${bot.stats.consecutive_wins}</div>
                            </div>
                        </div>
                    </div>
                `).join('');

                // Update league table
                const leagueRows = document.getElementById('league-rows');
                leagueRows.innerHTML = data.league.map(bot => `
                    <div class="league-row">
                        <span class="rank">${bot.rank_emoji}</span>
                        <div class="bot-info">
                            <div>${bot.bot_name}</div>
                            <div class="bot-tier-small">Lv.${bot.level.current} ${bot.tier.name}</div>
                        </div>
                        <span class="score">${bot.score.toFixed(1)}</span>
                    </div>
                `).join('');
            }

            function manualSettle() {
                fetch('/api/settle', {method: 'POST'}).then(r => r.json()).then(console.log);
            }

            function reinvest() {
                const botId = prompt('Enter Bot ID:');
                const amount = prompt('Enter Amount:');
                if (botId && amount) {
                    fetch('/api/reinvest', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({bot_id: botId, amount: parseFloat(amount)})
                    }).then(r => r.json()).then(console.log);
                }
            }

            function withdraw() {
                const botId = prompt('Enter Bot ID:');
                const amount = prompt('Enter Amount (% or $):');
                if (botId && amount) {
                    fetch('/api/withdraw', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({bot_id: botId, amount: amount})
                    }).then(r => r.json()).then(console.log);
                }
            }

            function refreshData() {
                ws.send(JSON.stringify({action: 'refresh'}));
            }
        </script>
    </body>
    </html>
    """


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 실시간 업데이트"""
    await websocket.accept()
    dashboard.active_connections.append(websocket)

    try:
        # 초기 데이터 전송
        data = {
            'timestamp': datetime.utcnow().isoformat(),
            'bots': await dashboard.get_bot_cards(),
            'league': await dashboard.get_league_table(),
            'vault': await dashboard.get_vault_summary(),
        }
        await websocket.send_json(data)

        while True:
            message = await websocket.receive_text()
            # 클라이언트 요청 처리
            if message == 'refresh':
                data = {
                    'timestamp': datetime.utcnow().isoformat(),
                    'bots': await dashboard.get_bot_cards(),
                    'league': await dashboard.get_league_table(),
                    'vault': await dashboard.get_vault_summary(),
                }
                await websocket.send_json(data)

    except WebSocketDisconnect:
        dashboard.active_connections.remove(websocket)


@app.post("/api/settle")
async def api_settle():
    """수동 정산 API"""
    result = await dashboard.settlement_system.manual_settlement()
    return result


@app.post("/api/reinvest")
async def api_reinvest(data: dict):
    """재투자 API (사용자 권한)"""
    bot_id = data.get('bot_id')
    amount = data.get('amount')

    success = await dashboard.vault_manager.reinvest_to_bot(bot_id, amount)
    return {'success': success, 'bot_id': bot_id, 'amount': amount}


@app.post("/api/withdraw")
async def api_withdraw(data: dict):
    """출금 API (마스터 금고로)"""
    bot_id = data.get('bot_id')
    amount = data.get('amount')  # 금액 또는 퍼센트

    # TODO: 실제 출금 로직
    return {'success': True, 'bot_id': bot_id, 'amount': amount, 'status': 'pending'}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

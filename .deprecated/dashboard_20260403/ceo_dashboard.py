"""
CEO Dashboard - OZ_A2M 완결판 대시보드
STEP 15: CEO 대시보드 완결판

기능:
- 안정봇 패널 (다크 테마)
- 도파민봇 패널 (네온 테마)
- WebSocket 실시간 업데이트
- 킬스위치
- Telegram 알림 토글
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger
from lib.messaging.mqtt_client import MQTTClient, MQTTConfig
from lib.messaging.event_bus import EventBus, get_event_bus

logger = get_logger(__name__)


class BotCategory(str, Enum):
    """봇 카테고리"""
    STABLE = "stable"      # 안정봇
    DOPAMINE = "dopamine"  # 도파민봇


class DashboardTheme(str, Enum):
    """대시보드 테마"""
    DARK = "dark"
    NEON = "neon"


class CEODashboard:
    """
    CEO 통합 대시보드

    섹션:
    1. 안정봇 패널 - Binance/Bybit 정형 거래 봇
    2. 도파민봇 패널 - Pump.fun/Polymarket 투기 봇
    """

    # 테마 색상
    COLORS = {
        "dark": {
            "bg": "#1a1a2e",
            "card_bg": "#16213e",
            "text": "#ffffff",
            "success": "#00b894",
            "warning": "#fdcb6e",
            "danger": "#d63031",
            "info": "#74b9ff"
        },
        "neon": {
            "bg": "#0a0a0f",
            "pink": "#FF006E",
            "purple": "#8338EC",
            "yellow": "#FFBE0B",
            "cyan": "#00F5FF",
            "glow": "0 0 10px"
        }
    }

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883
    ):
        self.host = host
        self.port = port

        # 상태
        self.bots: Dict[str, Dict] = {}
        self.system_stats = {
            "cpu": 0.0,
            "memory": 0.0,
            "uptime": 0
        }
        self.total_pnl = 0.0
        self.kill_switch_active = False
        self.telegram_enabled = True

        # MQTT
        mqtt_config = MQTTConfig(
            host=mqtt_host,
            port=mqtt_port,
            client_id="ceo_dashboard"
        )
        self.mqtt = MQTTClient(config=mqtt_config)

        # EventBus
        self.event_bus: Optional[EventBus] = None

        # WebSocket 클라이언트 관리
        self.ws_clients: set = set()

        logger.info(f"CEO Dashboard initialized on {host}:{port}")

    async def initialize(self):
        """대시보드 초기화"""
        try:
            self.event_bus = get_event_bus()
            await self.event_bus.connect()
            logger.info("EventBus connected")

            # 봇 상태 구독
            await self.event_bus.subscribe("bots/status", self._on_bot_status)
            await self.event_bus.subscribe("bots/trade", self._on_bot_trade)
            await self.event_bus.subscribe("system/metrics", self._on_system_metrics)

        except Exception as e:
            logger.warning(f"EventBus connection failed: {e}")

        # 초기 봇 상태 설정
        self._initialize_bot_status()

    def _initialize_bot_status(self):
        """초기 봇 상태 설정"""
        stable_bots = [
            ("grid_binance_001", "Binance Grid", "binance", "BTC/USDT", 11.0),
            ("dca_binance_001", "Binance DCA", "binance", "BTC/USDT", 14.0),
            ("triarb_binance_001", "Triangular Arb", "binance", "BTC/ETH/BNB", 20.0),
            ("funding_binance_bybit_001", "Funding Rate", "multi", "Multi", 20.0),
            ("scalper_bybit_001", "Bybit Scalping", "bybit", "SOL/USDT", 20.0),
            ("hyperliquid_mm_001", "Hyperliquid MM", "hyperliquid", "SOL-PERP", 20.0),
            ("ibkr_forecast_001", "IBKR Forecast", "ibkr", "AAPL/MSFT", 10.0),
        ]

        dopamine_bots = [
            ("polymarket_ai_001", "Polymarket AI", "polymarket", "Multi", 20.0),
            ("pump_sniper_001", "Pump.fun Sniper", "solana", "New Tokens", 0.1),
            ("gmgn_copy_001", "GMGN Copy", "solana", "Smart Money", 0.1),
        ]

        for bot_id, name, exchange, symbol, capital in stable_bots:
            self.bots[bot_id] = {
                "id": bot_id,
                "name": name,
                "category": BotCategory.STABLE,
                "exchange": exchange,
                "symbol": symbol,
                "capital": capital,
                "status": "running",
                "pnl": 0.0,
                "trades": 0,
                "win_rate": 0.0
            }

        for bot_id, name, exchange, symbol, capital in dopamine_bots:
            self.bots[bot_id] = {
                "id": bot_id,
                "name": name,
                "category": BotCategory.DOPAMINE,
                "exchange": exchange,
                "symbol": symbol,
                "capital": capital,
                "status": "running",
                "pnl": 0.0,
                "trades": 0,
                "win_rate": 0.0
            }

    async def _on_bot_status(self, message):
        """봇 상태 업데이트 처리"""
        try:
            data = json.loads(message.payload.decode())
            bot_id = data.get("bot_id")

            if bot_id in self.bots:
                self.bots[bot_id].update({
                    "status": data.get("status", "unknown"),
                    "pnl": data.get("pnl", 0.0),
                    "trades": data.get("total_trades", 0),
                    "win_rate": data.get("win_rate", 0.0)
                })

                # 총 PnL 업데이트
                self._update_total_pnl()

        except Exception as e:
            logger.error(f"Error processing bot status: {e}")

    async def _on_bot_trade(self, message):
        """봇 거래 업데이트 처리"""
        try:
            data = json.loads(message.payload.decode())
            # 실시간 거래 알림 처리
            logger.info(f"Trade update: {data}")

        except Exception as e:
            logger.error(f"Error processing trade: {e}")

    async def _on_system_metrics(self, message):
        """시스템 메트릭 업데이트"""
        try:
            data = json.loads(message.payload.decode())
            self.system_stats.update({
                "cpu": data.get("cpu", 0),
                "memory": data.get("memory", 0),
                "uptime": data.get("uptime", 0)
            })

        except Exception as e:
            logger.error(f"Error processing metrics: {e}")

    def _update_total_pnl(self):
        """총 PnL 업데이트"""
        self.total_pnl = sum(bot.get("pnl", 0) for bot in self.bots.values())

    def get_stable_bots(self) -> List[Dict]:
        """안정봇 목록 반환"""
        return [
            bot for bot in self.bots.values()
            if bot["category"] == BotCategory.STABLE
        ]

    def get_dopamine_bots(self) -> List[Dict]:
        """도파민봇 목록 반환"""
        return [
            bot for bot in self.bots.values()
            if bot["category"] == BotCategory.DOPAMINE
        ]

    def get_dashboard_data(self) -> Dict[str, Any]:
        """대시보드 데이터 반환"""
        stable = self.get_stable_bots()
        dopamine = self.get_dopamine_bots()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "summary": {
                "total_bots": len(self.bots),
                "stable_bots": len(stable),
                "dopamine_bots": len(dopamine),
                "running_bots": sum(1 for b in self.bots.values() if b["status"] == "running"),
                "error_bots": sum(1 for b in self.bots.values() if b["status"] == "error"),
                "total_pnl": self.total_pnl,
                "kill_switch_active": self.kill_switch_active,
                "telegram_enabled": self.telegram_enabled
            },
            "system": self.system_stats,
            "stable_bots": stable,
            "dopamine_bots": dopamine,
            "colors": self.COLORS
        }

    async def activate_kill_switch(self):
        """킬스위치 활성화"""
        logger.critical("CEO Dashboard: Kill switch activated!")
        self.kill_switch_active = True

        # 모든 봇 중지 명령 발행
        if self.event_bus:
            await self.event_bus.emit("command/kill_switch", {
                "timestamp": datetime.utcnow().isoformat(),
                "source": "ceo_dashboard"
            })

    async def toggle_telegram(self, enabled: bool):
        """Telegram 알림 토글"""
        self.telegram_enabled = enabled
        logger.info(f"Telegram notifications {'enabled' if enabled else 'disabled'}")

    def generate_html(self) -> str:
        """HTML 대시보드 생성"""
        data = self.get_dashboard_data()

        return f"""
<!DOCTYPE html>
<html>
<head>
    <title>OZ_A2M CEO Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: {self.COLORS["dark"]["bg"]};
            color: {self.COLORS["dark"]["text"]};
            min-height: 100vh;
        }}

        .header {{
            background: {self.COLORS["dark"]["card_bg"]};
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid {self.COLORS["dark"]["info"]};
        }}

        .header h1 {{
            color: {self.COLORS["neon"]["pink"]};
            text-shadow: {self.COLORS["neon"]["glow"]} {self.COLORS["neon"]["pink"]};
        }}

        .summary {{
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }}

        .summary-card {{
            background: {self.COLORS["dark"]["card_bg"]};
            padding: 15px 25px;
            border-radius: 10px;
            min-width: 150px;
        }}

        .summary-card .value {{
            font-size: 24px;
            font-weight: bold;
            color: {self.COLORS["dark"]["success"]};
        }}

        .container {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            padding: 20px;
        }}

        @media (max-width: 768px) {{
            .container {{
                grid-template-columns: 1fr;
            }}
        }}

        .panel {{
            border-radius: 15px;
            padding: 20px;
        }}

        .stable-panel {{
            background: {self.COLORS["dark"]["card_bg"]};
            border: 1px solid {self.COLORS["dark"]["info"]};
        }}

        .dopamine-panel {{
            background: {self.COLORS["neon"]["bg"]};
            border: 2px solid {self.COLORS["neon"]["pink"]};
            box-shadow: {self.COLORS["neon"]["glow"]} {self.COLORS["neon"]["pink"]};
        }}

        .panel h2 {{
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        .dopamine-panel h2 {{
            color: {self.COLORS["neon"]["pink"]};
            text-shadow: {self.COLORS["neon"]["glow"]} {self.COLORS["neon"]["pink"]};
        }}

        .bot-card {{
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .bot-card.running {{
            border-left: 4px solid {self.COLORS["dark"]["success"]};
        }}

        .bot-card.error {{
            border-left: 4px solid {self.COLORS["dark"]["danger"]};
        }}

        .bot-info h4 {{
            margin-bottom: 5px;
        }}

        .bot-meta {{
            font-size: 12px;
            opacity: 0.7;
        }}

        .bot-pnl {{
            text-align: right;
        }}

        .pnl-positive {{
            color: {self.COLORS["dark"]["success"]};
        }}

        .pnl-negative {{
            color: {self.COLORS["dark"]["danger"]};
        }}

        .controls {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            display: flex;
            gap: 10px;
        }}

        .btn {{
            padding: 15px 30px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.3s;
        }}

        .btn-kill {{
            background: {self.COLORS["dark"]["danger"]};
            color: white;
        }}

        .btn-kill:hover {{
            background: #ff3333;
            transform: scale(1.05);
        }}

        .btn-telegram {{
            background: {self.COLORS["dark"]["info"]};
            color: white;
        }}

        .status-indicator {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 5px;
        }}

        .status-running {{
            background: {self.COLORS["dark"]["success"]};
            box-shadow: 0 0 5px {self.COLORS["dark"]["success"]};
        }}

        .status-error {{
            background: {self.COLORS["dark"]["danger"]};
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🎯 OZ_A2M CEO Dashboard</h1>
        <div class="summary">
            <div class="summary-card">
                <div>Total PnL</div>
                <div class="value">${self.total_pnl:+.2f}</div>
            </div>
            <div class="summary-card">
                <div>Running Bots</div>
                <div class="value">{data['summary']['running_bots']}/{data['summary']['total_bots']}</div>
            </div>
            <div class="summary-card">
                <div>CPU / RAM</div>
                <div class="value">{self.system_stats['cpu']:.1f}% / {self.system_stats['memory']:.1f}%</div>
            </div>
        </div>
    </div>

    <div class="container">
        <div class="panel stable-panel">
            <h2>📊 안정봇 (Stable Bots)</h2>
            {self._generate_bot_cards(data['stable_bots'])}
        </div>

        <div class="panel dopamine-panel">
            <h2>🚀 도파민봇 (Dopamine Bots)</h2>
            {self._generate_bot_cards(data['dopamine_bots'], neon=True)}
        </div>
    </div>

    <div class="controls">
        <button class="btn btn-telegram" onclick="toggleTelegram()">
            {'🔔' if self.telegram_enabled else '🔕'} Telegram
        </button>
        <button class="btn btn-kill" onclick="activateKillSwitch()">
            🚨 KILL SWITCH
        </button>
    </div>

    <script>
        function activateKillSwitch() {{
            if (confirm('⚠️ 정말 모든 봇을 중지하시겠습니까?')) {{
                fetch('/api/kill-switch', {{method: 'POST'}});
                alert('🚨 킬스위치 활성화됨');
            }}
        }}

        function toggleTelegram() {{
            fetch('/api/toggle-telegram', {{method: 'POST'}});
            location.reload();
        }}

        // WebSocket 연결
        const ws = new WebSocket('ws://' + window.location.host + '/ws');
        ws.onmessage = function(event) {{
            const data = JSON.parse(event.data);
            console.log('Update:', data);
        }};
    </script>
</body>
</html>
"""

    def _generate_bot_cards(self, bots: List[Dict], neon: bool = False) -> str:
        """봇 카드 HTML 생성"""
        cards = []
        for bot in bots:
            status_class = "running" if bot["status"] == "running" else "error"
            pnl_class = "pnl-positive" if bot.get("pnl", 0) >= 0 else "pnl-negative"
            pnl_sign = "+" if bot.get("pnl", 0) >= 0 else ""

            cards.append(f"""
                <div class="bot-card {status_class}">
                    <div class="bot-info">
                        <h4>{bot['name']}</h4>
                        <div class="bot-meta">
                            <span class="status-indicator status-{status_class}"></span>
                            {bot['exchange']} | {bot['symbol']} | ${bot['capital']}
                        </div>
                    </div>
                    <div class="bot-pnl">
                        <div class="{pnl_class}">{pnl_sign}${bot.get('pnl', 0):.2f}</div>
                        <div class="bot-meta">{bot.get('trades', 0)} trades</div>
                    </div>
                </div>
            """)
        return "\n".join(cards)

    async def run(self):
        """대시보드 실행"""
        await self.initialize()
        logger.info(f"CEO Dashboard running on http://{self.host}:{self.port}")


async def main():
    """단독 실행용"""
    dashboard = CEODashboard()
    await dashboard.run()

    # 테스트 데이터
    dashboard.total_pnl = 150.50

    # HTML 출력
    html = dashboard.generate_html()
    print("Dashboard HTML generated")
    print(f"Total bots: {len(dashboard.bots)}")
    print(f"Stable bots: {len(dashboard.get_stable_bots())}")
    print(f"Dopamine bots: {len(dashboard.get_dopamine_bots())}")


if __name__ == "__main__":
    asyncio.run(main())

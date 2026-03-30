"""
OZ_A2M TUI Dashboard - Terminal User Interface
Pi-Mono TUI 패키지 기반 CEO 대시보드 CLI 버전

기능:
- 실시간 봇 상태 모니터링
- 수익 현황 표시
- 시스템 메트릭스 모니터링
- 간단한 봇 제어
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# 프로젝트 경로 설정
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger

logger = get_logger(__name__)

# Pi-Mono TUI 사용 시도
try:
    from pi.tui import TerminalUI, Panel, Text, Table, Row
    PI_MONO_AVAILABLE = True
except ImportError:
    PI_MONO_AVAILABLE = False
    logger.warning("pi-mono tui not available, using fallback")

# Fallback: Rich 라이브러리 사용
try:
    from rich.console import Console
    from rich.table import Table as RichTable
    from rich.panel import Panel as RichPanel
    from rich.layout import Layout
    from rich.live import Live
    from rich.text import Text as RichText
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    logger.warning("rich not available, using basic output")


class OZDashboard:
    """
    OZ_A2M TUI 대시보드

    Pi-Mono TUI 또는 Rich 라이브러리를 사용하여
    터미널에서 실시간으로 봇 상태를 모니터링
    """

    def __init__(self):
        self.bots: Dict[str, Dict] = {}
        self.system_metrics: Dict[str, float] = {}
        self.total_pnl: float = 0.0
        self.running = False

        if PI_MONO_AVAILABLE:
            self.ui = TerminalUI()
            self._mode = 'pi-mono'
        elif RICH_AVAILABLE:
            self.console = Console()
            self._mode = 'rich'
        else:
            self._mode = 'basic'

    async def fetch_bot_status(self) -> Dict[str, Dict]:
        """봇 상태 조회"""
        try:
            # FastAPI 서버에 API 요청
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get('http://localhost:8082/api/bots') as resp:
                    if resp.status == 200:
                        bots_data = await resp.json()
                        return {bot['bot_id']: bot for bot in bots_data if isinstance(bots_data, list)}
        except Exception as e:
            logger.error(f"Failed to fetch bot status: {e}")

        # Fallback: 직접 초기화
        return await self._init_bots_directly()

    async def _init_bots_directly(self) -> Dict[str, Dict]:
        """직접 봇 초기화 (API 서버 없을 시)"""
        try:
            from department_7.src.bot.grid_bot import BinanceGridBot
            from department_7.src.bot.dca_bot import BinanceDCABot
            from department_7.src.bot.scalper import BybitScalpingBot
            from department_7.src.bot.polymarket_bot import PolymarketAIBot
            from department_7.src.bot.pump_sniper_bot import PumpSniperBot

            bots = {
                'grid_binance_001': BinanceGridBot(capital=11),
                'dca_binance_001': BinanceDCABot(capital=14),
                'scalper_bybit_001': BybitScalpingBot(capital=20),
                'polymarket_ai_001': PolymarketAIBot(capital=19.85, mock_mode=False),
                'pump_sniper_001': PumpSniperBot(capital_sol=0.1, mock_mode=False),
            }

            return {
                bid: {
                    'bot_id': bid,
                    'status': 'idle',
                    'type': 'stable' if 'pump' not in bid else 'dopamine',
                    **bot.get_status()
                }
                for bid, bot in bots.items()
            }
        except Exception as e:
            logger.error(f"Direct bot init failed: {e}")
            return {}

    async def fetch_system_metrics(self) -> Dict[str, float]:
        """시스템 메트릭스 조회"""
        try:
            import psutil
            return {
                'cpu': psutil.cpu_percent(),
                'memory': psutil.virtual_memory().percent,
                'disk': psutil.disk_usage('/').percent,
            }
        except Exception as e:
            logger.error(f"Failed to fetch metrics: {e}")
            return {'cpu': 0, 'memory': 0, 'disk': 0}

    def _create_bot_table(self) -> str:
        """봇 상태 테이블 생성"""
        if not self.bots:
            return "No bots available"

        lines = ["\n" + "="*80]
        lines.append(f"{'ID':<20} {'Status':<10} {'Type':<10} {'PnL':<15} {'Trades':<10}")
        lines.append("-"*80)

        for bot_id, bot in self.bots.items():
            status = bot.get('status', 'unknown')
            bot_type = bot.get('type', 'unknown')
            pnl = bot.get('pnl', 0)
            trades = bot.get('trades', 0)

            status_icon = "🟢" if status in ['running', 'idle'] else "🔴"
            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"

            lines.append(f"{bot_id:<20} {status_icon} {status:<8} {bot_type:<10} {pnl_str:<15} {trades:<10}")

        lines.append("="*80)
        return "\n".join(lines)

    def _create_metrics_table(self) -> str:
        """시스템 메트릭스 테이블 생성"""
        lines = ["\n" + "="*40]
        lines.append(f"{'Metric':<15} {'Value':<10}")
        lines.append("-"*40)

        for metric, value in self.system_metrics.items():
            icon = "🟢" if value < 70 else ("🟡" if value < 85 else "🔴")
            lines.append(f"{metric.upper():<15} {icon} {value:.1f}%")

        lines.append("="*40)
        return "\n".join(lines)

    def _render_rich(self):
        """Rich 라이브러리로 렌더링"""
        # 봇 테이블
        bot_table = RichTable(title="Trading Bots", show_header=True)
        bot_table.add_column("Bot ID", style="cyan")
        bot_table.add_column("Status", style="green")
        bot_table.add_column("Type", style="yellow")
        bot_table.add_column("PnL", justify="right")
        bot_table.add_column("Trades", justify="right")

        for bot_id, bot in self.bots.items():
            status = bot.get('status', 'unknown')
            status_style = "green" if status in ['running', 'idle'] else "red"
            pnl = bot.get('pnl', 0)
            pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
            pnl_style = "green" if pnl >= 0 else "red"

            bot_table.add_row(
                bot_id,
                f"[{status_style}]{status}[/{status_style}]",
                bot.get('type', 'unknown'),
                f"[{pnl_style}]{pnl_str}[/{pnl_style}]",
                str(bot.get('trades', 0))
            )

        # 시스템 테이블
        sys_table = RichTable(title="System Metrics", show_header=True)
        sys_table.add_column("Metric", style="cyan")
        sys_table.add_column("Value", justify="right")

        for metric, value in self.system_metrics.items():
            color = "green" if value < 70 else ("yellow" if value < 85 else "red")
            sys_table.add_row(
                metric.upper(),
                f"[{color}]{value:.1f}%[/{color}]"
            )

        # 출력
        self.console.clear()
        self.console.print(RichPanel(bot_table, title="OZ_A2M Dashboard"))
        self.console.print(RichPanel(sys_table))
        self.console.print(f"\n[dim]Last update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]")
        self.console.print("[dim]Press Ctrl+C to exit[/dim]")

    def _render_basic(self):
        """기본 출력으로 렌더링"""
        import os
        os.system('clear' if os.name != 'nt' else 'cls')

        print("\n" + "="*80)
        print(" "*25 + "OZ_A2M CEO DASHBOARD (TUI)")
        print("="*80)

        print(self._create_bot_table())
        print(self._create_metrics_table())

        print(f"\nLast update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("Press Ctrl+C to exit")

    async def _update_loop(self):
        """업데이트 루프"""
        while self.running:
            try:
                self.bots = await self.fetch_bot_status()
                self.system_metrics = await self.fetch_system_metrics()

                if self._mode == 'rich':
                    self._render_rich()
                else:
                    self._render_basic()

                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Update loop error: {e}")
                await asyncio.sleep(5)

    async def start(self):
        """TUI 대시보드 시작"""
        self.running = True
        logger.info(f"Starting TUI Dashboard (mode: {self._mode})")

        try:
            await self._update_loop()
        except KeyboardInterrupt:
            self.running = False
            print("\n\nTUI Dashboard stopped.")

    async def stop(self):
        """TUI 대시보드 중지"""
        self.running = False
        logger.info("TUI Dashboard stopped")


async def main():
    """메인 실행"""
    dashboard = OZDashboard()
    await dashboard.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTUI Dashboard stopped.")

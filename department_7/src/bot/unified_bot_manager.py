"""
UnifiedBotManager - 통합 봇 관리자
STEP 9~17: OZ_A2M 완결판

모든 트레이딩 봇을 중앙에서 관리:
- 봇 등록/시작/중지
- 상태 모니터링
- PnL 집계
- 킬스위치
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import logging

from .scalper import BybitScalpingBot, ScalpingBotAdapter

logger = logging.getLogger(__name__)


class BotType(str, Enum):
    """봇 유형"""
    SCALPING = "scalping"
    GRID = "grid"
    DCA = "dca"
    FUNDING_RATE = "funding_rate"
    TRIANGULAR_ARB = "triangular_arb"
    MARKET_MAKER = "market_maker"
    FORECAST = "forecast"
    POLYMARKET = "polymarket"
    PUMP_SNIPE = "pump_snipe"
    COPY_TRADE = "copy_trade"


class BotStatus(str, Enum):
    """봇 상태"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class BotConfig:
    """봇 설정"""
    bot_id: str
    bot_type: BotType
    exchange: str
    symbol: str
    capital: float
    sandbox: bool = True
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BotInfo:
    """봇 정보"""
    bot_id: str
    bot_type: BotType
    status: BotStatus
    exchange: str
    symbol: str
    capital: float
    current_pnl: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)
    error_message: Optional[str] = None


class UnifiedBotManager:
    """
    통합 봇 관리자

    모든 트레이딩 봇을 중앙에서 관리하는 싱글톤 클래스
    """

    _instance: Optional['UnifiedBotManager'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._bots: Dict[str, Any] = {}  # 봇 인스턴스
        self._bot_configs: Dict[str, BotConfig] = {}  # 봇 설정
        self._bot_infos: Dict[str, BotInfo] = {}  # 봇 상태 정보
        self._bot_tasks: Dict[str, asyncio.Task] = {}  # 봇 태스크
        self._lock = asyncio.Lock()
        self._callbacks: List[Callable] = []
        self._kill_switch_active = False

        logger.info("UnifiedBotManager initialized")

    def register_bot(self, config: BotConfig, bot_instance: Any) -> bool:
        """
        봇 등록

        Args:
            config: 봇 설정
            bot_instance: 봇 인스턴스

        Returns:
            등록 성공 여부
        """
        bot_id = config.bot_id

        if bot_id in self._bots:
            logger.warning(f"Bot {bot_id} already registered")
            return False

        self._bot_configs[bot_id] = config
        self._bots[bot_id] = bot_instance
        self._bot_infos[bot_id] = BotInfo(
            bot_id=bot_id,
            bot_type=config.bot_type,
            status=BotStatus.STOPPED,
            exchange=config.exchange,
            symbol=config.symbol,
            capital=config.capital
        )

        logger.info(f"Bot {bot_id} ({config.bot_type.value}) registered")
        return True

    async def start_bot(self, bot_id: str) -> bool:
        """
        봇 시작

        Args:
            bot_id: 봇 ID

        Returns:
            시작 성공 여부
        """
        if bot_id not in self._bots:
            logger.error(f"Bot {bot_id} not found")
            return False

        if self._kill_switch_active:
            logger.warning(f"Kill switch active, cannot start bot {bot_id}")
            return False

        async with self._lock:
            if bot_id in self._bot_tasks and not self._bot_tasks[bot_id].done():
                logger.warning(f"Bot {bot_id} already running")
                return False

            bot = self._bots[bot_id]
            self._bot_infos[bot_id].status = BotStatus.STARTING

            try:
                # 봇 태스크 생성
                task = asyncio.create_task(self._run_bot(bot_id, bot))
                self._bot_tasks[bot_id] = task

                logger.info(f"Bot {bot_id} started")
                return True

            except Exception as e:
                logger.error(f"Failed to start bot {bot_id}: {e}")
                self._bot_infos[bot_id].status = BotStatus.ERROR
                self._bot_infos[bot_id].error_message = str(e)
                return False

    async def _run_bot(self, bot_id: str, bot: Any):
        """봇 실행 래퍼"""
        self._bot_infos[bot_id].status = BotStatus.RUNNING
        self._notify_update(bot_id)

        try:
            if hasattr(bot, 'run'):
                await bot.run()
            elif hasattr(bot, 'start'):
                await bot.start()
            else:
                raise ValueError(f"Bot {bot_id} has no run or start method")

        except asyncio.CancelledError:
            logger.info(f"Bot {bot_id} cancelled")
            self._bot_infos[bot_id].status = BotStatus.STOPPED

        except Exception as e:
            logger.error(f"Bot {bot_id} error: {e}")
            self._bot_infos[bot_id].status = BotStatus.ERROR
            self._bot_infos[bot_id].error_message = str(e)

        finally:
            self._bot_infos[bot_id].last_updated = datetime.utcnow()
            self._notify_update(bot_id)

    async def stop_bot(self, bot_id: str) -> bool:
        """
        봇 중지

        Args:
            bot_id: 봇 ID

        Returns:
            중지 성공 여부
        """
        if bot_id not in self._bots:
            logger.error(f"Bot {bot_id} not found")
            return False

        async with self._lock:
            if bot_id in self._bot_tasks:
                task = self._bot_tasks[bot_id]
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=10.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"Bot {bot_id} stop timeout, forcing cancel")
                    except asyncio.CancelledError:
                        pass

                del self._bot_tasks[bot_id]

            # 봇 인스턴스 중지
            bot = self._bots[bot_id]
            if hasattr(bot, 'stop'):
                try:
                    await bot.stop()
                except Exception as e:
                    logger.error(f"Error stopping bot {bot_id}: {e}")

            self._bot_infos[bot_id].status = BotStatus.STOPPED
            self._bot_infos[bot_id].last_updated = datetime.utcnow()
            self._notify_update(bot_id)

            logger.info(f"Bot {bot_id} stopped")
            return True

    async def stop_all_bots(self):
        """모든 봇 중지"""
        logger.info("Stopping all bots...")
        tasks = []
        for bot_id in list(self._bots.keys()):
            tasks.append(self.stop_bot(bot_id))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("All bots stopped")

    async def kill_switch(self):
        """
        킬스위치 - 모든 봇 즉시 중지

        모든 봇을 즉시 중지하고 새로운 봇 시작을 차단합니다.
        """
        logger.critical("KILL SWITCH ACTIVATED")
        self._kill_switch_active = True

        # 모든 봇 중지
        await self.stop_all_bots()

        # Telegram 알림 발송
        await self._send_kill_switch_alert()

        logger.critical("All bots stopped by kill switch")

    def reset_kill_switch(self):
        """킬스위치 해제"""
        logger.info("Kill switch reset")
        self._kill_switch_active = False

    async def _send_kill_switch_alert(self):
        """킬스위치 알림 발송"""
        try:
            import os
            import aiohttp

            bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")

            if not bot_token or not chat_id:
                return

            message = (
                "🚨🚨🚨 KILL SWITCH ACTIVATED 🚨🚨🚨\n\n"
                f"시간: {datetime.utcnow().isoformat()}\n"
                f"모든 봇이 즉시 중지되었습니다.\n\n"
                "수동 확인이 필요합니다."
            )

            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        logger.warning(f"Kill switch alert failed: {resp.status}")
        except Exception as e:
            logger.error(f"Failed to send kill switch alert: {e}")

    def get_bot_status(self, bot_id: str) -> Optional[BotInfo]:
        """특정 봇 상태 조회"""
        return self._bot_infos.get(bot_id)

    def get_all_status(self) -> List[BotInfo]:
        """모든 봇 상태 조회"""
        return list(self._bot_infos.values())

    def get_summary(self) -> Dict[str, Any]:
        """전체 봇 요약 정보"""
        total_bots = len(self._bots)
        running_bots = sum(1 for info in self._bot_infos.values() if info.status == BotStatus.RUNNING)
        error_bots = sum(1 for info in self._bot_infos.values() if info.status == BotStatus.ERROR)
        total_pnl = sum(info.current_pnl for info in self._bot_infos.values())
        total_capital = sum(info.capital for info in self._bot_infos.values())

        return {
            "total_bots": total_bots,
            "running_bots": running_bots,
            "error_bots": error_bots,
            "kill_switch_active": self._kill_switch_active,
            "total_pnl": total_pnl,
            "total_capital": total_capital,
            "total_return_pct": (total_pnl / total_capital * 100) if total_capital > 0 else 0,
            "bots": [
                {
                    "bot_id": info.bot_id,
                    "bot_type": info.bot_type.value,
                    "status": info.status.value,
                    "exchange": info.exchange,
                    "symbol": info.symbol,
                    "capital": info.capital,
                    "current_pnl": info.current_pnl,
                    "win_rate": info.win_rate,
                    "total_trades": info.total_trades
                }
                for info in self._bot_infos.values()
            ]
        }

    def update_bot_pnl(self, bot_id: str, pnl: float, trades: int = 0, win_rate: float = 0.0):
        """봇 PnL 업데이트"""
        if bot_id in self._bot_infos:
            self._bot_infos[bot_id].current_pnl = pnl
            if trades > 0:
                self._bot_infos[bot_id].total_trades = trades
            if win_rate > 0:
                self._bot_infos[bot_id].win_rate = win_rate
            self._bot_infos[bot_id].last_updated = datetime.utcnow()
            self._notify_update(bot_id)

    def on_status_update(self, callback: Callable[[str, BotInfo], None]):
        """상태 업데이트 콜백 등록"""
        self._callbacks.append(callback)

    def _notify_update(self, bot_id: str):
        """상태 업데이트 알림"""
        info = self._bot_infos.get(bot_id)
        if info:
            for callback in self._callbacks:
                try:
                    callback(bot_id, info)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

    async def refresh_all_status(self):
        """모든 봇 상태 새로고침"""
        for bot_id, bot in self._bots.items():
            try:
                if hasattr(bot, 'get_status'):
                    status = bot.get_status()
                    self._bot_infos[bot_id].current_pnl = status.get('daily_pnl', 0.0)
                    self._bot_infos[bot_id].total_trades = status.get('total_trades', 0)
                    win = status.get('winning_trades', 0)
                    total = status.get('total_trades', 1)
                    self._bot_infos[bot_id].win_rate = (win / total * 100) if total > 0 else 0
                    self._bot_infos[bot_id].last_updated = datetime.utcnow()
            except Exception as e:
                logger.error(f"Failed to refresh status for {bot_id}: {e}")


# 전역 인스턴스
_manager: Optional[UnifiedBotManager] = None


def get_bot_manager() -> UnifiedBotManager:
    """전역 BotManager 인스턴스 반환"""
    global _manager
    if _manager is None:
        _manager = UnifiedBotManager()
    return _manager


def reset_bot_manager():
    """BotManager 초기화"""
    global _manager
    _manager = None


# Bybit 스캘핑봇 생성 및 등록 헬퍼
async def create_and_register_scalper_bot(
    bot_id: str = "scalper_bybit_001",
    capital: float = 20.0,
    sandbox: bool = False
) -> Optional[BybitScalpingBot]:
    """
    Bybit 스캘핑봇 생성 및 등록

    Args:
        bot_id: 봇 ID
        capital: 자본금
        sandbox: 샌드박스 모드

    Returns:
        생성된 봇 인스턴스
    """
    try:
        # 봇 인스턴스 생성
        bot = BybitScalpingBot(
            bot_id=bot_id,
            symbol="SOL/USDT",
            exchange_id="bybit",
            sandbox=sandbox,
            capital=capital,
            telegram_alerts=True
        )

        # 설정 생성
        config = BotConfig(
            bot_id=bot_id,
            bot_type=BotType.SCALPING,
            exchange="bybit",
            symbol="SOL/USDT",
            capital=capital,
            sandbox=sandbox
        )

        # 매니저에 등록
        manager = get_bot_manager()
        manager.register_bot(config, bot)

        logger.info(f"Scalper bot {bot_id} created and registered")
        return bot

    except Exception as e:
        logger.error(f"Failed to create scalper bot: {e}")
        return None


# Binance Grid Bot 생성 및 등록 헬퍼
async def create_and_register_grid_bot(
    bot_id: str = "grid_binance_001",
    capital: float = 11.0,
    grid_count: int = 20,
    grid_spacing_pct: float = 0.005,
    sandbox: bool = False
) -> Optional[Any]:
    """
    Binance Grid Bot 생성 및 등록

    Args:
        bot_id: 봇 ID
        capital: 자본금
        grid_count: 그리드 개수
        grid_spacing_pct: 그리드 간격 (%)
        sandbox: 샌드박스 모드

    Returns:
        생성된 봇 인스턴스
    """
    try:
        from .grid_bot import BinanceGridBot

        bot = BinanceGridBot(
            bot_id=bot_id,
            symbol="BTC/USDT",
            exchange_id="binance",
            capital=capital,
            grid_count=grid_count,
            grid_spacing_pct=grid_spacing_pct,
            sandbox=sandbox,
            telegram_alerts=True
        )

        config = BotConfig(
            bot_id=bot_id,
            bot_type=BotType.GRID,
            exchange="binance",
            symbol="BTC/USDT",
            capital=capital,
            sandbox=sandbox
        )

        manager = get_bot_manager()
        manager.register_bot(config, bot)

        logger.info(f"Grid bot {bot_id} created and registered")
        return bot

    except Exception as e:
        logger.error(f"Failed to create grid bot: {e}")
        return None


# Binance DCA Bot 생성 및 등록 헬퍼
async def create_and_register_dca_bot(
    bot_id: str = "dca_binance_001",
    capital: float = 14.0,
    dca_drop_pct: float = 0.02,
    take_profit_pct: float = 0.03,
    sandbox: bool = False
) -> Optional[Any]:
    """
    Binance DCA Bot 생성 및 등록

    Args:
        bot_id: 봇 ID
        capital: 자본금
        dca_drop_pct: DCA 매수 하띹 (%)
        take_profit_pct: 익절 상승률 (%)
        sandbox: 샌드박스 모드

    Returns:
        생성된 봇 인스턴스
    """
    try:
        from .dca_bot import BinanceDCABot

        bot = BinanceDCABot(
            bot_id=bot_id,
            symbol="BTC/USDT",
            exchange_id="binance",
            capital=capital,
            dca_drop_pct=dca_drop_pct,
            take_profit_pct=take_profit_pct,
            sandbox=sandbox,
            telegram_alerts=True
        )

        config = BotConfig(
            bot_id=bot_id,
            bot_type=BotType.DCA,
            exchange="binance",
            symbol="BTC/USDT",
            capital=capital,
            sandbox=sandbox
        )

        manager = get_bot_manager()
        manager.register_bot(config, bot)

        logger.info(f"DCA bot {bot_id} created and registered")
        return bot

    except Exception as e:
        logger.error(f"Failed to create DCA bot: {e}")
        return None


async def main():
    """테스트용 메인 함수"""
    manager = get_bot_manager()

    # Bybit 스캘핑봇 생성 및 등록
    bot = await create_and_register_scalper_bot(
        bot_id="scalper_bybit_001",
        capital=20.0,
        sandbox=False
    )

    if bot:
        print(f"✅ Scalper bot registered: {bot.bot_id}")
        print(f"   Symbol: {bot.symbol}")
        print(f"   Capital: ${bot.capital}")
        print(f"   Sandbox: {bot.sandbox}")

        # 상태 요약 출력
        summary = manager.get_summary()
        print(f"\n📊 Manager Summary:")
        print(f"   Total bots: {summary['total_bots']}")
        print(f"   Kill switch: {'ACTIVE' if summary['kill_switch_active'] else 'inactive'}")


if __name__ == "__main__":
    asyncio.run(main())

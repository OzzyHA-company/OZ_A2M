"""
Binance Grid Bot - 바이낸스 그리드 봇
STEP 10: OZ_A2M 완결판

설정:
- 거래소: Binance
- 심볼: BTC/USDT
- 그리드 간격: 0.5%
- 주문 개수: 20개
- 자본: $11
- sandbox: False (실거래)
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from decimal import Decimal
from enum import Enum

import ccxt.async_support as ccxt

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger
from lib.messaging.mqtt_client import MQTTClient, MQTTConfig
from lib.messaging.event_bus import EventBus, get_event_bus
from occore.pnl.calculator import ProfitCalculator, get_calculator
from occore.pnl.models import PositionSide

logger = get_logger(__name__)


class GridStatus(str, Enum):
    """그리드 상태"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class GridLevel:
    """그리드 레벨"""
    level: int
    price: float
    buy_order_id: Optional[str] = None
    sell_order_id: Optional[str] = None
    filled: bool = False


@dataclass
class GridTrade:
    """그리드 거래 기록"""
    id: str
    grid_level: int
    side: str
    amount: float
    price: float
    timestamp: datetime
    pnl: Optional[float] = None


class BinanceGridBot:
    """
    Binance 그리드 트레이딩 봇

    전략:
    - 현재가 기준으로 위아래에 그리드 주문 배치
    - 매수 주문 체결 시 해당 레벨 위에 매도 주문 배치
    - 매도 주문 체결 시 해당 레벨 아래에 매수 주문 배치
    """

    def __init__(
        self,
        bot_id: str = "grid_binance_001",
        symbol: str = "BTC/USDT",
        exchange_id: str = "binance",
        capital: float = 11.0,
        grid_count: int = 20,
        grid_spacing_pct: float = 0.005,  # 0.5%
        sandbox: bool = False,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        telegram_alerts: bool = True
    ):
        self.bot_id = bot_id
        self.symbol = symbol
        self.exchange_id = exchange_id
        self.capital = capital
        self.grid_count = grid_count
        self.grid_spacing_pct = grid_spacing_pct
        self.sandbox = sandbox
        self.telegram_alerts = telegram_alerts

        # 상태
        self.status = GridStatus.IDLE
        self.grid_levels: Dict[int, GridLevel] = {}
        self.trades: List[GridTrade] = []
        self.current_price: float = 0.0
        self.grid_range_low: float = 0.0
        self.grid_range_high: float = 0.0

        # 거래소
        self.exchange: Optional[ccxt.Exchange] = None

        # MQTT
        mqtt_config = MQTTConfig(host=mqtt_host, port=mqtt_port, client_id=bot_id)
        self.mqtt = MQTTClient(config=mqtt_config)

        # EventBus
        self.event_bus: Optional[EventBus] = None

        # PnL Calculator
        self.pnl_calculator = get_calculator()

        # Telegram
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        # 통계
        self.total_trades: int = 0
        self.winning_trades: int = 0
        self.total_pnl: float = 0.0
        self.grid_profit: float = 0.0  # 그리드 차익 누적

        # 콜백
        self.on_trade: Optional[Callable[[GridTrade], None]] = None
        self.on_grid_update: Optional[Callable[[], None]] = None

        logger.info(f"BinanceGridBot {bot_id} initialized (capital=${capital}, grids={grid_count})")

    def _load_api_keys(self) -> tuple:
        """.env에서 Binance API 키 로드"""
        api_key = os.environ.get("BINANCE_API_KEY")
        api_secret = os.environ.get("BINANCE_API_SECRET")

        if not api_key or not api_secret:
            raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET must be set in environment")

        return api_key, api_secret

    async def initialize(self):
        """봇 초기화"""
        api_key, api_secret = self._load_api_keys()

        # 거래소 설정
        exchange_class = getattr(ccxt, self.exchange_id)
        config = {
            "apiKey": api_key,
            "secret": api_secret,
            "sandbox": self.sandbox,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"}
        }
        self.exchange = exchange_class(config)

        if self.sandbox:
            self.exchange.set_sandbox_mode(True)

        # 마켓 로드
        await self.exchange.load_markets()

        # 현재가 조회
        ticker = await self.exchange.fetch_ticker(self.symbol)
        self.current_price = ticker["last"]

        # 그리드 범위 계산
        self._calculate_grid_range()

        # EventBus 연결
        try:
            self.event_bus = get_event_bus(mqtt_host="localhost", mqtt_port=1883)
            await self.event_bus.connect()
            logger.info("EventBus connected")
        except Exception as e:
            logger.warning(f"EventBus connection failed: {e}")
            self.event_bus = None

        self.status = GridStatus.RUNNING
        logger.info(f"Grid bot initialized at price ${self.current_price:.2f}")
        logger.info(f"Grid range: ${self.grid_range_low:.2f} ~ ${self.grid_range_high:.2f}")

        # 시작 알림
        await self._send_telegram_notification(
            f"📊 Binance 그리드봇 시작\n"
            f"심볼: {self.symbol}\n"
            f"현재가: ${self.current_price:.2f}\n"
            f"그리드: {self.grid_count}개 ({self.grid_spacing_pct*100}%)\n"
            f"자본: ${self.capital}"
        )

    def _calculate_grid_range(self):
        """그리드 범위 계산"""
        half_grids = self.grid_count // 2
        self.grid_range_low = self.current_price * ((1 - self.grid_spacing_pct) ** half_grids)
        self.grid_range_high = self.current_price * ((1 + self.grid_spacing_pct) ** half_grids)

        # 그리드 레벨 생성
        price_step = (self.grid_range_high - self.grid_range_low) / (self.grid_count - 1)
        for i in range(self.grid_count):
            price = self.grid_range_low + (price_step * i)
            self.grid_levels[i] = GridLevel(level=i, price=price)

    async def run(self):
        """메인 루프"""
        try:
            await self.initialize()
        except Exception as e:
            logger.error(f"Grid bot initialization failed: {e}")
            self.status = GridStatus.ERROR
            raise

        try:
            # 초기 주문 배치
            await self._place_initial_orders()

            while self.status == GridStatus.RUNNING:
                try:
                    # 주문 상태 모니터링
                    await self._monitor_orders()

                    # 그리드 재조정 (가격이 범위를 벗어난 경우)
                    await self._check_grid_rebalance()

                    await asyncio.sleep(5)

                except ccxt.NetworkError as e:
                    logger.error(f"Network error: {e}")
                    await asyncio.sleep(30)
                except Exception as e:
                    logger.error(f"Error in grid loop: {e}")
                    await asyncio.sleep(10)

        except asyncio.CancelledError:
            logger.info("Grid bot cancelled")
            await self.stop()
        except Exception as e:
            logger.error(f"Grid bot error: {e}")
            self.status = GridStatus.ERROR
            await self.stop()
            raise

    async def _place_initial_orders(self):
        """초기 주문 배치"""
        # 현재가보다 아래는 매수 주문, 위는 매도 주문
        for level, grid in self.grid_levels.items():
            if grid.price < self.current_price:
                # 매수 주문
                await self._place_buy_order(level)
            elif grid.price > self.current_price:
                # 매도 주문
                await self._place_sell_order(level)

    async def _place_buy_order(self, level: int):
        """매수 주문 배치"""
        try:
            grid = self.grid_levels[level]
            amount = self._calculate_order_amount()

            order = await self.exchange.create_limit_buy_order(
                self.symbol,
                amount,
                grid.price
            )

            grid.buy_order_id = order["id"]
            logger.debug(f"Placed buy order at level {level}: ${grid.price:.2f}")

        except Exception as e:
            logger.error(f"Failed to place buy order at level {level}: {e}")

    async def _place_sell_order(self, level: int):
        """매도 주문 배치"""
        try:
            grid = self.grid_levels[level]
            amount = self._calculate_order_amount()

            order = await self.exchange.create_limit_sell_order(
                self.symbol,
                amount,
                grid.price
            )

            grid.sell_order_id = order["id"]
            logger.debug(f"Placed sell order at level {level}: ${grid.price:.2f}")

        except Exception as e:
            logger.error(f"Failed to place sell order at level {level}: {e}")

    def _calculate_order_amount(self) -> float:
        """주문 수량 계산"""
        # 자본을 그리드 개수로 분할
        amount_per_grid = (self.capital / self.grid_count) / self.current_price
        return round(amount_per_grid, 6)

    async def _monitor_orders(self):
        """주문 체결 모니터링"""
        try:
            open_orders = await self.exchange.fetch_open_orders(self.symbol)
            open_order_ids = {order["id"] for order in open_orders}

            for level, grid in self.grid_levels.items():
                # 매수 주문 체결 확인
                if grid.buy_order_id and grid.buy_order_id not in open_order_ids:
                    logger.info(f"Buy order filled at level {level}: ${grid.price:.2f}")
                    await self._handle_buy_filled(level)

                # 매도 주문 체결 확인
                if grid.sell_order_id and grid.sell_order_id not in open_order_ids:
                    logger.info(f"Sell order filled at level {level}: ${grid.price:.2f}")
                    await self._handle_sell_filled(level)

        except Exception as e:
            logger.error(f"Error monitoring orders: {e}")

    async def _handle_buy_filled(self, level: int):
        """매수 체결 처리"""
        grid = self.grid_levels[level]
        amount = self._calculate_order_amount()

        # 거래 기록
        trade = GridTrade(
            id=f"grid_buy_{datetime.utcnow().timestamp()}",
            grid_level=level,
            side="buy",
            amount=amount,
            price=grid.price,
            timestamp=datetime.utcnow()
        )
        self.trades.append(trade)
        self.total_trades += 1

        # 상위 레벨에 매도 주문 배치
        if level + 1 < self.grid_count:
            await self._place_sell_order(level + 1)

        # Telegram 알림
        await self._send_telegram_notification(
            f"📥 그리드 매수 체결 (Lv.{level})\n"
            f"가격: ${grid.price:.2f}\n"
            f"수량: {amount:.6f} BTC"
        )

        if self.on_trade:
            self.on_trade(trade)

    async def _handle_sell_filled(self, level: int):
        """매도 체결 처리"""
        grid = self.grid_levels[level]
        amount = self._calculate_order_amount()

        # 그리드 차익 계산 (직전 매수 가격과의 차이)
        grid_profit = amount * grid.price * self.grid_spacing_pct
        self.grid_profit += grid_profit
        self.total_pnl += grid_profit

        # 거래 기록
        trade = GridTrade(
            id=f"grid_sell_{datetime.utcnow().timestamp()}",
            grid_level=level,
            side="sell",
            amount=amount,
            price=grid.price,
            timestamp=datetime.utcnow(),
            pnl=grid_profit
        )
        self.trades.append(trade)
        self.total_trades += 1
        self.winning_trades += 1

        # 하위 레벨에 매수 주문 배치
        if level - 1 >= 0:
            await self._place_buy_order(level - 1)

        # Telegram 알림
        await self._send_telegram_notification(
            f"📤 그리드 매도 체결 (Lv.{level})\n"
            f"가격: ${grid.price:.2f}\n"
            f"수량: {amount:.6f} BTC\n"
            f"차익: ${grid_profit:.4f}"
        )

        if self.on_trade:
            self.on_trade(trade)

    async def _check_grid_rebalance(self):
        """그리드 재조정 필요 여부 확인"""
        try:
            ticker = await self.exchange.fetch_ticker(self.symbol)
            current = ticker["last"]

            # 현재가가 그리드 범위를 벗어난 경우
            if current < self.grid_range_low * 0.95 or current > self.grid_range_high * 1.05:
                logger.info("Price out of grid range, rebalancing...")
                await self._rebalance_grids(current)

        except Exception as e:
            logger.error(f"Error checking grid rebalance: {e}")

    async def _rebalance_grids(self, new_price: float):
        """그리드 재조정"""
        # 기존 주문 모두 취소
        try:
            await self.exchange.cancel_all_orders(self.symbol)
        except Exception as e:
            logger.warning(f"Error cancelling orders: {e}")

        # 새 그리드 범위 계산
        self.current_price = new_price
        self.grid_levels.clear()
        self._calculate_grid_range()

        # 새 주문 배치
        await self._place_initial_orders()

        logger.info(f"Grids rebalanced around ${new_price:.2f}")

    async def stop(self):
        """봇 중지"""
        self.status = GridStatus.IDLE

        # 모든 주문 취소
        try:
            await self.exchange.cancel_all_orders(self.symbol)
            logger.info("All orders cancelled")
        except Exception as e:
            logger.error(f"Error cancelling orders: {e}")

        # EventBus 연결 해제
        if self.event_bus:
            await self.event_bus.disconnect()

        await self.mqtt.disconnect()

        # 일일 리포트
        await self._send_daily_report()

        logger.info(f"Grid bot {self.bot_id} stopped")

    async def _send_telegram_notification(self, message: str):
        """Telegram 알림 발송"""
        if not self.telegram_alerts or not self.telegram_bot_token or not self.telegram_chat_id:
            return

        try:
            import aiohttp
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        logger.warning(f"Telegram notification failed: {resp.status}")
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")

    async def _send_daily_report(self):
        """일일 리포트 발송"""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        await self._send_telegram_notification(
            f"📊 Grid Bot 일일 리포트\n"
            f"총 거래: {self.total_trades}회\n"
            f"승률: {win_rate:.1f}%\n"
            f"그리드 차익: ${self.grid_profit:.4f}\n"
            f"총 PnL: ${self.total_pnl:.4f}"
        )

    def get_status(self) -> Dict[str, Any]:
        """봇 상태 반환"""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0

        return {
            "bot_id": self.bot_id,
            "bot_type": "grid",
            "exchange": self.exchange_id,
            "status": self.status.value,
            "symbol": self.symbol,
            "capital": self.capital,
            "current_price": self.current_price,
            "grid_count": self.grid_count,
            "grid_spacing_pct": self.grid_spacing_pct,
            "grid_range_low": self.grid_range_low,
            "grid_range_high": self.grid_range_high,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "win_rate": win_rate,
            "total_pnl": self.total_pnl,
            "grid_profit": self.grid_profit,
            "timestamp": datetime.utcnow().isoformat()
        }

    def get_grid_levels(self) -> List[Dict]:
        """그리드 레벨 정보 반환"""
        return [
            {
                "level": g.level,
                "price": g.price,
                "buy_order_id": g.buy_order_id,
                "sell_order_id": g.sell_order_id,
                "filled": g.filled
            }
            for g in self.grid_levels.values()
        ]


async def main():
    """단독 실행용"""
    bot = BinanceGridBot(
        bot_id="grid_binance_001",
        symbol="BTC/USDT",
        capital=11.0,
        grid_count=20,
        grid_spacing_pct=0.005,
        sandbox=False
    )

    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()
        print("\n📊 Final Stats:")
        status = bot.get_status()
        print(f"   Total Trades: {status['total_trades']}")
        print(f"   Grid Profit: ${status['grid_profit']:.4f}")


if __name__ == "__main__":
    asyncio.run(main())

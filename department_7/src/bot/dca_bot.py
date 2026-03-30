"""
Binance DCA Bot - 바이낸스 DCA (Dollar Cost Averaging) 봇
STEP 10: OZ_A2M 완결판

설정:
- 거래소: Binance
- 심볼: BTC/USDT
- 하락 -2%마다 분할매수
- 반등 +3% 익절
- 자본: $14
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
from occore.pnl.calculator import get_calculator
from occore.pnl.models import PositionSide

logger = get_logger(__name__)


class DCAStatus(str, Enum):
    """DCA 봇 상태"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class DCAPosition:
    """DCA 포지션"""
    entry_price: float
    amount: float
    timestamp: datetime
    dca_count: int = 1  # DCA 횟수

    @property
    def total_cost(self) -> float:
        return self.entry_price * self.amount


@dataclass
class DCATrade:
    """DCA 거래 기록"""
    id: str
    side: str
    amount: float
    price: float
    timestamp: datetime
    dca_count: int = 0
    pnl: Optional[float] = None


class BinanceDCABot:
    """
    Binance DCA (Dollar Cost Averaging) 봇

    전략:
    - 초기 매수 후 가격이 -2% 하락할 때마다 추가 매수
    - 평균 매수가 기준 +3% 반등 시 전량 익절
    - 리스크 분산을 위한 분할 매수
    """

    def __init__(
        self,
        bot_id: str = "dca_binance_001",
        symbol: str = "BTC/USDT",
        exchange_id: str = "binance",
        capital: float = 14.0,
        dca_drop_pct: float = 0.02,  # -2%
        take_profit_pct: float = 0.03,  # +3%
        max_dca_count: int = 5,  # 최대 DCA 횟수
        sandbox: bool = False,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        telegram_alerts: bool = True
    ):
        self.bot_id = bot_id
        self.symbol = symbol
        self.exchange_id = exchange_id
        self.capital = capital
        self.dca_drop_pct = dca_drop_pct
        self.take_profit_pct = take_profit_pct
        self.max_dca_count = max_dca_count
        self.sandbox = sandbox
        self.telegram_alerts = telegram_alerts

        # 상태
        self.status = DCAStatus.IDLE
        self.position: Optional[DCAPosition] = None
        self.trades: List[DCATrade] = []
        self.current_price: float = 0.0
        self.last_dca_price: float = 0.0
        self.peak_price: float = 0.0  # 최고가 (트레일링용)

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
        self.dca_executions: int = 0  # DCA 실행 횟수

        # 콜백
        self.on_trade: Optional[Callable[[DCATrade], None]] = None
        self.on_position_change: Optional[Callable[[Optional[DCAPosition]], None]] = None

        logger.info(f"BinanceDCABot {bot_id} initialized (capital=${capital}, DCA={dca_drop_pct*100}%)")

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

        # EventBus 연결
        try:
            self.event_bus = get_event_bus(mqtt_host="localhost", mqtt_port=1883)
            await self.event_bus.connect()
            logger.info("EventBus connected")
        except Exception as e:
            logger.warning(f"EventBus connection failed: {e}")
            self.event_bus = None

        self.status = DCAStatus.RUNNING
        logger.info(f"DCA bot initialized at price ${self.current_price:.2f}")

        # 시작 알림
        await self._send_telegram_notification(
            f"📉 Binance DCA봇 시작\n"
            f"심볼: {self.symbol}\n"
            f"현재가: ${self.current_price:.2f}\n"
            f"DCA 조건: -{self.dca_drop_pct*100}%\n"
            f"익절 조건: +{self.take_profit_pct*100}%\n"
            f"자본: ${self.capital}"
        )

    async def run(self):
        """메인 루프"""
        try:
            await self.initialize()
        except Exception as e:
            logger.error(f"DCA bot initialization failed: {e}")
            self.status = DCAStatus.ERROR
            raise

        try:
            # 초기 매수
            if not self.position:
                await self._initial_buy()

            while self.status == DCAStatus.RUNNING:
                try:
                    # 현재가 업데이트
                    await self._update_price()

                    if self.position:
                        # DCA 조건 체크
                        await self._check_dca_condition()

                        # 익절 조건 체크
                        await self._check_take_profit()

                    await asyncio.sleep(10)  # 10초마다 체크

                except ccxt.NetworkError as e:
                    logger.error(f"Network error: {e}")
                    await asyncio.sleep(30)
                except Exception as e:
                    logger.error(f"Error in DCA loop: {e}")
                    await asyncio.sleep(10)

        except asyncio.CancelledError:
            logger.info("DCA bot cancelled")
            await self.stop()
        except Exception as e:
            logger.error(f"DCA bot error: {e}")
            self.status = DCAStatus.ERROR
            await self.stop()
            raise

    async def _update_price(self):
        """현재가 업데이트"""
        try:
            ticker = await self.exchange.fetch_ticker(self.symbol)
            self.current_price = ticker["last"]

            # 최고가 업데이트
            if self.current_price > self.peak_price:
                self.peak_price = self.current_price

        except Exception as e:
            logger.error(f"Failed to update price: {e}")

    async def _initial_buy(self):
        """초기 매수"""
        try:
            amount = self._calculate_position_amount()
            order = await self.exchange.create_market_buy_order(self.symbol, amount)

            price = order["price"] or order["average"] or self.current_price

            self.position = DCAPosition(
                entry_price=price,
                amount=amount,
                timestamp=datetime.utcnow(),
                dca_count=1
            )
            self.last_dca_price = price
            self.peak_price = price

            # 거래 기록
            trade = DCATrade(
                id=order["id"],
                side="buy",
                amount=amount,
                price=price,
                timestamp=datetime.utcnow(),
                dca_count=1
            )
            self.trades.append(trade)
            self.total_trades += 1

            logger.info(f"Initial buy: {amount} BTC @ ${price:.2f}")

            # Telegram 알림
            await self._send_telegram_notification(
                f"📥 DCA 초기 매수\n"
                f"가격: ${price:.2f}\n"
                f"수량: {amount:.6f} BTC\n"
                f"금액: ${amount * price:.2f}"
            )

            if self.on_position_change:
                self.on_position_change(self.position)

        except Exception as e:
            logger.error(f"Failed to execute initial buy: {e}")
            raise

    async def _check_dca_condition(self):
        """DCA 조건 체크"""
        if not self.position:
            return

        if self.position.dca_count >= self.max_dca_count:
            return  # 최대 DCA 횟수 도달

        # 현재가가 마지막 DCA 가격보다 dca_drop_pct 이상 하락했는지 확인
        drop_pct = (self.last_dca_price - self.current_price) / self.last_dca_price

        if drop_pct >= self.dca_drop_pct:
            logger.info(f"DCA condition met: price dropped {drop_pct*100:.2f}%")
            await self._execute_dca()

    async def _execute_dca(self):
        """DCA 실행 (추가 매수)"""
        try:
            amount = self._calculate_position_amount()
            order = await self.exchange.create_market_buy_order(self.symbol, amount)

            price = order["price"] or order["average"] or self.current_price

            # 포지션 업데이트 (평균 단가 재계산)
            total_cost = (self.position.entry_price * self.position.amount) + (price * amount)
            total_amount = self.position.amount + amount

            self.position.entry_price = total_cost / total_amount
            self.position.amount = total_amount
            self.position.dca_count += 1
            self.last_dca_price = price
            self.dca_executions += 1

            # 거래 기록
            trade = DCATrade(
                id=order["id"],
                side="buy",
                amount=amount,
                price=price,
                timestamp=datetime.utcnow(),
                dca_count=self.position.dca_count
            )
            self.trades.append(trade)
            self.total_trades += 1

            logger.info(f"DCA #{self.position.dca_count}: +{amount} BTC @ ${price:.2f}")
            logger.info(f"New average price: ${self.position.entry_price:.2f}")

            # Telegram 알림
            await self._send_telegram_notification(
                f"📉 DCA #{self.position.dca_count} 실행\n"
                f"추가매수 가격: ${price:.2f}\n"
                f"수량: {amount:.6f} BTC\n"
                f"평균단가: ${self.position.entry_price:.2f}\n"
                f"총수량: {self.position.amount:.6f} BTC"
            )

            if self.on_position_change:
                self.on_position_change(self.position)

        except Exception as e:
            logger.error(f"Failed to execute DCA: {e}")

    async def _check_take_profit(self):
        """익절 조건 체크"""
        if not self.position:
            return

        # 평균 매수가 대비 상승률 계산
        gain_pct = (self.current_price - self.position.entry_price) / self.position.entry_price

        if gain_pct >= self.take_profit_pct:
            logger.info(f"Take profit condition met: price up {gain_pct*100:.2f}%")
            await self._execute_take_profit()

    async def _execute_take_profit(self):
        """익절 실행"""
        try:
            order = await self.exchange.create_market_sell_order(
                self.symbol,
                self.position.amount
            )

            exit_price = order["price"] or order["average"] or self.current_price
            pnl = (exit_price - self.position.entry_price) * self.position.amount
            pnl_pct = (exit_price / self.position.entry_price - 1) * 100

            # 거래 기록
            trade = DCATrade(
                id=order["id"],
                side="sell",
                amount=self.position.amount,
                price=exit_price,
                timestamp=datetime.utcnow(),
                dca_count=self.position.dca_count,
                pnl=pnl
            )
            self.trades.append(trade)
            self.total_trades += 1
            self.winning_trades += 1
            self.total_pnl += pnl

            logger.info(f"Take profit: Sold {self.position.amount} BTC @ ${exit_price:.2f}")
            logger.info(f"PnL: ${pnl:.2f} ({pnl_pct:.2f}%)")

            # Telegram 알림
            emoji = "🟢" if pnl > 0 else "🔴"
            await self._send_telegram_notification(
                f"{emoji} DCA 익절 완료\n"
                f"매도가: ${exit_price:.2f}\n"
                f"평균단가: ${self.position.entry_price:.2f}\n"
                f"수량: {self.position.amount:.6f} BTC\n"
                f"PnL: ${pnl:.2f} ({pnl_pct:.2f}%)\n"
                f"DCA 횟수: {self.position.dca_count}"
            )

            # 포지션 클리어
            self.position = None
            self.last_dca_price = 0
            self.peak_price = 0

            if self.on_trade:
                self.on_trade(trade)
            if self.on_position_change:
                self.on_position_change(None)

            # 새로운 사이클 시작 (선택적)
            await asyncio.sleep(5)
            await self._initial_buy()

        except Exception as e:
            logger.error(f"Failed to execute take profit: {e}")

    def _calculate_position_amount(self) -> float:
        """포지션 수량 계산 (자본을 DCA 횟수로 분할)"""
        amount_per_dca = (self.capital / self.max_dca_count) / self.current_price
        return round(amount_per_dca, 6)

    async def stop(self):
        """봇 중지"""
        self.status = DCAStatus.IDLE

        # 열린 포지션 정리 (선택적)
        if self.position:
            try:
                await self._execute_take_profit()
            except Exception as e:
                logger.error(f"Error closing position on stop: {e}")

        # EventBus 연결 해제
        if self.event_bus:
            await self.event_bus.disconnect()

        await self.mqtt.disconnect()

        # 일일 리포트
        await self._send_daily_report()

        logger.info(f"DCA bot {self.bot_id} stopped")

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
            f"📊 DCA Bot 일일 리포트\n"
            f"총 거래: {self.total_trades}회\n"
            f"DCA 실행: {self.dca_executions}회\n"
            f"승률: {win_rate:.1f}%\n"
            f"총 PnL: ${self.total_pnl:.2f}"
        )

    def get_status(self) -> Dict[str, Any]:
        """봇 상태 반환"""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0

        return {
            "bot_id": self.bot_id,
            "bot_type": "dca",
            "exchange": self.exchange_id,
            "status": self.status.value,
            "symbol": self.symbol,
            "capital": self.capital,
            "current_price": self.current_price,
            "position": {
                "entry_price": self.position.entry_price,
                "amount": self.position.amount,
                "dca_count": self.position.dca_count,
                "timestamp": self.position.timestamp.isoformat()
            } if self.position else None,
            "dca_drop_pct": self.dca_drop_pct,
            "take_profit_pct": self.take_profit_pct,
            "max_dca_count": self.max_dca_count,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "win_rate": win_rate,
            "total_pnl": self.total_pnl,
            "dca_executions": self.dca_executions,
            "timestamp": datetime.utcnow().isoformat()
        }


async def main():
    """단독 실행용"""
    bot = BinanceDCABot(
        bot_id="dca_binance_001",
        symbol="BTC/USDT",
        capital=14.0,
        dca_drop_pct=0.02,
        take_profit_pct=0.03,
        sandbox=False
    )

    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()
        print("\n📊 Final Stats:")
        status = bot.get_status()
        print(f"   Total Trades: {status['total_trades']}")
        print(f"   Total PnL: ${status['total_pnl']:.2f}")


if __name__ == "__main__":
    asyncio.run(main())

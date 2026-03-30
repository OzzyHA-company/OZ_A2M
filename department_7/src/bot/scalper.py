"""
Bybit Scalping Bot - Bybit 단타 매매 봇
STEP 9: OZ_A2M 완결판

기능:
- Bybit SOL/USDT 스캘핑
- .env에서 BYBIT_API_KEY/SECRET 로드
- sandbox=False, 자본 $20
- Telegram 거래 체결 알림
"""

import asyncio
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional, Callable
from enum import Enum
from decimal import Decimal

import ccxt.async_support as ccxt

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger
from lib.messaging.mqtt_client import MQTTClient, MQTTConfig
from lib.messaging.event_bus import EventBus, EventType, EventPriority, get_event_bus

logger = get_logger(__name__)


class BotState(str, Enum):
    """봇 상태"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


class PositionSide(str, Enum):
    """포지션 방향"""
    LONG = "long"
    SHORT = "short"
    NONE = "none"


@dataclass
class Position:
    """포지션 정보"""
    symbol: str
    side: PositionSide
    entry_price: float
    amount: float
    entry_time: datetime
    unrealized_pnl: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "entry_price": self.entry_price,
            "amount": self.amount,
            "entry_time": self.entry_time.isoformat(),
            "unrealized_pnl": self.unrealized_pnl
        }


@dataclass
class Trade:
    """거래 기록"""
    id: str
    symbol: str
    side: str
    amount: float
    price: float
    timestamp: datetime
    pnl: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "amount": self.amount,
            "price": self.price,
            "timestamp": self.timestamp.isoformat(),
            "pnl": self.pnl
        }


class BybitScalpingBot:
    """
    Bybit 스캘핑 봇

    설정:
    - exchange_id: "bybit"
    - symbol: "SOL/USDT"
    - sandbox: False (실거래)
    - 자본: $20 USDT
    """

    def __init__(
        self,
        bot_id: str = "scalper_bybit_001",
        symbol: str = "SOL/USDT",
        exchange_id: str = "bybit",
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        sandbox: bool = False,
        capital: float = 20.0,
        telegram_alerts: bool = True
    ):
        self.bot_id = bot_id
        self.symbol = symbol
        self.exchange_id = exchange_id
        self.sandbox = sandbox
        self.capital = capital
        self.telegram_alerts = telegram_alerts

        # 상태
        self.state = BotState.IDLE
        self.position: Optional[Position] = None
        self.trades: List[Trade] = []
        self.balance: float = capital
        self.initial_capital = capital

        # 리스크 설정 (스캘핑용)
        self.max_position_size = 0.5  # 최대 0.5 SOL
        self.stop_loss_pct = 0.01  # 손절 -1%
        self.take_profit_pct = 0.02  # 익절 +2%
        self.max_daily_loss = capital * 0.2  # 일일 최대 손실 20%

        # 거래소
        self.exchange: Optional[ccxt.Exchange] = None

        # MQTT
        mqtt_config = MQTTConfig(
            host=mqtt_host,
            port=mqtt_port,
            client_id=bot_id
        )
        self.mqtt = MQTTClient(config=mqtt_config)
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port

        # EventBus
        self.event_bus: Optional[EventBus] = None
        self.enable_kafka = False

        # Telegram 알림
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        # 통계
        self.daily_pnl: float = 0.0
        self.total_trades: int = 0
        self.winning_trades: int = 0
        self.daily_trades: int = 0

        # 콜백
        self.on_trade: Optional[Callable[[Trade], None]] = None
        self.on_position_change: Optional[Callable[[Optional[Position]], None]] = None

        logger.info(f"BybitScalpingBot {bot_id} initialized (capital=${capital}, sandbox={sandbox})")

    def _load_api_keys(self) -> tuple:
        """.env에서 Bybit API 키 로드"""
        api_key = os.environ.get("BYBIT_API_KEY")
        api_secret = os.environ.get("BYBIT_API_SECRET")

        if not api_key or not api_secret:
            raise ValueError("BYBIT_API_KEY and BYBIT_API_SECRET must be set in environment")

        return api_key, api_secret

    async def initialize(self, enable_event_bus: bool = True, enable_kafka: bool = False):
        """봇 초기화"""
        # API 키 로드
        api_key, api_secret = self._load_api_keys()

        # 거래소 설정
        exchange_class = getattr(ccxt, self.exchange_id)
        config = {
            "apiKey": api_key,
            "secret": api_secret,
            "sandbox": self.sandbox,
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot"
            }
        }
        self.exchange = exchange_class(config)

        # 샌드박스 모드 설정
        if self.sandbox:
            self.exchange.set_sandbox_mode(True)
            logger.info("Exchange set to sandbox mode")

        # 마켓 로드
        await self.exchange.load_markets()

        # EventBus 초기화
        if enable_event_bus:
            try:
                self.event_bus = get_event_bus(
                    mqtt_host=self.mqtt_host,
                    mqtt_port=self.mqtt_port,
                    enable_kafka=enable_kafka
                )
                self.enable_kafka = enable_kafka
                await self.event_bus.connect()
                logger.info(f"EventBus connected (Kafka: {enable_kafka})")
            except Exception as e:
                logger.warning(f"EventBus connection failed, falling back to MQTT only: {e}")
                self.event_bus = None

        # MQTT 연결
        if not self.event_bus:
            try:
                await self.mqtt.connect()
                await self.mqtt.subscribe("signals/scalping", self._on_mqtt_message)
                await self.mqtt.subscribe(f"orders/{self.bot_id}/execute", self._on_mqtt_message)
                logger.info(f"MQTT connected for bot {self.bot_id}")
            except Exception as e:
                logger.error(f"MQTT connection failed: {e}")
                self.state = BotState.ERROR
                raise RuntimeError(f"Failed to connect MQTT: {e}")

        self.state = BotState.RUNNING
        logger.info(f"BybitScalpingBot {self.bot_id} initialized and running")

        # 시작 알림
        await self._send_telegram_notification(
            f"🚀 Bybit 스캘핑봇 시작\n"
            f"심볼: {self.symbol}\n"
            f"자본: ${self.capital}\n"
            f"모드: {'실거래' if not self.sandbox else '테스트'}"
        )

    async def run(self):
        """봇 메인 루프"""
        try:
            await self.initialize()
        except Exception as e:
            logger.error(f"Bot initialization failed: {e}")
            self.state = BotState.ERROR
            raise

        try:
            while self.state == BotState.RUNNING:
                try:
                    # 포지션 모니터링
                    if self.position:
                        await self._check_exit_conditions()

                    # 잔고 업데이트
                    await self._update_balance()

                    # 일일 거래량 리셋 (자정)
                    await self._check_daily_reset()

                    await asyncio.sleep(5)

                except ccxt.NetworkError as e:
                    logger.error(f"Network error in bot loop: {e}")
                    await asyncio.sleep(30)
                    continue
                except ccxt.ExchangeError as e:
                    logger.error(f"Exchange error in bot loop: {e}")
                    self.state = BotState.ERROR
                    await self._safe_stop()
                    raise
                except Exception as e:
                    logger.error(f"Unexpected error in bot loop: {e}")
                    self.state = BotState.ERROR
                    await self._safe_stop()
                    raise

        except asyncio.CancelledError:
            logger.info("Bot loop cancelled")
            await self._safe_stop()
        except Exception as e:
            logger.error(f"Bot error: {e}")
            self.state = BotState.ERROR
            await self._safe_stop()
            raise

    async def _safe_stop(self):
        """안전한 봇 중지"""
        logger.warning(f"Safe stopping bot {self.bot_id}")
        try:
            self.state = BotState.ERROR

            if self.event_bus:
                try:
                    await self.event_bus.emit_bot_status(
                        bot_id=self.bot_id,
                        status="error",
                        detail={"daily_pnl": self.daily_pnl, "total_trades": self.total_trades}
                    )
                except Exception as e:
                    logger.error(f"Failed to emit error status: {e}")

            if self.position:
                try:
                    await self.close_position()
                except Exception as e:
                    logger.error(f"Failed to close position during safe stop: {e}")

            if self.event_bus:
                try:
                    await self.event_bus.disconnect()
                except Exception as e:
                    logger.error(f"Failed to disconnect EventBus: {e}")

            try:
                await self.mqtt.disconnect()
            except Exception as e:
                logger.error(f"Failed to disconnect MQTT: {e}")

            await self._send_telegram_notification(
                f"⚠️ Bybit 스캘핑봇 비상정지\n"
                f"누적 PnL: ${self.daily_pnl:.2f}"
            )

            logger.info(f"BybitScalpingBot {self.bot_id} safely stopped")
        except Exception as e:
            logger.error(f"Error during safe stop: {e}")

    async def stop(self):
        """봇 중지"""
        self.state = BotState.IDLE

        if self.event_bus:
            try:
                await self.event_bus.emit_bot_status(
                    bot_id=self.bot_id,
                    status="stopped",
                    detail={"daily_pnl": self.daily_pnl, "total_trades": self.total_trades}
                )
            except Exception as e:
                logger.warning(f"Failed to emit stop status: {e}")

        if self.position:
            await self.close_position()

        if self.event_bus:
            await self.event_bus.disconnect()
            logger.info("EventBus disconnected")

        await self.mqtt.disconnect()

        # 일일 PnL 알림
        await self._send_daily_pnl_notification()

        logger.info(f"BybitScalpingBot {self.bot_id} stopped")

    async def _on_mqtt_message(self, message):
        """MQTT 메시지 처리"""
        try:
            topic = message.topic.value
            payload = message.payload.decode()
            msg = json.loads(payload)
            logger.debug(f"Received message on {topic}: {msg}")

            if topic == "signals/scalping":
                await self._handle_signal(msg)
            elif topic == f"orders/{self.bot_id}/execute":
                await self._handle_manual_order(msg)

        except Exception as e:
            logger.error(f"Error handling MQTT message: {e}")

    async def _handle_signal(self, signal: Dict):
        """매매 신호 처리"""
        action = signal.get("action")
        symbol = signal.get("symbol")
        amount = signal.get("amount", 0.1)
        confidence = signal.get("confidence", 0.5)

        if symbol != self.symbol:
            return

        if confidence < 0.7:
            logger.info(f"Signal ignored due to low confidence: {confidence}")
            return

        logger.info(f"Processing signal: {action} {symbol} @ {signal.get('price')}")

        if action == "buy":
            await self.open_long(amount)
        elif action == "sell":
            if self.position and self.position.side == PositionSide.LONG:
                await self.close_position()

    async def _handle_manual_order(self, order: Dict):
        """수동 주문 처리"""
        action = order.get("action")
        amount = order.get("amount", 0.1)

        if action == "buy":
            await self.open_long(amount)
        elif action == "sell":
            await self.close_position()

    async def open_long(self, amount: float):
        """롱 포지션 진입"""
        if self.position:
            logger.warning("Already in position")
            return

        if amount > self.max_position_size:
            amount = self.max_position_size

        try:
            order = self.exchange.create_market_buy_order(self.symbol, amount)
            price = order["price"] or order["average"]

            self.position = Position(
                symbol=self.symbol,
                side=PositionSide.LONG,
                entry_price=price,
                amount=amount,
                entry_time=datetime.utcnow()
            )

            trade = Trade(
                id=order["id"],
                symbol=self.symbol,
                side="buy",
                amount=amount,
                price=price,
                timestamp=datetime.utcnow()
            )
            self.trades.append(trade)
            self.total_trades += 1
            self.daily_trades += 1

            logger.info(f"Opened LONG position: {amount} {self.symbol} @ {price}")

            # Telegram 알림
            await self._send_telegram_notification(
                f"✅ 매수 체결\n"
                f"심볼: {self.symbol}\n"
                f"수량: {amount} SOL\n"
                f"가격: ${price:.4f}\n"
                f"금액: ${amount * price:.2f}"
            )

            if self.on_position_change:
                self.on_position_change(self.position)
            await self._publish_trade(trade)

        except ccxt.NetworkError as e:
            logger.error(f"Network error opening position: {e}")
        except ccxt.InsufficientFunds as e:
            logger.error(f"Insufficient funds: {e}")
            await self._send_telegram_notification(f"⚠️ 잔고부족: {e}")
            await self._safe_stop()
            raise RuntimeError(f"Insufficient funds, bot stopped: {e}")
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error opening position: {e}")
            self.state = BotState.ERROR
            await self._safe_stop()
            raise
        except Exception as e:
            logger.error(f"Failed to open long position: {e}")
            self.state = BotState.ERROR
            await self._safe_stop()
            raise

    async def close_position(self):
        """포지션 청산"""
        if not self.position:
            return

        try:
            if self.position.side == PositionSide.LONG:
                order = self.exchange.create_market_sell_order(
                    self.symbol,
                    self.position.amount
                )

                exit_price = order["price"] or order["average"]
                pnl = (exit_price - self.position.entry_price) * self.position.amount

                trade = Trade(
                    id=order["id"],
                    symbol=self.symbol,
                    side="sell",
                    amount=self.position.amount,
                    price=exit_price,
                    timestamp=datetime.utcnow(),
                    pnl=pnl
                )
                self.trades.append(trade)
                self.total_trades += 1
                self.daily_trades += 1

                if pnl > 0:
                    self.winning_trades += 1
                self.daily_pnl += pnl

                logger.info(f"Closed LONG position: {self.position.amount} {self.symbol} @ {exit_price}, PnL: {pnl:.4f}")

                # Telegram 알림
                emoji = "🟢" if pnl > 0 else "🔴"
                await self._send_telegram_notification(
                    f"{emoji} 매도 체결\n"
                    f"심볼: {self.symbol}\n"
                    f"수량: {self.position.amount} SOL\n"
                    f"가격: ${exit_price:.4f}\n"
                    f"PnL: ${pnl:.4f}"
                )

                if self.on_trade:
                    self.on_trade(trade)
                await self._publish_trade(trade)

            self.position = None

            if self.on_position_change:
                self.on_position_change(None)

        except ccxt.NetworkError as e:
            logger.error(f"Network error closing position: {e}")
            await self._sync_position()
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error closing position: {e}")
            self.state = BotState.ERROR
            raise
        except Exception as e:
            logger.error(f"Failed to close position: {e}")
            raise

    async def _check_exit_conditions(self):
        """손절/익절 조건 체크"""
        if not self.position:
            return

        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            current_price = ticker["last"]

            if self.position.side == PositionSide.LONG:
                pnl_pct = (current_price - self.position.entry_price) / self.position.entry_price
                self.position.unrealized_pnl = (current_price - self.position.entry_price) * self.position.amount

                if pnl_pct <= -self.stop_loss_pct:
                    logger.info(f"Stop loss triggered: {pnl_pct:.4%}")
                    await self.close_position()
                    return

                if pnl_pct >= self.take_profit_pct:
                    logger.info(f"Take profit triggered: {pnl_pct:.4%}")
                    await self.close_position()
                    return

            if self.daily_pnl < -self.max_daily_loss:
                logger.warning("Daily max loss reached, stopping bot")
                await self._send_telegram_notification(
                    f"🛑 일일 최대 손실 도달 (${self.max_daily_loss:.2f})\n"
                    f"봇을 중지합니다."
                )
                await self.stop()

        except Exception as e:
            logger.error(f"Error checking exit conditions: {e}")

    async def _sync_position(self):
        """거래소에서 포지션 상태 동기화"""
        try:
            positions = self.exchange.fetch_positions([self.symbol])
            for pos in positions:
                if pos['symbol'] == self.symbol and pos['contracts'] > 0:
                    if not self.position:
                        self.position = Position(
                            symbol=self.symbol,
                            side=PositionSide.LONG if pos['side'] == 'long' else PositionSide.SHORT,
                            entry_price=pos['entryPrice'],
                            amount=pos['contracts'],
                            entry_time=datetime.utcnow()
                        )
                        logger.info(f"Position synced from exchange: {self.position}")
                    break
            else:
                if self.position:
                    logger.warning("Position not found in exchange, clearing local state")
                    self.position = None
        except Exception as e:
            logger.error(f"Failed to sync position: {e}")

    async def _update_balance(self):
        """잔고 업데이트"""
        try:
            balance = await self.exchange.fetch_balance()
            self.balance = balance["USDT"]["free"] if "USDT" in balance else 0.0
        except ccxt.NetworkError as e:
            logger.warning(f"Network error updating balance: {e}")
        except Exception as e:
            logger.error(f"Error updating balance: {e}")

    async def _publish_trade(self, trade: Trade):
        """거래 정보 발행"""
        try:
            if self.event_bus:
                await self.event_bus.emit_trade(
                    trade_id=trade.id,
                    order_id=trade.id,
                    symbol=trade.symbol,
                    side=trade.side,
                    amount=trade.amount,
                    price=trade.price,
                    pnl=trade.pnl
                )
            else:
                topic = f"trades/{self.bot_id}"
                payload = json.dumps(trade.to_dict())
                await self.mqtt.publish(topic, payload)
        except Exception as e:
            logger.error(f"Error publishing trade: {e}")

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

    async def _send_daily_pnl_notification(self):
        """일일 PnL 알림 발송"""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        await self._send_telegram_notification(
            f"📊 Bybit 스캘핑봇 일일 리포트\n"
            f"총 거래: {self.total_trades}회\n"
            f"승률: {win_rate:.1f}%\n"
            f"일일 PnL: ${self.daily_pnl:.2f}\n"
            f"수익률: {(self.daily_pnl / self.initial_capital * 100):.2f}%"
        )

    async def _check_daily_reset(self):
        """일일 통계 리셋 체크"""
        # 자정에 리셋 (간단한 구현)
        pass

    def get_status(self) -> Dict:
        """봇 상태 반환"""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0

        return {
            "bot_id": self.bot_id,
            "bot_type": "scalping",
            "exchange": self.exchange_id,
            "status": self.state.value,  # 'state' 대신 'status' 사용 (호환성)
            "state": self.state.value,
            "symbol": self.symbol,
            "capital": self.capital,
            "balance": self.balance,
            "position": self.position.to_dict() if self.position else None,
            "daily_pnl": self.daily_pnl,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "win_rate": win_rate,
            "timestamp": datetime.utcnow().isoformat()
        }

    def get_recent_trades(self, limit: int = 10) -> List[Dict]:
        """최근 거래 내역"""
        return [t.to_dict() for t in self.trades[-limit:]]


# UnifiedBotManager 통합을 위한 인터페이스
class ScalpingBotAdapter:
    """UnifiedBotManager용 어댑터"""

    def __init__(self, bot: BybitScalpingBot):
        self.bot = bot
        self.bot_id = bot.bot_id

    async def start(self):
        await self.bot.run()

    async def stop(self):
        await self.bot.stop()

    def get_status(self) -> Dict:
        return self.bot.get_status()


# 하위 호환성을 위한 별칭
ScalpingBot = BybitScalpingBot


async def main():
    """단독 실행용 메인 함수"""
    bot = BybitScalpingBot(
        bot_id="scalper_bybit_001",
        symbol="SOL/USDT",
        exchange_id="bybit",
        sandbox=False,
        capital=20.0,
        telegram_alerts=True
    )

    def on_trade(trade: Trade):
        print(f"\n💰 TRADE: {trade.side.upper()} {trade.amount} @ {trade.price}")
        if trade.pnl:
            emoji = "🟢" if trade.pnl > 0 else "🔴"
            print(f"   PnL: {emoji} {trade.pnl:.4f} USDT")

    def on_position_change(pos: Optional[Position]):
        if pos:
            print(f"\n📊 POSITION: {pos.side.value.upper()} {pos.amount} @ {pos.entry_price}")
        else:
            print("\n📊 POSITION: Closed")

    bot.on_trade = on_trade
    bot.on_position_change = on_position_change

    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()
        print("\n\n📈 Final Stats:")
        status = bot.get_status()
        print(f"   Total Trades: {status['total_trades']}")
        print(f"   Win Rate: {status['win_rate']:.1f}%")
        print(f"   Daily PnL: ${status['daily_pnl']:.4f}")


if __name__ == "__main__":
    asyncio.run(main())

"""
Scalping Bot - 단타 매매 봇
Phase 7 핵심 컴포넌트
"""

import asyncio
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional, Callable
from enum import Enum

import ccxt

from occore.logger import get_logger
from occore.messaging.mqtt_client import MQTTClient

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


class ScalpingBot:
    """
    스캘핑 봇

    기능:
    - MQTT 신호 수신
    - 시장가 주문 실행
    - 포지션 관리
    - 손절/익절 자동화
    - 성과 추적
    """

    def __init__(
        self,
        bot_id: str = "scalper_1",
        symbol: str = "BTC/USDT",
        exchange_id: str = "binance",
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        sandbox: bool = True
    ):
        self.bot_id = bot_id
        self.symbol = symbol
        self.exchange_id = exchange_id
        self.sandbox = sandbox

        # 상태
        self.state = BotState.IDLE
        self.position: Optional[Position] = None
        self.trades: List[Trade] = []
        self.balance: float = 10000.0  # 시작 잔고 (USDT)

        # 리스크 설정
        self.max_position_size = 0.01  # 최대 포지션 크기 (BTC)
        self.stop_loss_pct = 0.005  # 손절 -0.5%
        self.take_profit_pct = 0.01  # 익절 +1%
        self.max_daily_loss = 100.0  # 일일 최대 손실

        # 거래소
        self.exchange: Optional[ccxt.Exchange] = None

        # MQTT
        self.mqtt = MQTTClient(client_id=bot_id)
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port

        # 통계
        self.daily_pnl: float = 0.0
        self.total_trades: int = 0
        self.winning_trades: int = 0

        # 콜백
        self.on_trade: Optional[Callable[[Trade], None]] = None
        self.on_position_change: Optional[Callable[[Optional[Position]], None]] = None

        logger.info(f"ScalpingBot {bot_id} initialized")

    async def initialize(self):
        """봇 초기화"""
        # 거래소 설정
        exchange_class = getattr(ccxt, self.exchange_id)
        config = {
            "sandbox": self.sandbox,
            "enableRateLimit": True,
        }
        self.exchange = exchange_class(config)

        # 테스트넷 설정
        if self.sandbox:
            self.exchange.set_sandbox_mode(True)
            logger.info("Exchange set to sandbox mode")

        # MQTT 연결
        await self.mqtt.connect(self.mqtt_host, self.mqtt_port)
        self.mqtt.on_message = self._on_mqtt_message
        await self.mqtt.subscribe("signals/scalping")
        await self.mqtt.subscribe(f"orders/{self.bot_id}/execute")

        self.state = BotState.RUNNING
        logger.info(f"ScalpingBot {self.bot_id} initialized and running")

    async def run(self):
        """봇 메인 루프"""
        await self.initialize()

        try:
            while self.state == BotState.RUNNING:
                # 포지션 모니터링 (손절/익절 체크)
                if self.position:
                    await self._check_exit_conditions()

                # 잔고 업데이트
                await self._update_balance()

                await asyncio.sleep(5)  # 5초마다 체크

        except asyncio.CancelledError:
            logger.info("Bot loop cancelled")
        except Exception as e:
            logger.error(f"Bot error: {e}")
            self.state = BotState.ERROR
            raise

    async def stop(self):
        """봇 중지"""
        self.state = BotState.IDLE

        # 열린 포지션 정리
        if self.position:
            await self.close_position()

        await self.mqtt.disconnect()
        logger.info(f"ScalpingBot {self.bot_id} stopped")

    def _on_mqtt_message(self, client, topic, payload, qos, properties):
        """MQTT 메시지 처리"""
        try:
            msg = json.loads(payload.decode())
            logger.debug(f"Received message on {topic}: {msg}")

            if topic == "signals/scalping":
                asyncio.create_task(self._handle_signal(msg))
            elif topic == f"orders/{self.bot_id}/execute":
                asyncio.create_task(self._handle_manual_order(msg))

        except Exception as e:
            logger.error(f"Error handling MQTT message: {e}")

    async def _handle_signal(self, signal: Dict):
        """매매 신호 처리"""
        action = signal.get("action")
        symbol = signal.get("symbol")
        amount = signal.get("amount", 0.001)
        confidence = signal.get("confidence", 0.5)

        if symbol != self.symbol:
            return

        # 신뢰도가 낮으면 무시
        if confidence < 0.7:
            logger.info(f"Signal ignored due to low confidence: {confidence}")
            return

        logger.info(f"Processing signal: {action} {symbol} @ {signal.get('price')}")

        if action == "buy":
            await self.open_long(amount)
        elif action == "sell":
            if self.position and self.position.side == PositionSide.LONG:
                await self.close_position()
            else:
                await self.open_short(amount)

    async def _handle_manual_order(self, order: Dict):
        """수동 주문 처리"""
        action = order.get("action")
        amount = order.get("amount", 0.001)

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

            logger.info(f"Opened LONG position: {amount} {self.symbol} @ {price}")

            # 콜백 및 발행
            if self.on_position_change:
                self.on_position_change(self.position)
            await self._publish_trade(trade)

        except Exception as e:
            logger.error(f"Failed to open long position: {e}")

    async def open_short(self, amount: float):
        """숏 포지션 진입 (선물 거래 필요)"""
        logger.warning("Short selling not implemented in spot trading")

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

                if pnl > 0:
                    self.winning_trades += 1
                self.daily_pnl += pnl

                logger.info(f"Closed LONG position: {self.position.amount} {self.symbol} @ {exit_price}, PnL: {pnl:.4f}")

                # 콜백 및 발행
                if self.on_trade:
                    self.on_trade(trade)
                await self._publish_trade(trade)

            self.position = None

            if self.on_position_change:
                self.on_position_change(None)

        except Exception as e:
            logger.error(f"Failed to close position: {e}")

    async def _check_exit_conditions(self):
        """손절/익절 조건 체크"""
        if not self.position:
            return

        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            current_price = ticker["last"]

            # 미실현 손익 계산
            if self.position.side == PositionSide.LONG:
                pnl_pct = (current_price - self.position.entry_price) / self.position.entry_price
                self.position.unrealized_pnl = (current_price - self.position.entry_price) * self.position.amount

                # 손절
                if pnl_pct <= -self.stop_loss_pct:
                    logger.info(f"Stop loss triggered: {pnl_pct:.4%}")
                    await self.close_position()
                    return

                # 익절
                if pnl_pct >= self.take_profit_pct:
                    logger.info(f"Take profit triggered: {pnl_pct:.4%}")
                    await self.close_position()
                    return

            # 일일 최대 손실 체크
            if self.daily_pnl < -self.max_daily_loss:
                logger.warning("Daily max loss reached, stopping bot")
                await self.stop()

        except Exception as e:
            logger.error(f"Error checking exit conditions: {e}")

    async def _update_balance(self):
        """잔고 업데이트"""
        try:
            balance = self.exchange.fetch_balance()
            self.balance = balance["USDT"]["free"] if "USDT" in balance else 0.0
        except Exception as e:
            logger.error(f"Error updating balance: {e}")

    async def _publish_trade(self, trade: Trade):
        """거래 정보 MQTT 발행"""
        try:
            topic = f"trades/{self.bot_id}"
            payload = json.dumps(trade.to_dict())
            await self.mqtt.publish(topic, payload)
        except Exception as e:
            logger.error(f"Error publishing trade: {e}")

    def get_status(self) -> Dict:
        """봇 상태 반환"""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0

        return {
            "bot_id": self.bot_id,
            "state": self.state.value,
            "symbol": self.symbol,
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


async def main():
    """단독 실행용 메인 함수"""
    bot = ScalpingBot(
        bot_id="scalper_1",
        symbol="BTC/USDT",
        sandbox=True  # 테스트넷
    )

    # 콜백 설정
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
        print(f"   Daily PnL: {status['daily_pnl']:.4f} USDT")


if __name__ == "__main__":
    asyncio.run(main())

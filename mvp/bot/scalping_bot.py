"""
OZ_A2M 스캘핑 봇 (Scalping Bot)
제7부서 운영팀 - 실제 거래 실행

기능:
- 1분/5분 단위 스캘핑 전략
- MQTT를 통해 게이트웨이와 통신
- 리스크 관리 (손절/익절 자동 설정)
- 체결 리포트 실시간 전송
"""

import asyncio
import json
import os
import signal
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Optional

import paho.mqtt.client as mqtt
import structlog

# 로깅 설정
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
)
logger = structlog.get_logger()

# 설정
MQTT_HOST = os.getenv('MQTT_HOST', 'mqtt-broker')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
BOT_ID = os.getenv('BOT_ID', 'scalping_bot_001')
SYMBOL = os.getenv('SYMBOL', 'BTC/USDT')
TIMEFRAME = os.getenv('TIMEFRAME', '1m')

RISK_PER_TRADE = float(os.getenv('RISK_PER_TRADE', 0.01))  # 1%
STOP_LOSS_PCT = float(os.getenv('STOP_LOSS_PCT', 0.005))   # 0.5%
TAKE_PROFIT_PCT = float(os.getenv('TAKE_PROFIT_PCT', 0.01))  # 1%


@dataclass
class TradeSignal:
    """거래 신호 데이터 클래스"""
    bot_id: str
    symbol: str
    action: str  # BUY, SELL, HOLD
    price: float
    quantity: float
    timestamp: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Position:
    """포지션 데이터 클래스"""
    symbol: str
    entry_price: float
    quantity: float
    side: str  # LONG, SHORT
    stop_loss: float
    take_profit: float
    entry_time: str
    unrealized_pnl: float = 0.0


class ScalpingBot:
    """스캘핑 봇 메인 클래스"""

    def __init__(self):
        self.bot_id = BOT_ID
        self.symbol = SYMBOL
        self.timeframe = TIMEFRAME
        self.mqtt_client: Optional[mqtt.Client] = None
        self.position: Optional[Position] = None
        self.running = False
        self.price_history: list = []

    def on_connect(self, client, userdata, flags, rc, properties=None):
        """MQTT 연결 콜백"""
        if rc == 0:
            logger.info(f"Bot {self.bot_id} connected to MQTT")
            # 명령 구독
            client.subscribe(f"oz/a2m/command/{self.bot_id}")
            client.subscribe("oz/a2m/command/all")
        else:
            logger.error(f"MQTT connection failed: {rc}")

    def on_message(self, client, userdata, msg):
        """MQTT 메시지 콜백"""
        try:
            payload = json.loads(msg.payload.decode())
            logger.info(f"Command received: {payload}")
            self.handle_command(payload)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON received: {msg.payload}")

    def handle_command(self, command: Dict):
        """명령 처리"""
        cmd = command.get('command')

        if cmd == 'start':
            self.running = True
            logger.info("Bot started by command")
        elif cmd == 'stop':
            self.running = False
            logger.info("Bot stopped by command")
        elif cmd == 'emergency_stop':
            self.emergency_stop()
        elif cmd == 'close_position':
            self.close_position()

    def emergency_stop(self):
        """긴급 정지 - 모든 포지션 청산"""
        logger.warning("EMERGENCY STOP activated!")
        self.running = False
        if self.position:
            self.close_position(reason="emergency")

    def close_position(self, reason: str = "manual"):
        """포지션 청산"""
        if not self.position:
            return

        signal = TradeSignal(
            bot_id=self.bot_id,
            symbol=self.symbol,
            action="SELL" if self.position.side == "LONG" else "BUY",
            price=self.get_current_price(),
            quantity=self.position.quantity,
            timestamp=datetime.utcnow().isoformat(),
            reason=f"position_closed_{reason}"
        )

        self.publish_signal(signal)
        self.position = None
        logger.info(f"Position closed: {reason}")

    def get_current_price(self) -> float:
        """현재 가격 조회 (Mock)"""
        # TODO: 실제 거래소 API 연동
        return 50000.0 + (len(self.price_history) * 10)

    def calculate_indicators(self) -> Dict:
        """기술적 지표 계산"""
        if len(self.price_history) < 20:
            return {"signal": "HOLD", "strength": 0}

        # Simple Moving Average
        sma_5 = sum(self.price_history[-5:]) / 5
        sma_20 = sum(self.price_history[-20:]) / 20

        # RSI (간단한 버전)
        gains = []
        losses = []
        for i in range(1, min(15, len(self.price_history))):
            change = self.price_history[-i] - self.price_history[-(i+1)]
            if change > 0:
                gains.append(change)
            else:
                losses.append(abs(change))

        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        rs = avg_gain / avg_loss if avg_loss > 0 else 0
        rsi = 100 - (100 / (1 + rs))

        # 신호 생성
        signal = "HOLD"
        strength = 0

        if self.price_history[-1] > sma_5 > sma_20 and rsi < 70:
            signal = "BUY"
            strength = abs(rsi - 50) / 50
        elif self.price_history[-1] < sma_5 < sma_20 and rsi > 30:
            signal = "SELL"
            strength = abs(rsi - 50) / 50

        return {
            "signal": signal,
            "strength": strength,
            "sma_5": sma_5,
            "sma_20": sma_20,
            "rsi": rsi
        }

    def should_enter_position(self, indicators: Dict) -> bool:
        """포지션 진입 판단"""
        if self.position:
            return False
        return indicators["signal"] in ["BUY", "SELL"] and indicators["strength"] > 0.6

    def should_exit_position(self, current_price: float) -> bool:
        """포지션 청산 판단"""
        if not self.position:
            return False

        # 손절 확인
        if self.position.side == "LONG":
            if current_price <= self.position.stop_loss:
                return True
            if current_price >= self.position.take_profit:
                return True
        else:  # SHORT
            if current_price >= self.position.stop_loss:
                return True
            if current_price <= self.position.take_profit:
                return True

        return False

    def open_position(self, side: str, price: float):
        """포지션 오픈"""
        stop_loss = price * (1 - STOP_LOSS_PCT) if side == "LONG" else price * (1 + STOP_LOSS_PCT)
        take_profit = price * (1 + TAKE_PROFIT_PCT) if side == "LONG" else price * (1 - TAKE_PROFIT_PCT)

        self.position = Position(
            symbol=self.symbol,
            entry_price=price,
            quantity=0.01,  # TODO: 리스크 관리 기반 계산
            side=side,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=datetime.utcnow().isoformat()
        )

        signal = TradeSignal(
            bot_id=self.bot_id,
            symbol=self.symbol,
            action="BUY" if side == "LONG" else "SELL",
            price=price,
            quantity=self.position.quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            timestamp=datetime.utcnow().isoformat(),
            reason="scalping_signal"
        )

        self.publish_signal(signal)
        logger.info(f"Position opened: {side} at {price}")

    def publish_signal(self, signal: TradeSignal):
        """MQTT로 신호 발행"""
        if self.mqtt_client and self.mqtt_client.is_connected():
            topic = f"oz/a2m/signal/{self.bot_id}"
            payload = json.dumps(signal.to_dict())
            self.mqtt_client.publish(topic, payload, qos=1)
            logger.info(f"Signal published: {signal.action}")

    def publish_status(self):
        """상태 보고"""
        status = {
            "bot_id": self.bot_id,
            "symbol": self.symbol,
            "running": self.running,
            "has_position": self.position is not None,
            "position": asdict(self.position) if self.position else None,
            "timestamp": datetime.utcnow().isoformat()
        }

        if self.mqtt_client and self.mqtt_client.is_connected():
            topic = f"oz/a2m/status/{self.bot_id}"
            self.mqtt_client.publish(topic, json.dumps(status), qos=0)

    async def run(self):
        """메인 봇 루프"""
        # MQTT 연결
        self.mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.bot_id
        )
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message

        try:
            self.mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.error(f"Failed to connect MQTT: {e}")
            return

        self.running = True
        logger.info(f"Bot {self.bot_id} started")

        try:
            while self.running:
                # 가격 업데이트 (Mock)
                current_price = self.get_current_price()
                self.price_history.append(current_price)
                if len(self.price_history) > 100:
                    self.price_history = self.price_history[-50:]

                # 지표 계산
                indicators = self.calculate_indicators()

                # 포지션 관리
                if self.position:
                    if self.should_exit_position(current_price):
                        self.close_position(reason="tp_sl")
                else:
                    if self.should_enter_position(indicators):
                        side = "LONG" if indicators["signal"] == "BUY" else "SHORT"
                        self.open_position(side, current_price)

                # 상태 보고
                self.publish_status()

                # 대기
                await asyncio.sleep(60 if self.timeframe == "1m" else 300)

        except Exception as e:
            logger.error(f"Bot error: {e}")
        finally:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            logger.info(f"Bot {self.bot_id} stopped")


def signal_handler(signum, frame):
    """시그널 핸들러"""
    logger.info("Shutdown signal received")
    sys.exit(0)


async def main():
    """메인 함수"""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    bot = ScalpingBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())

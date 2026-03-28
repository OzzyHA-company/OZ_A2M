"""
OZ_A2M 트렌드 팔로워 봇 (Trend Following Bot)
제7부서 운영팀 - 추세 추종 전략

기능:
- EMA 교차 (EMA20 / EMA50) 추세 판단
- MACD 확인으로 추세 강도 검증
- MQTT를 통해 게이트웨이와 통신
- 리스크 관리 (동적 손절/익절)
"""

import asyncio
import json
import os
import signal
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Optional, List
from collections import deque

import paho.mqtt.client as mqtt
import structlog

# 로깅 설정
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),
)
logger = structlog.get_logger()

# 설정
MQTT_HOST = os.getenv('MQTT_HOST', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
BOT_ID = os.getenv('BOT_ID', 'trend_follower_001')
SYMBOL = os.getenv('SYMBOL', 'BTC/USDT')
TIMEFRAME = os.getenv('TIMEFRAME', '15m')

RISK_PER_TRADE = float(os.getenv('RISK_PER_TRADE', 0.02))  # 2%
STOP_LOSS_PCT = float(os.getenv('STOP_LOSS_PCT', 0.02))    # 2%
TAKE_PROFIT_PCT = float(os.getenv('TAKE_PROFIT_PCT', 0.06))  # 6% (1:3 RR)

# EMA 설정
EMA_FAST = int(os.getenv('EMA_FAST', 20))
EMA_SLOW = int(os.getenv('EMA_SLOW', 50))


@dataclass
class TradeSignal:
    """거래 신호 데이터 클래스"""
    bot_id: str
    symbol: str
    action: str  # BUY, SELL, CLOSE
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


class TrendFollowerBot:
    """
    트렌드 팔로워 봇

    전략:
    1. EMA 교차로 추세 방향 판단
       - EMA20 > EMA50: 상승 추세 (LONG)
       - EMA20 < EMA50: 하띟세 (SHORT)
    2. MACD로 추세 강도 확인
    3. 포지션 진입 후 추세 반전 시 청산
    """

    def __init__(self):
        self.bot_id = BOT_ID
        self.symbol = SYMBOL
        self.timeframe = TIMEFRAME
        self.mqtt_client: Optional[mqtt.Client] = None
        self.position: Optional[Position] = None
        self.running = False

        # 가격 데이터 저장
        self.price_history: deque = deque(maxlen=100)
        self.ema_fast_values: deque = deque(maxlen=EMA_SLOW + 10)
        self.ema_slow_values: deque = deque(maxlen=EMA_SLOW + 10)

        # EMA 계산용
        self.ema_fast_multiplier = 2 / (EMA_FAST + 1)
        self.ema_slow_multiplier = 2 / (EMA_SLOW + 1)
        self.ema_fast_current: Optional[float] = None
        self.ema_slow_current: Optional[float] = None

        # MACD
        self.macd_line: deque = deque(maxlen=26)
        self.signal_line: deque = deque(maxlen=26)
        self.macd_histogram: Optional[float] = None

    def calculate_ema(self, prices: List[float], period: int) -> float:
        """EMA 계산"""
        if len(prices) < period:
            return sum(prices) / len(prices) if prices else 0.0

        # 초기 SMA
        sma = sum(prices[:period]) / period
        multiplier = 2 / (period + 1)

        # EMA 계산
        ema = sma
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema

        return ema

    def calculate_macd(self, prices: List[float]) -> tuple:
        """MACD 계산 (12, 26, 9)"""
        if len(prices) < 26:
            return 0.0, 0.0, 0.0

        ema_12 = self.calculate_ema(prices[-26:], 12)
        ema_26 = self.calculate_ema(prices[-26:], 26)
        macd = ema_12 - ema_26

        self.macd_line.append(macd)

        # Signal line (EMA 9 of MACD)
        signal = 0.0
        if len(self.macd_line) >= 9:
            signal = self.calculate_ema(list(self.macd_line)[-9:], 9)

        histogram = macd - signal
        return macd, signal, histogram

    def analyze_trend(self) -> Dict[str, any]:
        """
        추세 분석

        Returns:
            {
                'direction': 'UP' | 'DOWN' | 'NEUTRAL',
                'strength': float (0.0 ~ 1.0),
                'ema_fast': float,
                'ema_slow': float,
                'macd': float,
                'signal': float,
                'histogram': float
            }
        """
        if len(self.price_history) < EMA_SLOW:
            return {'direction': 'NEUTRAL', 'strength': 0.0}

        prices = list(self.price_history)

        # EMA 계산
        ema_fast = self.calculate_ema(prices, EMA_FAST)
        ema_slow = self.calculate_ema(prices, EMA_SLOW)

        self.ema_fast_current = ema_fast
        self.ema_slow_current = ema_slow

        # MACD 계산
        macd, signal, histogram = self.calculate_macd(prices)
        self.macd_histogram = histogram

        # 추세 방향 판단
        if ema_fast > ema_slow:
            direction = 'UP'
            ema_diff = (ema_fast - ema_slow) / ema_slow
        elif ema_fast < ema_slow:
            direction = 'DOWN'
            ema_diff = (ema_slow - ema_fast) / ema_slow
        else:
            direction = 'NEUTRAL'
            ema_diff = 0.0

        # 추세 강도 (MACD 히스토그램 활용)
        macd_strength = min(abs(histogram) / (abs(macd) + 0.001), 1.0)
        ema_strength = min(ema_diff * 100, 1.0)  # 1% 차이 = 1.0

        strength = (macd_strength + ema_strength) / 2

        return {
            'direction': direction,
            'strength': strength,
            'ema_fast': ema_fast,
            'ema_slow': ema_slow,
            'macd': macd,
            'signal': signal,
            'histogram': histogram
        }

    def should_enter_long(self, trend: Dict) -> bool:
        """LONG 진입 조건"""
        return (
            trend['direction'] == 'UP' and
            trend['strength'] > 0.3 and
            trend['histogram'] > 0  # MACD 히스토그램 양수
        )

    def should_enter_short(self, trend: Dict) -> bool:
        """SHORT 진입 조건"""
        return (
            trend['direction'] == 'DOWN' and
            trend['strength'] > 0.3 and
            trend['histogram'] < 0  # MACD 히스토그램 음수
        )

    def should_close_position(self, trend: Dict) -> bool:
        """포지션 청산 조건"""
        if not self.position:
            return False

        # 추세 반전
        if self.position.side == 'LONG' and trend['direction'] == 'DOWN':
            return True
        if self.position.side == 'SHORT' and trend['direction'] == 'UP':
            return True

        # MACD 반전 신호
        if self.position.side == 'LONG' and trend['histogram'] < -0.1:
            return True
        if self.position.side == 'SHORT' and trend['histogram'] > 0.1:
            return True

        return False

    def on_connect(self, client, userdata, flags, rc, properties=None):
        """MQTT 연결 콜백"""
        if rc == 0:
            logger.info(f"TrendFollower {self.bot_id} connected to MQTT")
            client.subscribe(f"oz/a2m/command/{self.bot_id}")
            client.subscribe("oz/a2m/command/all")
            client.subscribe("oz/a2m/market/ohlcv")
        else:
            logger.error(f"MQTT connection failed: {rc}")

    def on_message(self, client, userdata, msg):
        """MQTT 메시지 콜백"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())

            if topic == "oz/a2m/market/ohlcv":
                self.handle_ohlcv(payload)
            elif topic == f"oz/a2m/command/{self.bot_id}":
                self.handle_command(payload)

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def handle_ohlcv(self, data: Dict):
        """OHLCV 데이터 처리"""
        symbol = data.get('symbol')
        if symbol != self.symbol:
            return

        close_price = data.get('close', 0)
        if close_price > 0:
            self.price_history.append(close_price)

        # 충분한 데이터 수집 후 분석
        if len(self.price_history) >= EMA_SLOW:
            self.evaluate_strategy()

    def evaluate_strategy(self):
        """전략 평가 및 신호 생성"""
        trend = self.analyze_trend()

        current_price = self.price_history[-1]

        # 포지션이 있으면 청산 확인
        if self.position:
            self.update_position_pnl(current_price)

            if self.should_close_position(trend):
                self.close_position(current_price, trend)
            return

        # 신규 진입 판단
        if self.should_enter_long(trend):
            self.enter_position('LONG', current_price, trend)
        elif self.should_enter_short(trend):
            self.enter_position('SHORT', current_price, trend)

    def enter_position(self, side: str, price: float, trend: Dict):
        """포지션 진입"""
        if self.position:
            return

        quantity = 0.1  # 기본 수량 (리스크 관리 필요)

        # 손절/익절 설정
        if side == 'LONG':
            stop_loss = price * (1 - STOP_LOSS_PCT)
            take_profit = price * (1 + TAKE_PROFIT_PCT)
        else:
            stop_loss = price * (1 + STOP_LOSS_PCT)
            take_profit = price * (1 - TAKE_PROFIT_PCT)

        self.position = Position(
            symbol=self.symbol,
            entry_price=price,
            quantity=quantity,
            side=side,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=datetime.now().isoformat()
        )

        # 신호 발행
        signal = TradeSignal(
            bot_id=self.bot_id,
            symbol=self.symbol,
            action='BUY' if side == 'LONG' else 'SELL',
            price=price,
            quantity=quantity,
            timestamp=datetime.now().isoformat(),
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason=f"Trend {trend['direction']} | EMA20:{trend['ema_fast']:.2f} | "
                   f"EMA50:{trend['ema_slow']:.2f} | MACD:{trend['histogram']:.4f}"
        )

        self.publish_signal(signal)
        logger.info(f"Position opened: {side} at {price}")

    def close_position(self, price: float, trend: Dict):
        """포지션 청산"""
        if not self.position:
            return

        # PnL 계산
        if self.position.side == 'LONG':
            pnl = (price - self.position.entry_price) * self.position.quantity
            pnl_pct = (price - self.position.entry_price) / self.position.entry_price
        else:
            pnl = (self.position.entry_price - price) * self.position.quantity
            pnl_pct = (self.position.entry_price - price) / self.position.entry_price

        # 신호 발행
        signal = TradeSignal(
            bot_id=self.bot_id,
            symbol=self.symbol,
            action='CLOSE',
            price=price,
            quantity=self.position.quantity,
            timestamp=datetime.now().isoformat(),
            reason=f"Trend reversal | PnL: {pnl:.2f} ({pnl_pct:.2%}) | "
                   f"EMA20:{trend['ema_fast']:.2f} | MACD:{trend['histogram']:.4f}"
        )

        self.publish_signal(signal)
        logger.info(f"Position closed: PnL={pnl:.2f}")

        self.position = None

    def update_position_pnl(self, current_price: float):
        """포지션 PnL 업데이트"""
        if not self.position:
            return

        if self.position.side == 'LONG':
            self.position.unrealized_pnl = (
                current_price - self.position.entry_price
            ) * self.position.quantity
        else:
            self.position.unrealized_pnl = (
                self.position.entry_price - current_price
            ) * self.position.quantity

    def publish_signal(self, signal: TradeSignal):
        """신호 발행"""
        if self.mqtt_client:
            self.mqtt_client.publish(
                f"oz/a2m/signals/{self.bot_id}",
                json.dumps(signal.to_dict())
            )

    def handle_command(self, command: Dict):
        """명령 처리"""
        cmd = command.get('command')
        logger.info(f"Received command: {cmd}")

        if cmd == 'stop':
            self.stop()
        elif cmd == 'status':
            self.publish_status()

    def publish_status(self):
        """상태 발행"""
        status = {
            'bot_id': self.bot_id,
            'status': 'running' if self.running else 'stopped',
            'symbol': self.symbol,
            'position': asdict(self.position) if self.position else None,
            'ema_fast': self.ema_fast_current,
            'ema_slow': self.ema_slow_current,
            'macd_histogram': self.macd_histogram,
            'timestamp': datetime.now().isoformat()
        }

        if self.mqtt_client:
            self.mqtt_client.publish(
                f"oz/a2m/status/{self.bot_id}",
                json.dumps(status)
            )

    def start(self):
        """봇 시작"""
        logger.info(f"Starting TrendFollower {self.bot_id}")

        self.mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message

        try:
            self.mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
            self.running = True

            # 상태 발행 루프
            while self.running:
                self.publish_status()
                asyncio.run(asyncio.sleep(5))

        except Exception as e:
            logger.error(f"Bot error: {e}")
        finally:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

    def stop(self):
        """봇 중지"""
        logger.info(f"Stopping TrendFollower {self.bot_id}")
        self.running = False


def signal_handler(sig, frame):
    """시그널 핸들러"""
    logger.info("Shutdown signal received")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    bot = TrendFollowerBot()
    bot.start()

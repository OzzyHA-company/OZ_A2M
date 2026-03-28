"""
Signal Generator - 시장 데이터 분석 및 매매 신호 생성
Phase 7 핵심 컴포넌트
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, Callable
from enum import Enum

import aiohttp
import pandas as pd
import numpy as np

from occore.logger import get_logger
from occore.messaging.mqtt_client import MQTTClient

logger = get_logger(__name__)


class SignalType(str, Enum):
    """신호 유형"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Signal:
    """매매 신호 데이터"""
    type: SignalType
    symbol: str
    price: float
    confidence: float  # 0.0 ~ 1.0
    indicators: Dict[str, float]
    timestamp: datetime
    strategy: str
    amount: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.type.value,
            "symbol": self.symbol,
            "price": self.price,
            "confidence": self.confidence,
            "indicators": self.indicators,
            "timestamp": self.timestamp.isoformat(),
            "strategy": self.strategy,
            "amount": self.amount
        }


class TechnicalAnalyzer:
    """기술적 분석 엔진"""

    @staticmethod
    def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        """RSI 계산"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def calculate_ma(prices: pd.Series, period: int) -> pd.Series:
        """이동평균 계산"""
        return prices.rolling(window=period).mean()

    @staticmethod
    def calculate_macd(
        prices: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> tuple:
        """MACD 계산"""
        ema_fast = prices.ewm(span=fast).mean()
        ema_slow = prices.ewm(span=slow).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal).mean()
        macd_hist = macd - macd_signal
        return macd, macd_signal, macd_hist

    @staticmethod
    def calculate_bollinger_bands(
        prices: pd.Series,
        period: int = 20,
        std_dev: float = 2.0
    ) -> tuple:
        """볼린저 밴드 계산"""
        ma = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()
        upper = ma + (std * std_dev)
        lower = ma - (std * std_dev)
        return upper, ma, lower


class SignalGenerator:
    """
    매매 신호 생성기

    기능:
    - 시장 데이터 수집
    - 기술적 분석 (RSI, MA, MACD, 볼린저 밴드)
    - 매매 신호 생성
    - MQTT 발행
    """

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        exchange: str = "binance",
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883
    ):
        self.symbol = symbol
        self.exchange = exchange
        self.analyzer = TechnicalAnalyzer()

        # MQTT 클라이언트
        self.mqtt = MQTTClient(client_id="signal_generator")
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port

        # 설정
        self.interval = "1m"  # 1분봉
        self.limit = 100  # 100개 데이터
        self.rsi_period = 14
        self.ma_short = 20
        self.ma_long = 50
        self.rsi_oversold = 30
        self.rsi_overbought = 70

        # 콜백
        self.on_signal: Optional[Callable[[Signal], None]] = None

        self._running = False
        logger.info(f"SignalGenerator initialized for {symbol}")

    async def start(self):
        """시그널 생성기 시작"""
        await self.mqtt.connect(self.mqtt_host, self.mqtt_port)
        self._running = True
        logger.info("SignalGenerator started")

        while self._running:
            try:
                await self._generate_cycle()
            except Exception as e:
                logger.error(f"Signal generation error: {e}")
            await asyncio.sleep(60)  # 1분마다 실행

    async def stop(self):
        """시그널 생성기 중지"""
        self._running = False
        await self.mqtt.disconnect()
        logger.info("SignalGenerator stopped")

    async def _generate_cycle(self):
        """한 사이클의 신호 생성"""
        # 데이터 수집
        df = await self._fetch_data()
        if df is None or len(df) < 50:
            logger.warning("Insufficient data for analysis")
            return

        # 분석
        signal = self._analyze(df)

        if signal and signal.type != SignalType.HOLD:
            logger.info(f"Signal generated: {signal.type.value} {signal.symbol} @ {signal.price}")

            # MQTT 발행
            await self._publish_signal(signal)

            # 콜백 실행
            if self.on_signal:
                self.on_signal(signal)

    async def _fetch_data(self) -> Optional[pd.DataFrame]:
        """Binance API에서 캔들스틱 데이터 수집"""
        try:
            symbol_clean = self.symbol.replace("/", "")
            url = f"https://api.binance.com/api/v3/klines"
            params = {
                "symbol": symbol_clean,
                "interval": self.interval,
                "limit": self.limit
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.error(f"API error: {resp.status}")
                        return None

                    data = await resp.json()

                    df = pd.DataFrame(data, columns=[
                        "timestamp", "open", "high", "low", "close",
                        "volume", "close_time", "quote_volume", "trades",
                        "taker_buy_base", "taker_buy_quote", "ignore"
                    ])

                    # 타입 변환
                    for col in ["open", "high", "low", "close", "volume"]:
                        df[col] = df[col].astype(float)

                    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

                    return df

        except Exception as e:
            logger.error(f"Data fetch error: {e}")
            return None

    def _analyze(self, df: pd.DataFrame) -> Optional[Signal]:
        """기술적 분석 및 신호 생성"""
        close = df["close"]

        # 지표 계산
        rsi = self.analyzer.calculate_rsi(close, self.rsi_period)
        ma20 = self.analyzer.calculate_ma(close, self.ma_short)
        ma50 = self.analyzer.calculate_ma(close, self.ma_long)
        macd, macd_signal, macd_hist = self.analyzer.calculate_macd(close)
        bb_upper, bb_middle, bb_lower = self.analyzer.calculate_bollinger_bands(close)

        # 최신 값
        last_price = close.iloc[-1]
        last_rsi = rsi.iloc[-1]
        last_ma20 = ma20.iloc[-1]
        last_ma50 = ma50.iloc[-1]
        last_macd = macd.iloc[-1]
        last_macd_signal = macd_signal.iloc[-1]
        last_bb_lower = bb_lower.iloc[-1]
        last_bb_upper = bb_upper.iloc[-1]

        if pd.isna(last_rsi) or pd.isna(last_ma20):
            return None

        # 신호 판단
        signal_type = SignalType.HOLD
        confidence = 0.5

        # 매수 조건
        buy_conditions = [
            last_rsi < self.rsi_oversold,  # RSI 과매도
            last_price > last_ma20,  # 단기 상승세
            last_ma20 > last_ma50,  # 골든크로스
            last_macd > last_macd_signal,  # MACD 상승
            last_price < last_bb_lower * 1.02  # 하단 밴드 근처
        ]

        # 매도 조건
        sell_conditions = [
            last_rsi > self.rsi_overbought,  # RSI 과매수
            last_price < last_ma20,  # 단기 하락세
            last_ma20 < last_ma50,  # 데드크로스
            last_macd < last_macd_signal,  # MACD 하락
            last_price > last_bb_upper * 0.98  # 상단 밴드 근처
        ]

        buy_score = sum(buy_conditions)
        sell_score = sum(sell_conditions)

        if buy_score >= 3:
            signal_type = SignalType.BUY
            confidence = 0.5 + (buy_score * 0.1)
        elif sell_score >= 3:
            signal_type = SignalType.SELL
            confidence = 0.5 + (sell_score * 0.1)

        # 신호가 없으면 None 반환
        if signal_type == SignalType.HOLD:
            return None

        return Signal(
            type=signal_type,
            symbol=self.symbol,
            price=last_price,
            confidence=min(confidence, 1.0),
            indicators={
                "rsi": last_rsi,
                "ma20": last_ma20,
                "ma50": last_ma50,
                "macd": last_macd,
                "macd_signal": last_macd_signal,
                "bb_lower": last_bb_lower,
                "bb_upper": last_bb_upper
            },
            timestamp=datetime.utcnow(),
            strategy="scalping_rsi_ma",
            amount=0.001  # 기본 거래량
        )

    async def _publish_signal(self, signal: Signal):
        """MQTT로 신호 발행"""
        try:
            topic = f"signals/{signal.strategy}"
            payload = json.dumps(signal.to_dict())
            await self.mqtt.publish(topic, payload)
            logger.debug(f"Published signal to {topic}")
        except Exception as e:
            logger.error(f"Failed to publish signal: {e}")


async def main():
    """단독 실행용 메인 함수"""
    generator = SignalGenerator(
        symbol="BTC/USDT",
        mqtt_host="localhost",
        mqtt_port=1883
    )

    # 신호 콜백
    def on_signal(signal: Signal):
        print(f"\n🚨 SIGNAL: {signal.type.value.upper()}")
        print(f"   Symbol: {signal.symbol}")
        print(f"   Price: {signal.price:.2f}")
        print(f"   Confidence: {signal.confidence:.1%}")
        print(f"   RSI: {signal.indicators.get('rsi', 0):.2f}")

    generator.on_signal = on_signal

    try:
        await generator.start()
    except KeyboardInterrupt:
        await generator.stop()


if __name__ == "__main__":
    asyncio.run(main())
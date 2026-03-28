"""
OZ_A2M Phase 5: 추세 추종 봇 (Trend Following Bot)

MACD + 추세선 기반 중기 보유 전략
상승/하락 추세를 따라 수익 추구
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Any

try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    pd = None
    np = None

from ..bot_manager import BaseBot
from ..models import BotConfig, BotStatus, OrderSide, PositionSide

logger = logging.getLogger(__name__)


class TrendFollowingBot(BaseBot):
    """
    추세 추종 봇

    전략:
    - MACD 골든크로스 + 가격 > EMA50 -> 매수 (상승추세 진입)
    - MACD 데드크로스 + 가격 < EMA50 -> 매도 (하락추세 진입)
    - ATR 기반 동적 손절/익절
    - 1시간 또는 4시간 봉 기준
    """

    DEFAULT_PARAMS = {
        "timeframe": "1h",          # 1시간봉
        "ema_fast": 12,             # MACD 단기
        "ema_slow": 26,             # MACD 장기
        "signal_period": 9,         # MACD 시그널
        "trend_ema": 50,            # 추세 EMA
        "atr_period": 14,           # ATR 기간
        "atr_multiplier_sl": 2.0,   # ATR 손절 배수
        "atr_multiplier_tp": 3.0,   # ATR 익절 배수
        "trade_amount": 0.01,       # 거래 수량
        "min_trend_strength": 0.5   # 최소 추세 강도
    }

    def __init__(self, config: BotConfig, engine, position_manager, risk_controller):
        super().__init__(config, engine, position_manager, risk_controller)
        self.params = {**self.DEFAULT_PARAMS, **config.strategy_params}
        self.current_position_id: Optional[str] = None
        self.entry_price: Optional[Decimal] = None
        self.stop_loss: Optional[Decimal] = None
        self.take_profit: Optional[Decimal] = None
        self.ohlcv_buffer: List[List] = []
        self.trend_direction: Optional[str] = None

    async def run(self):
        logger.info(f"TrendFollowingBot started: {self.config.symbol}")
        self._running = True
        while self._running and self.config.status == BotStatus.RUNNING:
            try:
                await self.tick()
                sleep_seconds = 3600 if self.params['timeframe'] == '1h' else 14400
                await asyncio.sleep(sleep_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"TrendFollowingBot error: {e}")
                await asyncio.sleep(60)

    async def tick(self):
        await self._update_data()
        signal = self._generate_signal()
        ticker = await self.engine.connector.get_ticker(self.config.symbol)
        current_price = ticker.get('last')
        if not current_price:
            return

        if self.current_position_id:
            await self._manage_position(current_price)
        else:
            if signal == "long":
                await self._enter_long(current_price)
            elif signal == "short":
                await self._enter_short(current_price)

    async def _update_data(self):
        ohlcv = await self.engine.connector.get_ohlcv(
            self.config.symbol, self.params['timeframe'], limit=100
        )
        if ohlcv:
            self.ohlcv_buffer = ohlcv

    def _generate_signal(self) -> Optional[str]:
        if not PANDAS_AVAILABLE or len(self.ohlcv_buffer) < 50:
            return None
        try:
            df = pd.DataFrame(self.ohlcv_buffer, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            for col in ['open', 'high', 'low', 'close']:
                df[col] = pd.to_numeric(df[col])

            # MACD
            ema_fast = df['close'].ewm(span=self.params['ema_fast']).mean()
            ema_slow = df['close'].ewm(span=self.params['ema_slow']).mean()
            df['macd'] = ema_fast - ema_slow
            df['signal'] = df['macd'].ewm(span=self.params['signal_period']).mean()
            df['histogram'] = df['macd'] - df['signal']

            # Trend EMA
            df['ema50'] = df['close'].ewm(span=self.params['trend_ema']).mean()

            # ATR
            high_low = df['high'] - df['low']
            high_close = abs(df['high'] - df['close'].shift())
            low_close = abs(df['low'] - df['close'].shift())
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            true_range = ranges.max(axis=1)
            df['atr'] = true_range.rolling(self.params['atr_period']).mean()

            last = df.iloc[-1]
            prev = df.iloc[-2]

            if pd.isna(last['macd']) or pd.isna(last['ema50']):
                return None

            # Golden Cross + Price > EMA50
            if prev['macd'] < prev['signal'] and last['macd'] > last['signal']:
                if last['close'] > last['ema50']:
                    self.trend_direction = "up"
                    return "long"

            # Dead Cross + Price < EMA50
            if prev['macd'] > prev['signal'] and last['macd'] < last['signal']:
                if last['close'] < last['ema50']:
                    self.trend_direction = "down"
                    return "short"

        except Exception as e:
            logger.error(f"Signal generation error: {e}")
        return None

    async def _enter_long(self, price: Decimal):
        logger.info(f"Trend: Entering LONG {self.config.symbol} @ {price}")
        atr = self._get_last_atr()
        if atr:
            self.stop_loss = price - Decimal(str(atr)) * Decimal(str(self.params['atr_multiplier_sl']))
            self.take_profit = price + Decimal(str(atr)) * Decimal(str(self.params['atr_multiplier_tp']))

        position = await self.position_manager.open_position(
            symbol=self.config.symbol, side=PositionSide.LONG,
            amount=Decimal(str(self.params['trade_amount'])),
            exchange=self.config.exchange, bot_id=self.config.id
        )
        if position:
            self.current_position_id = position.id
            self.entry_price = position.entry_price
            logger.info(f"LONG entered. SL: {self.stop_loss}, TP: {self.take_profit}")

    async def _enter_short(self, price: Decimal):
        logger.info(f"Trend: Entering SHORT {self.config.symbol} @ {price}")
        atr = self._get_last_atr()
        if atr:
            self.stop_loss = price + Decimal(str(atr)) * Decimal(str(self.params['atr_multiplier_sl']))
            self.take_profit = price - Decimal(str(atr)) * Decimal(str(self.params['atr_multiplier_tp']))

        position = await self.position_manager.open_position(
            symbol=self.config.symbol, side=PositionSide.SHORT,
            amount=Decimal(str(self.params['trade_amount'])),
            exchange=self.config.exchange, bot_id=self.config.id
        )
        if position:
            self.current_position_id = position.id
            self.entry_price = position.entry_price
            logger.info(f"SHORT entered. SL: {self.stop_loss}, TP: {self.take_profit}")

    async def _manage_position(self, current_price: Decimal):
        if not self.current_position_id:
            return
        position = await self.position_manager.get_position(self.current_position_id)
        if not position or position.side == PositionSide.NONE:
            self._reset_position()
            return

        # Check SL/TP
        if position.side == PositionSide.LONG:
            if self.stop_loss and current_price <= self.stop_loss:
                logger.info("Long SL hit")
                await self._close_position()
            elif self.take_profit and current_price >= self.take_profit:
                logger.info("Long TP hit")
                await self._close_position()
        else:
            if self.stop_loss and current_price >= self.stop_loss:
                logger.info("Short SL hit")
                await self._close_position()
            elif self.take_profit and current_price <= self.take_profit:
                logger.info("Short TP hit")
                await self._close_position()

    async def _close_position(self):
        if self.current_position_id:
            await self.position_manager.close_position(self.current_position_id)
            self._reset_position()

    def _reset_position(self):
        self.current_position_id = None
        self.entry_price = None
        self.stop_loss = None
        self.take_profit = None

    def _get_last_atr(self) -> Optional[float]:
        if not PANDAS_AVAILABLE or len(self.ohlcv_buffer) < 20:
            return None
        try:
            df = pd.DataFrame(self.ohlcv_buffer, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            for col in ['high', 'low', 'close']:
                df[col] = pd.to_numeric(df[col])
            high_low = df['high'] - df['low']
            high_close = abs(df['high'] - df['close'].shift())
            low_close = abs(df['low'] - df['close'].shift())
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            true_range = ranges.max(axis=1)
            atr = true_range.rolling(self.params['atr_period']).mean().iloc[-1]
            return float(atr) if not pd.isna(atr) else None
        except:
            return None

    def get_status(self) -> Dict[str, Any]:
        return {"strategy": "trend_following", "trend": self.trend_direction,
                "has_position": self.current_position_id is not None}


if __name__ == "__main__":
    print("TrendFollowingBot template loaded")

"""
OZ_A2M Scalping Strategy for Department 7.

This is a high-frequency scalping strategy optimized for 5-minute candles.
Uses RSI, EMA, and Volume indicators for entry/exit signals.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd
import talib.abstract as ta
from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
from pandas import DataFrame

logger = logging.getLogger(__name__)


class OZScalpingStrategy(IStrategy):
    """
    OZ_A2M Scalping Strategy.

    Optimized for:
    - 5-minute timeframe
    - Major pairs (BTC, ETH, etc.)
    - Quick entries/exits (2-4% target)
    - Tight stop-loss (2%)
    """

    # Strategy metadata
    INTERFACE_VERSION = 3

    # Minimal ROI designed for quick scalping
    minimal_roi = {
        "0": 0.04,    # 4% profit at 0 minutes
        "30": 0.02,   # 2% profit after 30 minutes
        "60": 0.01,   # 1% profit after 60 minutes
        "120": 0      # Exit at breakeven after 120 minutes
    }

    # Stoploss: 2% (aggressive scalping)
    stoploss = -0.02

    # Trailing stop
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    # Timeframe
    timeframe = '5m'

    # Run "populate_indicators" only for new candle
    process_only_new_candles = True

    # These values can be overridden in the config
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # Number of candles the strategy requires to keep
    startup_candle_count: int = 30

    # Hyperopt parameters
    buy_rsi = IntParameter(10, 40, default=30, space="buy")
    buy_fast_ema_period = IntParameter(5, 20, default=9, space="buy")
    buy_slow_ema_period = IntParameter(15, 50, default=21, space="buy")

    sell_rsi = IntParameter(60, 90, default=70, space="sell")
    sell_fast_ema_period = IntParameter(5, 20, default=9, space="sell")

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Add technical indicators to the dataframe."""

        # RSI
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)

        # EMA
        dataframe['ema9'] = ta.EMA(dataframe, timeperiod=9)
        dataframe['ema21'] = ta.EMA(dataframe, timeperiod=21)
        dataframe['ema50'] = ta.EMA(dataframe, timeperiod=50)

        # MACD
        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']

        # Volume
        dataframe['volume_mean'] = dataframe['volume'].rolling(window=20).mean()
        dataframe['volume_ratio'] = dataframe['volume'] / dataframe['volume_mean']

        # Bollinger Bands
        bollinger = ta.BBANDS(dataframe, timeperiod=20)
        dataframe['bb_lower'] = bollinger['lowerband']
        dataframe['bb_middle'] = bollinger['middleband']
        dataframe['bb_upper'] = bollinger['upperband']
        dataframe['bb_width'] = (dataframe['bb_upper'] - dataframe['bb_lower']) / dataframe['bb_middle']

        # ATR for volatility
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Define entry conditions."""
        conditions = []

        # Condition 1: RSI oversold
        conditions.append(dataframe['rsi'] < self.buy_rsi.value)

        # Condition 2: EMA crossover (fast > slow)
        conditions.append(dataframe['ema9'] > dataframe['ema21'])

        # Condition 3: Price above EMA50 (uptrend)
        conditions.append(dataframe['close'] > dataframe['ema50'])

        # Condition 4: MACD bullish
        conditions.append(dataframe['macd'] > dataframe['macdsignal'])

        # Condition 5: Volume confirmation
        conditions.append(dataframe['volume_ratio'] > 1.2)

        # Condition 6: Price near lower BB (mean reversion)
        conditions.append(dataframe['close'] < dataframe['bb_lower'] * 1.02)

        if conditions:
            dataframe.loc[
                pd.concat(conditions, axis=1).all(axis=1),
                'enter_long'] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Define exit conditions."""
        conditions = []

        # Condition 1: RSI overbought
        conditions.append(dataframe['rsi'] > self.sell_rsi.value)

        # Condition 2: EMA crossover (fast < slow)
        conditions.append(dataframe['ema9'] < dataframe['ema21'])

        # Condition 3: MACD bearish
        conditions.append(dataframe['macd'] < dataframe['macdsignal'])

        # Condition 4: Price near upper BB
        conditions.append(dataframe['close'] > dataframe['bb_upper'] * 0.98)

        if conditions:
            dataframe.loc[
                pd.concat(conditions, axis=1).all(axis=1),
                'exit_long'] = 1

        return dataframe

    def leverage(self, pair: str, current_time, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: Optional[str], side: str,
                 **kwargs) -> float:
        """Define leverage - 1x for spot trading."""
        return 1.0

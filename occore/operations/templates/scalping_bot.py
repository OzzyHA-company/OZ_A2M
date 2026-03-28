"""
OZ_A2M Phase 5: 스캘핑 봇 (Scalping Bot)

RSI + 이동평균 기반 1분/5분 단타 전략
빠른 진입/청산으로 소규모 수익 추구
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
from ..models import (
    BotConfig, BotStatus, OrderSide, PositionSide,
    RiskLimit, DailyStats
)

logger = logging.getLogger(__name__)


class ScalpingBot(BaseBot):
    """
    스캘핑 봇

    전략:
    - RSI 과매도(<30) + 가격 > MA20 -> 매수
    - RSI 과매수(>70) + 가격 < MA20 -> 매도
    - 1분 또는 5분 봉 기준
    - 빠른 청산 (수익 0.5% 또는 손실 0.3%)
    """

    DEFAULT_PARAMS = {
        "timeframe": "1m",          # 1분봉
        "rsi_period": 14,           # RSI 기간
        "ma_period": 20,            # 이동평균 기간
        "rsi_oversold": 30,         # RSI 과매도
        "rsi_overbought": 70,       # RSI 과매수
        "take_profit_pct": 0.5,     # 익절 %
        "stop_loss_pct": 0.3,       # 손절 %
        "max_position_time": 300,   # 최대 보유 시간 (초)
        "trade_amount": 0.001,      # 거래 수량 (BTC)
        "cooldown_seconds": 60      # 재진입 쿨다운
    }

    def __init__(self, config: BotConfig, engine, position_manager, risk_controller):
        super().__init__(config, engine, position_manager, risk_controller)

        # 전략 파라미터
        self.params = {**self.DEFAULT_PARAMS, **config.strategy_params}

        # 상태
        self.last_signal: Optional[str] = None
        self.last_trade_time: Optional[datetime] = None
        self.current_position_id: Optional[str] = None
        self.entry_price: Optional[Decimal] = None
        self.position_start_time: Optional[datetime] = None

        # 데이터 버퍼
        self.ohlcv_buffer: List[List] = []
        self.max_buffer_size = 100

    async def run(self):
        """봇 실행"""
        logger.info(f"ScalpingBot started: {self.config.symbol} ({self.params['timeframe']})")
        self._running = True

        while self._running and self.config.status == BotStatus.RUNNING:
            try:
                await self.tick()

                # 타임프레임에 따른 대기
                sleep_seconds = 60 if self.params['timeframe'] == '1m' else 300
                await asyncio.sleep(sleep_seconds)

            except asyncio.CancelledError:
                logger.info("ScalpingBot cancelled")
                break
            except Exception as e:
                logger.error(f"ScalpingBot error: {e}")
                await asyncio.sleep(10)

    async def tick(self):
        """틱 처리 - 주기적 실행"""
        # 현재가 조회
        ticker = await self.engine.connector.get_ticker(self.config.symbol)
        current_price = ticker.get('last')

        if not current_price:
            logger.warning("Failed to get current price")
            return

        # OHLCV 데이터 수집
        await self._update_data()

        # 포지션 관리
        if self.current_position_id:
            await self._manage_position(current_price)
        else:
            await self._check_entry(current_price)

    async def _update_data(self):
        """OHLCV 데이터 업데이트"""
        ohlcv = await self.engine.connector.get_ohlcv(
            self.config.symbol,
            self.params['timeframe'],
            limit=self.params['ma_period'] + 10
        )

        if ohlcv:
            self.ohlcv_buffer = ohlcv[-self.max_buffer_size:]

    async def _check_entry(self, current_price: Decimal):
        """진입 조건 확인"""
        # 쿨다운 체크
        if self.last_trade_time:
            elapsed = (datetime.utcnow() - self.last_trade_time).total_seconds()
            if elapsed < self.params['cooldown_seconds']:
                return

        # 데이터 부족
        if len(self.ohlcv_buffer) < self.params['ma_period']:
            return

        # 신호 생성
        signal = self._generate_signal()

        if signal == "buy":
            await self._enter_long(current_price)
        elif signal == "sell":
            await self._enter_short(current_price)

    def _generate_signal(self) -> Optional[str]:
        """매매 신호 생성"""
        if not PANDAS_AVAILABLE or len(self.ohlcv_buffer) < self.params['rsi_period'] + 5:
            return None

        try:
            # DataFrame 생성
            df = pd.DataFrame(
                self.ohlcv_buffer,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['close'] = pd.to_numeric(df['close'])

            # RSI 계산
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0).rolling(window=self.params['rsi_period']).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=self.params['rsi_period']).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))

            # 이동평균 계산
            df['ma'] = df['close'].rolling(window=self.params['ma_period']).mean()

            # 마지막 값
            last_rsi = df['rsi'].iloc[-1]
            last_price = df['close'].iloc[-1]
            last_ma = df['ma'].iloc[-1]

            if pd.isna(last_rsi) or pd.isna(last_ma):
                return None

            # 매수 신호: RSI 과매도 + 가격 > MA
            if last_rsi < self.params['rsi_oversold'] and last_price > last_ma:
                self.last_signal = "buy"
                return "buy"

            # 매도 신호: RSI 과매수 + 가격 < MA
            if last_rsi > self.params['rsi_overbought'] and last_price < last_ma:
                self.last_signal = "sell"
                return "sell"

        except Exception as e:
            logger.error(f"Signal generation error: {e}")

        return None

    async def _enter_long(self, price: Decimal):
        """롱 포지션 진입"""
        logger.info(f"Entering LONG: {self.config.symbol} @ {price}")

        # 리스크 검사
        from ...models import Order
        order = Order(
            id="",
            order_id=None,
            symbol=self.config.symbol,
            side=OrderSide.BUY,
            order_type=OrderSide.BUY,  # market
            amount=Decimal(str(self.params['trade_amount'])),
            bot_id=self.config.id
        )

        allowed, reason = await self.risk_controller.check_order_risk(order)
        if not allowed:
            logger.warning(f"Entry rejected by risk controller: {reason}")
            return

        # 포지션 진입
        position = await self.position_manager.open_position(
            symbol=self.config.symbol,
            side=PositionSide.LONG,
            amount=Decimal(str(self.params['trade_amount'])),
            exchange=self.config.exchange,
            bot_id=self.config.id
        )

        if position:
            self.current_position_id = position.id
            self.entry_price = position.entry_price
            self.position_start_time = datetime.utcnow()
            self.last_trade_time = datetime.utcnow()

            # 주문 카운터 증가
            self.risk_controller.increment_order_counter(self.config.id)

            logger.info(f"LONG position opened: {position.id}")

    async def _enter_short(self, price: Decimal):
        """숏 포지션 진입"""
        logger.info(f"Entering SHORT: {self.config.symbol} @ {price}")

        # 리스크 검사
        from ...models import Order
        order = Order(
            id="",
            order_id=None,
            symbol=self.config.symbol,
            side=OrderSide.SELL,
            order_type=OrderSide.SELL,
            amount=Decimal(str(self.params['trade_amount'])),
            bot_id=self.config.id
        )

        allowed, reason = await self.risk_controller.check_order_risk(order)
        if not allowed:
            logger.warning(f"Entry rejected by risk controller: {reason}")
            return

        # 포지션 진입
        position = await self.position_manager.open_position(
            symbol=self.config.symbol,
            side=PositionSide.SHORT,
            amount=Decimal(str(self.params['trade_amount'])),
            exchange=self.config.exchange,
            bot_id=self.config.id
        )

        if position:
            self.current_position_id = position.id
            self.entry_price = position.entry_price
            self.position_start_time = datetime.utcnow()
            self.last_trade_time = datetime.utcnow()

            # 주문 카운터 증가
            self.risk_controller.increment_order_counter(self.config.id)

            logger.info(f"SHORT position opened: {position.id}")

    async def _manage_position(self, current_price: Decimal):
        """포지션 관리 (익절/손절)"""
        if not self.entry_price or not self.current_position_id:
            return

        position = await self.position_manager.get_position(self.current_position_id)
        if not position or position.side == PositionSide.NONE:
            self.current_position_id = None
            self.entry_price = None
            self.position_start_time = None
            return

        # 수익률 계산
        if position.side == PositionSide.LONG:
            pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
        else:
            pnl_pct = (self.entry_price - current_price) / self.entry_price * 100

        # 익절 조건
        if pnl_pct >= self.params['take_profit_pct']:
            logger.info(f"Take profit triggered: {pnl_pct:.2f}%")
            await self._close_position()
            return

        # 손절 조건
        if pnl_pct <= -self.params['stop_loss_pct']:
            logger.info(f"Stop loss triggered: {pnl_pct:.2f}%")
            await self._close_position()
            return

        # 시간 제한
        if self.position_start_time:
            elapsed = (datetime.utcnow() - self.position_start_time).total_seconds()
            if elapsed >= self.params['max_position_time']:
                logger.info(f"Time limit reached: {elapsed}s")
                await self._close_position()
                return

    async def _close_position(self):
        """포지션 청산"""
        if not self.current_position_id:
            return

        pnl = await self.position_manager.close_position(self.current_position_id)

        if pnl is not None:
            logger.info(f"Position closed with PnL: {pnl}")

        self.current_position_id = None
        self.entry_price = None
        self.position_start_time = None
        self.last_trade_time = datetime.utcnow()

    def get_status(self) -> Dict[str, Any]:
        """봇 상태 조회"""
        return {
            "strategy": "scalping",
            "symbol": self.config.symbol,
            "timeframe": self.params['timeframe'],
            "last_signal": self.last_signal,
            "has_position": self.current_position_id is not None,
            "position_id": self.current_position_id,
            "entry_price": str(self.entry_price) if self.entry_price else None,
            "data_points": len(self.ohlcv_buffer)
        }


if __name__ == "__main__":
    # 테스트
    print("ScalpingBot template loaded")
    print(f"Default params: {ScalpingBot.DEFAULT_PARAMS}")

"""
OZ_A2M Phase 5: 차익거래 봇 (Arbitrage Bot)

거래소 간 가격 차익 전략
두 거래소의 가격 차이를 이용한 무위험 수익 추구
"""

import asyncio
import logging
from decimal import Decimal
from typing import Dict, Optional, Any

from ..bot_manager import BaseBot
from ..models import BotConfig, BotStatus, OrderSide
from ..exchange_connector import ExchangeConnector

logger = logging.getLogger(__name__)


class ArbitrageBot(BaseBot):
    """
    차익거래 봇

    전략:
    - 두 거래소 간 가격 차이 모니터링
    - 차이가 min_spread_pct 이상일 때 진입
    - 저가 거래소에서 매수, 고가 거래소에서 매도
    - 동시 체결로 가격 리스크 최소화
    """

    DEFAULT_PARAMS = {
        "exchange_a": "binance",
        "exchange_b": "bybit",
        "min_spread_pct": 0.3,      # 최소 차익 %
        "trade_amount": 0.001,      # 거래 수량
        "max_slippage_pct": 0.1     # 최대 슬리피지
    }

    def __init__(self, config: BotConfig, engine, position_manager, risk_controller):
        super().__init__(config, engine, position_manager, risk_controller)
        self.params = {**self.DEFAULT_PARAMS, **config.strategy_params}
        self.connector_a: Optional[ExchangeConnector] = None
        self.connector_b: Optional[ExchangeConnector] = None
        self.last_spread: Optional[Decimal] = None
        self.trade_count = 0

    async def run(self):
        logger.info(f"ArbitrageBot started: {self.params['exchange_a']} vs {self.params['exchange_b']}")
        self._running = True

        # 두 거래소 연결
        self.connector_a = ExchangeConnector(
            self.params['exchange_a'], sandbox=self.engine.connector.sandbox
        )
        self.connector_b = ExchangeConnector(
            self.params['exchange_b'], sandbox=self.engine.connector.sandbox
        )
        await self.connector_a.connect()
        await self.connector_b.connect()

        while self._running and self.config.status == BotStatus.RUNNING:
            try:
                await self.tick()
                await asyncio.sleep(5)  # 5초마다 체크
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"ArbitrageBot error: {e}")
                await asyncio.sleep(10)

        await self.connector_a.disconnect()
        await self.connector_b.disconnect()

    async def tick(self):
        if not self.connector_a or not self.connector_b:
            return

        # 두 거래소 가격 조회
        ticker_a = await self.connector_a.get_ticker(self.config.symbol)
        ticker_b = await self.connector_b.get_ticker(self.config.symbol)

        price_a = ticker_a.get('last')
        price_b = ticker_b.get('last')

        if not price_a or not price_b:
            return

        # 스프레드 계산
        spread = abs(price_a - price_b)
        spread_pct = spread / ((price_a + price_b) / 2) * 100
        self.last_spread = spread_pct

        if spread_pct >= self.params['min_spread_pct']:
            logger.info(f"Arbitrage opportunity: {spread_pct:.3f}%")

            # 저가에서 매수, 고가에서 매도
            if price_a < price_b:
                buy_exchange = self.params['exchange_a']
                sell_exchange = self.params['exchange_b']
                buy_price = price_a
                sell_price = price_b
            else:
                buy_exchange = self.params['exchange_b']
                sell_exchange = self.params['exchange_a']
                buy_price = price_b
                sell_price = price_a

            await self._execute_arbitrage(
                buy_exchange, sell_exchange, buy_price, sell_price
            )

    async def _execute_arbitrage(self, buy_ex: str, sell_ex: str, buy_p: Decimal, sell_p: Decimal):
        """차익거래 실행"""
        amount = Decimal(str(self.params['trade_amount']))

        # 동시 주문
        logger.info(f"Executing arb: Buy {buy_ex} @ {buy_p}, Sell {sell_ex} @ {sell_p}")

        # 리스크 체크
        from ...models import Order
        test_order = Order(id="", order_id=None, symbol=self.config.symbol,
                           side=OrderSide.BUY, order_type=OrderSide.BUY, amount=amount)
        allowed, reason = await self.risk_controller.check_order_risk(test_order)
        if not allowed:
            logger.warning(f"Arbitrage rejected: {reason}")
            return

        # 모의 실행
        if self.engine.dry_run:
            profit = (sell_p - buy_p) * amount
            logger.info(f"Arbitrage executed (dry): Profit ~{profit}")
            self.trade_count += 1

    def get_status(self) -> Dict[str, Any]:
        return {
            "strategy": "arbitrage",
            "exchanges": [self.params['exchange_a'], self.params['exchange_b']],
            "last_spread_pct": float(self.last_spread) if self.last_spread else None,
            "trade_count": self.trade_count
        }


if __name__ == "__main__":
    print("ArbitrageBot template loaded")

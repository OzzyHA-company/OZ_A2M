"""
OZ_A2M Phase 5: 시장조성 봇 (Market Making Bot)

스프레드 기반 시장조성 전략
Bid/Ask 양쪽에 주문을 걸어 스프레드 수익 추구
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any

from ..bot_manager import BaseBot
from ..models import BotConfig, BotStatus, OrderSide, OrderType, Order

logger = logging.getLogger(__name__)


class MarketMakingBot(BaseBot):
    """
    시장조성 봇

    전략:
    - Bid/Ask 양쪽에 지정가 주문 배치
    - 스프레드의 X%를 수익으로 설정
    - 주문이 체결되면 반대편 재주문
    - 인벤토리 헤지로 방향성 리스크 관리
    """

    DEFAULT_PARAMS = {
        "spread_pct": 0.1,          # 목표 스프레드 %
        "order_size": 0.001,        # 주문 크기
        "max_inventory": 0.01,      # 최대 인벤토리
        "rebalance_threshold": 0.5, # 재조정 임계값
        "order_refresh_sec": 30     # 주문 갱신 주기
    }

    def __init__(self, config: BotConfig, engine, position_manager, risk_controller):
        super().__init__(config, engine, position_manager, risk_controller)
        self.params = {**self.DEFAULT_PARAMS, **config.strategy_params}
        self.bid_order_id: Optional[str] = None
        self.ask_order_id: Optional[str] = None
        self.inventory: Decimal = Decimal("0")  # 포지션 (양수=롱, 음수=숏)
        self.last_mid_price: Optional[Decimal] = None

    async def run(self):
        logger.info(f"MarketMakingBot started: {self.config.symbol}")
        self._running = True
        while self._running and self.config.status == BotStatus.RUNNING:
            try:
                await self.tick()
                await asyncio.sleep(self.params['order_refresh_sec'])
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"MarketMakingBot error: {e}")
                await asyncio.sleep(5)

    async def tick(self):
        ticker = await self.engine.connector.get_ticker(self.config.symbol)
        bid = ticker.get('bid')
        ask = ticker.get('ask')
        if not bid or not ask:
            return

        mid_price = (bid + ask) / 2
        self.last_mid_price = mid_price

        spread = mid_price * Decimal(str(self.params['spread_pct'] / 100))
        target_bid = mid_price - spread
        target_ask = mid_price + spread

        # 취소 후 재주문
        await self._update_orders(target_bid, target_ask)

    async def _update_orders(self, bid_price: Decimal, ask_price: Decimal):
        order_size = Decimal(str(self.params['order_size']))
        max_inv = Decimal(str(self.params['max_inventory']))

        # Bid 주문 (매수) - 인벤토리가 너무 많으면 중단
        if self.inventory < max_inv:
            if self.bid_order_id:
                await self.engine.cancel_order(self.bid_order_id)
            bid_order = await self.engine.place_limit_order(
                symbol=self.config.symbol, side=OrderSide.BUY,
                amount=order_size, price=bid_price, bot_id=self.config.id
            )
            self.bid_order_id = bid_order.id
        else:
            if self.bid_order_id:
                await self.engine.cancel_order(self.bid_order_id)
                self.bid_order_id = None

        # Ask 주문 (매도) - 인벤토리가 너무 적으면 중단
        if self.inventory > -max_inv:
            if self.ask_order_id:
                await self.engine.cancel_order(self.ask_order_id)
            ask_order = await self.engine.place_limit_order(
                symbol=self.config.symbol, side=OrderSide.SELL,
                amount=order_size, price=ask_price, bot_id=self.config.id
            )
            self.ask_order_id = ask_order.id
        else:
            if self.ask_order_id:
                await self.engine.cancel_order(self.ask_order_id)
                self.ask_order_id = None

        # 주문 카운터
        self.risk_controller.increment_order_counter(self.config.id)

    def get_status(self) -> Dict[str, Any]:
        return {
            "strategy": "market_making",
            "inventory": str(self.inventory),
            "mid_price": str(self.last_mid_price) if self.last_mid_price else None,
            "bid_order": self.bid_order_id,
            "ask_order": self.ask_order_id
        }


if __name__ == "__main__":
    print("MarketMakingBot template loaded")

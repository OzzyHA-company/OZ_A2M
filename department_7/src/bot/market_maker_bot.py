"""
Market Maker Bot

오더북 기반 시장 조성 봇
- 스프레드 조정
- 인벤토리 관리
- 리스크 제한
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

import aiohttp

from lib.core.logger import get_logger
from lib.core.tracer import get_tracer, trace_function

logger = get_logger(__name__)
tracer = get_tracer("market_maker_bot")


@dataclass
class OrderBook:
    """오더북 데이터"""
    symbol: str
    bids: List[Tuple[float, float]]  # (price, volume)
    asks: List[Tuple[float, float]]  # (price, volume)
    timestamp: datetime

    @property
    def best_bid(self) -> float:
        return self.bids[0][0] if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0][0] if self.asks else 0.0

    @property
    def mid_price(self) -> float:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return 0.0

    @property
    def spread(self) -> float:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return 0.0

    @property
    def spread_percent(self) -> float:
        mid = self.mid_price
        if mid > 0:
            return (self.spread / mid) * 100
        return 0.0


@dataclass
class Inventory:
    """인벤토리 상태"""
    base_asset: float  # BTC 등
    quote_asset: float  # USDT 등
    base_value: float  # 기준자산 가치 (quote 단위)

    @property
    def total_value(self) -> float:
        return self.quote_asset + self.base_value

    @property
    def inventory_ratio(self) -> float:
        """인벤토리 비율 (0.0 ~ 1.0)"""
        total = self.total_value
        if total > 0:
            return self.base_value / total
        return 0.5


class MarketMakerBot:
    """
    시장 조성 봇

    기능:
    1. 오더북 모니터링
    2. 동적 스프레드 설정
    3. 인벤토리 헤지
    4. 리스크 관리
    """

    def __init__(
        self,
        bot_id: str = "market_maker_001",
        symbol: str = "BTC/USDT",
        exchange: str = "binance",
        # 스프레드 설정
        base_spread_bps: float = 10.0,  # 기본 스프레드 (0.1%)
        min_spread_bps: float = 5.0,    # 최소 스프레드
        max_spread_bps: float = 50.0,   # 최대 스프레드
        # 인벤토리 설정
        target_inventory_ratio: float = 0.5,  # 목표 비율
        max_inventory_ratio: float = 0.8,     # 최대 비율
        min_inventory_ratio: float = 0.2,     # 최소 비율
        # 주문 설정
        order_size: float = 0.01,  # BTC
        max_position: float = 1.0,  # 최대 포지션
        # 리스크 설정
        stop_loss_pct: float = 5.0,
    ):
        self.bot_id = bot_id
        self.symbol = symbol
        self.exchange = exchange

        # 스프레드 설정
        self.base_spread_bps = base_spread_bps
        self.min_spread_bps = min_spread_bps
        self.max_spread_bps = max_spread_bps

        # 인벤토리 설정
        self.target_inventory_ratio = target_inventory_ratio
        self.max_inventory_ratio = max_inventory_ratio
        self.min_inventory_ratio = min_inventory_ratio

        # 주문 설정
        self.order_size = order_size
        self.max_position = max_position
        self.stop_loss_pct = stop_loss_pct

        # 상태
        self.inventory = Inventory(0.0, 10000.0, 0.0)
        self.current_orders: Dict[str, Any] = {}
        self.running = False

        # 통계
        self.orders_placed = 0
        self.orders_filled = 0
        self.total_pnl = 0.0

        logger.info(f"MarketMakerBot initialized: {symbol} on {exchange}")

    def calculate_spread(self, orderbook: OrderBook) -> float:
        """
        동적 스프레드 계산

        인벤토리 비율에 따라 스프레드 조정
        - 인벤토리 많음 → 매도 스프레드 축소, 매수 스프레드 확대
        - 인벤토리 적음 → 매수 스프레드 축소, 매도 스프레드 확대
        """
        base_spread = self.base_spread_bps / 10000  # bps → decimal

        # 인벤토리 스큐 계산
        inventory_skew = self.inventory.inventory_ratio - self.target_inventory_ratio

        # 스프레드 조정 (인벤토리 불균형 시 페널티)
        skew_adjustment = abs(inventory_skew) * 0.001  # 최대 0.1% 추가

        adjusted_spread = base_spread + skew_adjustment

        # 최소/최대 제한
        min_spread = self.min_spread_bps / 10000
        max_spread = self.max_spread_bps / 10000

        return max(min_spread, min(max_spread, adjusted_spread))

    def calculate_quotes(self, orderbook: OrderBook) -> Optional[Dict[str, float]]:
        """
        매도/매수 호가 계산

        Returns:
            {"bid": price, "ask": price} 또는 None
        """
        mid = orderbook.mid_price
        if mid <= 0:
            return None

        spread = self.calculate_spread(orderbook)
        half_spread = spread / 2

        # 인벤토리 스큐 적용
        inventory_skew = self.inventory.inventory_ratio - self.target_inventory_ratio
        skew_adjustment = inventory_skew * half_spread

        bid_price = mid * (1 - half_spread - skew_adjustment)
        ask_price = mid * (1 + half_spread - skew_adjustment)

        return {
            "bid": round(bid_price, 2),
            "ask": round(ask_price, 2),
            "mid": mid,
            "spread_bps": spread * 10000,
        }

    def check_inventory_limits(self) -> Tuple[bool, str]:
        """
        인벤토리 한도 체크

        Returns:
            (통과여부, 메시지)
        """
        ratio = self.inventory.inventory_ratio

        if ratio > self.max_inventory_ratio:
            return False, f"인벤토리 과다: {ratio:.1%}"
        if ratio < self.min_inventory_ratio:
            return False, f"인벤토리 부족: {ratio:.1%}"

        return True, "OK"

    def check_position_limits(self, side: str) -> bool:
        """포지션 한도 체크"""
        if side == "buy":
            return self.inventory.base_asset < self.max_position
        else:
            return self.inventory.base_asset > -self.max_position
        return True

    @trace_function("market_maker_place_orders")
    async def place_orders(self, orderbook: OrderBook) -> Dict[str, Any]:
        """
        주문 배치

        Args:
            orderbook: 현재 오더북

        Returns:
            주문 결과
        """
        # 인벤토리 체크
        passed, message = self.check_inventory_limits()
        if not passed:
            logger.warning(f"Inventory limit: {message}")
            return {"status": "skipped", "reason": message}

        # 호가 계산
        quotes = self.calculate_quotes(orderbook)
        if not quotes:
            return {"status": "failed", "reason": "Invalid quotes"}

        # 주문 크기 결정
        bid_size = self.order_size
        ask_size = self.order_size

        # 인벤토리 스큐에 따라 크기 조정
        inventory_skew = self.inventory.inventory_ratio - self.target_inventory_ratio
        if inventory_skew > 0.1:
            # 인벤토리 많음 → 매수 축소, 매도 확대
            bid_size *= 0.5
            ask_size *= 1.5
        elif inventory_skew < -0.1:
            # 인벤토리 적음 → 매수 확대, 매도 축소
            bid_size *= 1.5
            ask_size *= 0.5

        # 주문 생성
        orders = []

        if self.check_position_limits("buy"):
            orders.append({
                "side": "buy",
                "price": quotes["bid"],
                "size": round(bid_size, 6),
            })

        if self.check_position_limits("sell"):
            orders.append({
                "side": "sell",
                "price": quotes["ask"],
                "size": round(ask_size, 6),
            })

        # 주문 실행 (모의)
        for order in orders:
            order_id = f"{self.bot_id}_{datetime.utcnow().strftime('%H%M%S%f')}"
            self.current_orders[order_id] = order
            self.orders_placed += 1
            logger.info(f"Order placed: {order['side']} {order['size']} @ {order['price']}")

        return {
            "status": "success",
            "orders_count": len(orders),
            "quotes": quotes,
            "inventory_ratio": self.inventory.inventory_ratio,
        }

    async def update_inventory(self, trade: Dict[str, Any]):
        """인벤토리 업데이트"""
        side = trade.get("side")
        size = trade.get("size", 0)
        price = trade.get("price", 0)

        if side == "buy":
            self.inventory.base_asset += size
            self.inventory.quote_asset -= size * price
        else:
            self.inventory.base_asset -= size
            self.inventory.quote_asset += size * price

        # 기준자산 가치 업데이트
        self.inventory.base_value = self.inventory.base_asset * price

        self.orders_filled += 1
        logger.info(f"Inventory updated: {self.inventory}")

    def get_stats(self) -> Dict[str, Any]:
        """봇 통계"""
        return {
            "bot_id": self.bot_id,
            "symbol": self.symbol,
            "running": self.running,
            "inventory": {
                "base": self.inventory.base_asset,
                "quote": self.inventory.quote_asset,
                "ratio": self.inventory.inventory_ratio,
            },
            "orders": {
                "placed": self.orders_placed,
                "filled": self.orders_filled,
                "fill_rate": self.orders_filled / self.orders_placed if self.orders_placed > 0 else 0,
            },
            "pnl": self.total_pnl,
        }

    async def run(self):
        """봇 실행"""
        self.running = True
        logger.info(f"Starting MarketMakerBot: {self.bot_id}")

        while self.running:
            try:
                # 오더북 가져오기 (모의)
                orderbook = await self._fetch_orderbook()

                if orderbook:
                    # 주문 배치
                    result = await self.place_orders(orderbook)
                    logger.debug(f"Order result: {result}")

                # 5초 대기
                await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"Bot error: {e}")
                await asyncio.sleep(10)

    async def stop(self):
        """봇 중지"""
        self.running = False
        logger.info(f"Stopping MarketMakerBot: {self.bot_id}")

    def get_status(self) -> Dict[str, Any]:
        """봇 상태 반환"""
        return {
            "bot_id": self.bot_id,
            "bot_type": "market_maker",
            "status": "running" if self.running else "idle",
            "mock_mode": False,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "inventory_ratio": self.inventory.inventory_ratio if hasattr(self, 'inventory') else 0.5,
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def _fetch_orderbook(self) -> Optional[OrderBook]:
        """오더북 조회 (모의)"""
        # 실제 구현에서는 거래소 API 호출
        return OrderBook(
            symbol=self.symbol,
            bids=[(50000.0, 1.0), (49990.0, 2.0)],
            asks=[(50010.0, 1.0), (50020.0, 2.0)],
            timestamp=datetime.utcnow(),
        )


async def main():
    """메인 실행"""
    bot = MarketMakerBot(
        bot_id="mm_btc_001",
        symbol="BTC/USDT",
        base_spread_bps=10.0,
    )

    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())

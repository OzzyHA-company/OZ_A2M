#!/usr/bin/env python3
"""
Arbitrage Bot

거래소 간 가격 차이를 이용한 차익거래 봇
- 거래소 간 가격 모니터링
- 차익 기회 탐지
- 동시 주문 실행
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

from lib.core.logger import get_logger
from lib.core.tracer import get_tracer, trace_function

logger = get_logger(__name__)
tracer = get_tracer("arbitrage_bot")


@dataclass
class PriceData:
    """가격 데이터"""
    exchange: str
    symbol: str
    bid: float
    ask: float
    timestamp: datetime

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass
class ArbitrageOpportunity:
    """차익 기회"""
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    spread: float
    spread_percent: float
    profit_estimate: float


class ArbitrageBot:
    """
    차익거래 봇

    기능:
    1. 다중 거래소 가격 모니터링
    2. 차익 기회 실시간 탐지
    3. 수익성 검증
    4. 시뮬레이션/실거래 모드
    """

    def __init__(
        self,
        bot_id: str = "arbitrage_001",
        symbol: str = "BTC/USDT",
        exchanges: List[str] = None,
        # 차익 설정
        min_spread_bps: float = 50.0,      # 최소 스프레드 (0.5%)
        min_profit_usd: float = 10.0,      # 최소 수익
        # 거래 설정
        trade_size: float = 0.01,          # 거래 크기
        max_slippage_bps: float = 20.0,    # 최대 슬리피지
        # 리스크 설정
        max_daily_trades: int = 10,
        max_position: float = 1.0,
    ):
        self.bot_id = bot_id
        self.symbol = symbol
        self.exchanges = exchanges or ["binance", "bybit"]

        # 차익 설정
        self.min_spread_bps = min_spread_bps
        self.min_profit_usd = min_profit_usd

        # 거래 설정
        self.trade_size = trade_size
        self.max_slippage_bps = max_slippage_bps

        # 리스크 설정
        self.max_daily_trades = max_daily_trades
        self.max_position = max_position

        # 상태
        self.price_data: Dict[str, PriceData] = {}
        self.running = False
        self.daily_trades = 0
        self.total_profit = 0.0
        self.opportunities_found = 0

        logger.info(f"ArbitrageBot initialized: {symbol} across {self.exchanges}")

    def check_arbitrage_opportunity(
        self,
        price1: PriceData,
        price2: PriceData
    ) -> Optional[ArbitrageOpportunity]:
        """
        두 거래소 간 차익 기회 확인

        Args:
            price1: 첫 번째 거래소 가격
            price2: 두 번째 거래소 가격

        Returns:
            ArbitrageOpportunity 또는 None
        """
        # 매수/매도 거래소 결정
        if price1.ask < price2.bid:
            buy_exchange = price1.exchange
            sell_exchange = price2.exchange
            buy_price = price1.ask
            sell_price = price2.bid
        elif price2.ask < price1.bid:
            buy_exchange = price2.exchange
            sell_exchange = price1.exchange
            buy_price = price2.ask
            sell_price = price1.bid
        else:
            return None

        # 스프레드 계산
        spread = sell_price - buy_price
        spread_percent = (spread / buy_price) * 10000  # bps

        # 최소 스프레드 체크
        if spread_percent < self.min_spread_bps:
            return None

        # 예상 수익
        profit = spread * self.trade_size

        # 최소 수익 체크
        if profit < self.min_profit_usd:
            return None

        return ArbitrageOpportunity(
            symbol=self.symbol,
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            buy_price=buy_price,
            sell_price=sell_price,
            spread=spread,
            spread_percent=spread_percent,
            profit_estimate=profit,
        )

    def scan_opportunities(self) -> List[ArbitrageOpportunity]:
        """
        모든 거래소 쌍에서 차익 기회 탐색

        Returns:
            차익 기회 목록
        """
        opportunities = []
        exchanges = list(self.price_data.keys())

        for i in range(len(exchanges)):
            for j in range(i + 1, len(exchanges)):
                price1 = self.price_data.get(exchanges[i])
                price2 = self.price_data.get(exchanges[j])

                if price1 and price2:
                    opp = self.check_arbitrage_opportunity(price1, price2)
                    if opp:
                        opportunities.append(opp)

        return opportunities

    def validate_execution(self, opportunity: ArbitrageOpportunity) -> Tuple[bool, str]:
        """
        실행 가능성 검증

        Args:
            opportunity: 차익 기회

        Returns:
            (검증통과, 메시지)
        """
        # 일일 거래 한도
        if self.daily_trades >= self.max_daily_trades:
            return False, "Daily trade limit reached"

        # 포지션 한도
        # (실제 구현에서는 현재 포지션 확인)

        # 슬리피지 고려한 실제 수익 검증
        slippage_cost = opportunity.buy_price * (self.max_slippage_bps / 10000) * self.trade_size
        net_profit = opportunity.profit_estimate - slippage_cost

        if net_profit < self.min_profit_usd:
            return False, f"Net profit too small: ${net_profit:.2f}"

        return True, f"Valid: ${net_profit:.2f} net profit"

    @trace_function("arbitrage_execute")
    async def execute_arbitrage(self, opportunity: ArbitrageOpportunity) -> Dict[str, Any]:
        """
        차익거래 실행

        Args:
            opportunity: 차익 기회

        Returns:
            실행 결과
        """
        # 검증
        valid, message = self.validate_execution(opportunity)
        if not valid:
            logger.warning(f"Execution rejected: {message}")
            return {"status": "rejected", "reason": message}

        logger.info(
            f"Executing arbitrage: Buy {opportunity.buy_exchange} "
            f"@ {opportunity.buy_price:.2f}, Sell {opportunity.sell_exchange} "
            f"@ {opportunity.sell_price:.2f}, Profit: ${opportunity.profit_estimate:.2f}"
        )

        # 동시 주문 실행 (모의)
        buy_order = await self._place_order(
            exchange=opportunity.buy_exchange,
            side="buy",
            price=opportunity.buy_price,
            size=self.trade_size,
        )

        sell_order = await self._place_order(
            exchange=opportunity.sell_exchange,
            side="sell",
            price=opportunity.sell_price,
            size=self.trade_size,
        )

        # 결과 기록
        self.daily_trades += 1
        self.total_profit += opportunity.profit_estimate

        return {
            "status": "success",
            "buy_order": buy_order,
            "sell_order": sell_order,
            "profit": opportunity.profit_estimate,
            "spread_bps": opportunity.spread_percent,
        }

    async def _place_order(
        self,
        exchange: str,
        side: str,
        price: float,
        size: float,
    ) -> Dict[str, Any]:
        """주문 배치 (모의)"""
        order_id = f"{self.bot_id}_{exchange}_{datetime.utcnow().strftime('%H%M%S%f')}"

        # 실제 구현에서는 거래소 API 호출
        return {
            "order_id": order_id,
            "exchange": exchange,
            "side": side,
            "price": price,
            "size": size,
            "status": "filled",
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def update_price(self, exchange: str, bid: float, ask: float):
        """가격 업데이트"""
        self.price_data[exchange] = PriceData(
            exchange=exchange,
            symbol=self.symbol,
            bid=bid,
            ask=ask,
            timestamp=datetime.utcnow(),
        )

    async def run(self):
        """봇 실행"""
        self.running = True
        logger.info(f"Starting ArbitrageBot: {self.bot_id}")

        while self.running:
            try:
                # 가격 업데이트 (모의)
                await self._simulate_price_updates()

                # 차익 기회 탐색
                opportunities = self.scan_opportunities()

                if opportunities:
                    # 가장 수익성 높은 기회 선택
                    best = max(opportunities, key=lambda x: x.profit_estimate)
                    self.opportunities_found += 1

                    logger.info(
                        f"Opportunity found: {best.buy_exchange} -> {best.sell_exchange}, "
                        f"Spread: {best.spread_percent:.1f}bps, Profit: ${best.profit_estimate:.2f}"
                    )

                    # 실행
                    result = await self.execute_arbitrage(best)
                    logger.debug(f"Execution result: {result}")

                # 1초 대기
                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Bot error: {e}")
                await asyncio.sleep(5)

    async def stop(self):
        """봇 중지"""
        self.running = False
        logger.info(f"Stopping ArbitrageBot: {self.bot_id}")

    async def _simulate_price_updates(self):
        """가격 업데이트 시뮬레이션"""
        import random

        base_price = 50000.0

        for i, exchange in enumerate(self.exchanges):
            # 약간의 가격 차이 시뮬레이션
            offset = random.uniform(-50, 50) if i > 0 else 0
            spread = random.uniform(10, 20)

            bid = base_price + offset
            ask = bid + spread

            await self.update_price(exchange, bid, ask)

    def get_stats(self) -> Dict[str, Any]:
        """봇 통계"""
        return {
            "bot_id": self.bot_id,
            "symbol": self.symbol,
            "exchanges": self.exchanges,
            "running": self.running,
            "daily_trades": self.daily_trades,
            "total_profit": self.total_profit,
            "opportunities_found": self.opportunities_found,
            "current_prices": {
                ex: {"bid": p.bid, "ask": p.ask}
                for ex, p in self.price_data.items()
            },
        }


async def main():
    """메인 실행"""
    bot = ArbitrageBot(
        bot_id="arb_btc_001",
        symbol="BTC/USDT",
        exchanges=["binance", "bybit"],
        min_spread_bps=30.0,
    )

    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())

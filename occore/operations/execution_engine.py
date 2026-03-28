"""
OZ_A2M Phase 5: 제7부서 운영팀 - 주문 실행 엔진

ccxt 기반 주문 생성, 취소, 체결 확인 및 상태 관리
"""

import asyncio
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Callable, Any
import logging

try:
    import ccxt.async_support as ccxt
except ImportError:
    ccxt = None

from .models import (
    Order, OrderSide, OrderType, OrderStatus,
    Trade, Position, PositionSide
)
from .exchange_connector import ExchangeConnector, MockExchangeConnector

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """주문 실행 엔진"""

    def __init__(
        self,
        connector: Optional[ExchangeConnector] = None,
        dry_run: bool = True
    ):
        """
        실행 엔진 초기화

        Args:
            connector: 거래소 연결 (None이면 Mock 사용)
            dry_run: 모의 거래 모드
        """
        self.connector = connector or MockExchangeConnector()
        self.dry_run = dry_run

        # 주문 저장소
        self.orders: Dict[str, Order] = {}
        self.trades: Dict[str, Trade] = {}

        # 콜백
        self.on_order_update: Optional[Callable[[Order], None]] = None
        self.on_trade: Optional[Callable[[Trade], None]] = None

        # 모니터링 태스크
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """엔진 시작"""
        if not self.connector.is_connected:
            await self.connector.connect()

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_orders())
        logger.info("Execution engine started")

    async def stop(self):
        """엔진 중지"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Execution engine stopped")

    async def place_market_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        bot_id: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Order:
        """
        시장가 주문

        Args:
            symbol: 거래 심볼
            side: 매수/매도
            amount: 수량
            bot_id: 봇 ID
            metadata: 추가 메타데이터

        Returns:
            생성된 주문 객체
        """
        order_id = str(uuid.uuid4())

        order = Order(
            id=order_id,
            order_id=None,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            amount=amount,
            status=OrderStatus.PENDING,
            bot_id=bot_id,
            metadata=metadata or {}
        )

        if self.dry_run:
            # 모의 거래
            await self._simulate_fill(order)
        else:
            # 실제 거래
            await self._place_real_order(order)

        self.orders[order_id] = order
        return order

    async def place_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
        bot_id: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Order:
        """
        지정가 주문

        Args:
            symbol: 거래 심볼
            side: 매수/매도
            amount: 수량
            price: 지정가
            bot_id: 봇 ID
            metadata: 추가 메타데이터

        Returns:
            생성된 주문 객체
        """
        order_id = str(uuid.uuid4())

        order = Order(
            id=order_id,
            order_id=None,
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            amount=amount,
            price=price,
            status=OrderStatus.PENDING,
            bot_id=bot_id,
            metadata=metadata or {}
        )

        if self.dry_run:
            # 모의 거래 - 지정가는 즉시 체결되지 않음
            order.status = OrderStatus.OPEN
        else:
            await self._place_real_order(order)

        self.orders[order_id] = order
        return order

    async def cancel_order(self, order_id: str) -> bool:
        """
        주문 취소

        Args:
            order_id: 주문 ID

        Returns:
            성공 여부
        """
        order = self.orders.get(order_id)
        if not order:
            logger.error(f"Order not found: {order_id}")
            return False

        if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED]:
            logger.warning(f"Order already {order.status.value}: {order_id}")
            return False

        if self.dry_run:
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.utcnow()
        else:
            try:
                if ccxt and order.order_id:
                    await self.connector.exchange.cancel_order(
                        order.order_id,
                        order.symbol
                    )
                order.status = OrderStatus.CANCELLED
                order.updated_at = datetime.utcnow()
            except Exception as e:
                logger.error(f"Failed to cancel order: {e}")
                return False

        if self.on_order_update:
            self.on_order_update(order)

        return True

    async def get_order_status(self, order_id: str) -> Optional[Order]:
        """
        주문 상태 조회

        Args:
            order_id: 주문 ID

        Returns:
            주문 객체 또는 None
        """
        order = self.orders.get(order_id)
        if not order:
            return None

        if not self.dry_run and order.order_id:
            # 실제 거래소에서 상태 업데이트
            try:
                if ccxt:
                    exchange_order = await self.connector.exchange.fetch_order(
                        order.order_id,
                        order.symbol
                    )
                    self._update_order_from_exchange(order, exchange_order)
            except Exception as e:
                logger.error(f"Failed to fetch order status: {e}")

        return order

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """
        미체결 주문 조회

        Args:
            symbol: 특정 심볼 (None이면 전체)

        Returns:
            미체결 주문 목록
        """
        open_orders = [
            o for o in self.orders.values()
            if o.status in [OrderStatus.PENDING, OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]
        ]

        if symbol:
            open_orders = [o for o in open_orders if o.symbol == symbol]

        return open_orders

    async def _place_real_order(self, order: Order):
        """실제 거래소에 주문 배치"""
        if not ccxt:
            raise RuntimeError("ccxt not installed")

        try:
            # 수량/가격 포맷팅
            amount = self.connector.format_amount(order.symbol, order.amount)

            params = {}
            if order.order_type == OrderType.MARKET:
                result = await self.connector.exchange.create_market_buy_order(
                    order.symbol,
                    float(amount),
                    params
                ) if order.side == OrderSide.BUY else await self.connector.exchange.create_market_sell_order(
                    order.symbol,
                    float(amount),
                    params
                )
            else:
                price = self.connector.format_price(order.symbol, order.price)
                result = await self.connector.exchange.create_limit_buy_order(
                    order.symbol,
                    float(amount),
                    float(price),
                    params
                ) if order.side == OrderSide.BUY else await self.connector.exchange.create_limit_sell_order(
                    order.symbol,
                    float(amount),
                    float(price),
                    params
                )

            order.order_id = result.get("id")
            order.status = OrderStatus.OPEN
            order.updated_at = datetime.utcnow()

        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            order.status = OrderStatus.REJECTED
            order.updated_at = datetime.utcnow()

    async def _simulate_fill(self, order: Order):
        """모의 체결"""
        # 현재가 조회
        ticker = await self.connector.get_ticker(order.symbol)
        price = ticker.get("last", Decimal("50000"))

        # 체결 처리
        fill_amount = order.amount
        fee = fill_amount * price * Decimal("0.001")  # 0.1% 수수료

        order.status = OrderStatus.FILLED
        order.filled_amount = fill_amount
        order.remaining_amount = Decimal("0")
        order.avg_fill_price = price
        order.fee = fee
        order.updated_at = datetime.utcnow()

        # 트레이드 생성
        trade_id = str(uuid.uuid4())
        trade = Trade(
            id=trade_id,
            trade_id=f"sim-{trade_id[:8]}",
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            amount=fill_amount,
            price=price,
            fee=fee,
            fee_currency=order.symbol.split("/")[1] if "/" in order.symbol else "USDT",
            bot_id=order.bot_id
        )
        self.trades[trade_id] = trade

        # 콜백 호출
        if self.on_trade:
            self.on_trade(trade)
        if self.on_order_update:
            self.on_order_update(order)

        logger.info(f"Simulated fill: {order.side.value} {fill_amount} {order.symbol} @ {price}")

    def _update_order_from_exchange(self, order: Order, exchange_order: Dict):
        """거래소 주문 정보로 업데이트"""
        status_map = {
            "open": OrderStatus.OPEN,
            "closed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "pending": OrderStatus.PENDING
        }

        order.status = status_map.get(
            exchange_order.get("status"),
            OrderStatus.PENDING
        )
        order.filled_amount = Decimal(str(exchange_order.get("filled", 0)))
        order.remaining_amount = Decimal(str(exchange_order.get("remaining", 0)))
        order.updated_at = datetime.utcnow()

    async def _monitor_orders(self):
        """주문 모니터링 루프"""
        while self._running:
            try:
                # 미체결 주문 체결 확인
                open_orders = await self.get_open_orders()
                for order in open_orders:
                    if not self.dry_run and order.order_id:
                        await self.get_order_status(order.id)

                await asyncio.sleep(1)  # 1초 간격

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Order monitoring error: {e}")
                await asyncio.sleep(5)

    def get_order_history(
        self,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 100
    ) -> List[Order]:
        """
        주문 히스토리 조회

        Args:
            bot_id: 특정 봇 필터
            symbol: 특정 심볼 필터
            limit: 최대 개수

        Returns:
            주문 목록
        """
        orders = list(self.orders.values())

        if bot_id:
            orders = [o for o in orders if o.bot_id == bot_id]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]

        # 시간 역순 정렬
        orders.sort(key=lambda o: o.created_at, reverse=True)
        return orders[:limit]

    def get_trade_history(
        self,
        bot_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 100
    ) -> List[Trade]:
        """
        체결 히스토리 조회

        Args:
            bot_id: 특정 봇 필터
            symbol: 특정 심볼 필터
            limit: 최대 개수

        Returns:
            체결 목록
        """
        trades = list(self.trades.values())

        if bot_id:
            trades = [t for t in trades if t.bot_id == bot_id]
        if symbol:
            trades = [t for t in trades if t.symbol == symbol]

        # 시간 역순 정렬
        trades.sort(key=lambda t: t.timestamp, reverse=True)
        return trades[:limit]

    def get_statistics(self, bot_id: Optional[str] = None) -> Dict[str, Any]:
        """
        거래 통계

        Args:
            bot_id: 특정 봇 필터

        Returns:
            통계 정보
        """
        orders = [o for o in self.orders.values() if not bot_id or o.bot_id == bot_id]
        trades = [t for t in self.trades.values() if not bot_id or t.bot_id == bot_id]

        filled_orders = [o for o in orders if o.status == OrderStatus.FILLED]
        cancelled_orders = [o for o in orders if o.status == OrderStatus.CANCELLED]

        total_volume = sum(t.total_value for t in trades)
        total_fees = sum(t.fee for t in trades)

        return {
            "total_orders": len(orders),
            "filled_orders": len(filled_orders),
            "cancelled_orders": len(cancelled_orders),
            "total_trades": len(trades),
            "total_volume": total_volume,
            "total_fees": total_fees,
            "bot_id": bot_id
        }


# 편의 함수
async def create_market_buy(
    symbol: str,
    amount: Decimal,
    connector: Optional[ExchangeConnector] = None,
    dry_run: bool = True
) -> Order:
    """시장가 매수 편의 함수"""
    engine = ExecutionEngine(connector, dry_run)
    await engine.start()
    order = await engine.place_market_order(symbol, OrderSide.BUY, amount)
    await engine.stop()
    return order


async def create_market_sell(
    symbol: str,
    amount: Decimal,
    connector: Optional[ExchangeConnector] = None,
    dry_run: bool = True
) -> Order:
    """시장가 매도 편의 함수"""
    engine = ExecutionEngine(connector, dry_run)
    await engine.start()
    order = await engine.place_market_order(symbol, OrderSide.SELL, amount)
    await engine.stop()
    return order


if __name__ == "__main__":
    # 테스트
    async def test():
        engine = ExecutionEngine(dry_run=True)
        await engine.start()

        # 시장가 매수
        order = await engine.place_market_order(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            amount=Decimal("0.001")
        )
        print(f"Order placed: {order.to_dict()}")

        # 통계
        stats = engine.get_statistics()
        print(f"Statistics: {stats}")

        await engine.stop()

    asyncio.run(test())

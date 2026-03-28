"""
OZ_A2M Phase 5: 제7부서 운영팀 - 포지션 관리 모듈

포지션 추적, 진입/청산, 손익 계산 및 포지션 히스토리 관리
"""

import asyncio
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Callable, Any
import logging

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

from .models import (
    Position, PositionSide, Order, OrderSide, OrderStatus,
    Trade, DailyStats
)
from .execution_engine import ExecutionEngine

logger = logging.getLogger(__name__)


class PositionManager:
    """포지션 관리자"""

    def __init__(
        self,
        execution_engine: ExecutionEngine,
        redis_url: Optional[str] = None
    ):
        """
        포지션 관리자 초기화

        Args:
            execution_engine: 주문 실행 엔진
            redis_url: Redis URL (선택)
        """
        self.execution_engine = execution_engine

        # 포지션 저장소
        self.positions: Dict[str, Position] = {}  # position_id -> Position
        self.symbol_positions: Dict[str, str] = {}  # symbol+exchange -> position_id

        # 일일 통계
        self.daily_stats: Dict[str, DailyStats] = {}  # date+bot_id -> DailyStats

        # Redis 캐시
        self.redis_client: Optional[Any] = None
        self._redis_enabled = False

        if redis_url and redis:
            self._redis_enabled = True
            self.redis_url = redis_url

        # 콜백
        self.on_position_update: Optional[Callable[[Position], None]] = None
        self.on_pnl_update: Optional[Callable[[Decimal], None]] = None

        # 실행 엔진 콜백 등록
        self.execution_engine.on_trade = self._on_trade

    async def connect(self):
        """Redis 연결"""
        if self._redis_enabled and redis:
            try:
                self.redis_client = redis.from_url(self.redis_url)
                await self.redis_client.ping()
                logger.info("Redis connected")
            except Exception as e:
                logger.error(f"Redis connection failed: {e}")
                self._redis_enabled = False

    async def disconnect(self):
        """Redis 연결 해제"""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis disconnected")

    async def open_position(
        self,
        symbol: str,
        side: PositionSide,
        amount: Decimal,
        price: Optional[Decimal] = None,
        exchange: str = "binance",
        bot_id: Optional[str] = None,
        leverage: float = 1.0
    ) -> Position:
        """
        포지션 진입

        Args:
            symbol: 거래 심볼
            side: 롱/숏
            amount: 수량
            price: 진입 가격 (None이면 시장가)
            exchange: 거래소
            bot_id: 봇 ID
            leverage: 레버리지

        Returns:
            생성된 포지션
        """
        # 기존 포지션 확인
        pos_key = f"{exchange}:{symbol}"
        existing_pos_id = self.symbol_positions.get(pos_key)

        if existing_pos_id:
            existing_pos = self.positions.get(existing_pos_id)
            if existing_pos and existing_pos.side != PositionSide.NONE:
                logger.warning(f"Position already exists for {symbol}")
                return existing_pos

        # 주문 실행
        order_side = OrderSide.BUY if side == PositionSide.LONG else OrderSide.SELL

        if price:
            order = await self.execution_engine.place_limit_order(
                symbol=symbol,
                side=order_side,
                amount=amount,
                price=price,
                bot_id=bot_id
            )
        else:
            order = await self.execution_engine.place_market_order(
                symbol=symbol,
                side=order_side,
                amount=amount,
                bot_id=bot_id
            )

        # 체결 확인 대기
        if order.status != OrderStatus.FILLED:
            await asyncio.sleep(0.5)  # 체결 대기
            order = await self.execution_engine.get_order_status(order.id)

        if order.status != OrderStatus.FILLED:
            logger.error(f"Order not filled: {order.id}")
            raise RuntimeError(f"Failed to open position: order not filled")

        # 포지션 생성
        position_id = str(uuid.uuid4())
        position = Position(
            id=position_id,
            symbol=symbol,
            side=side,
            amount=order.filled_amount,
            entry_price=order.avg_fill_price,
            mark_price=order.avg_fill_price,
            leverage=leverage,
            margin=order.filled_amount * order.avg_fill_price / Decimal(str(leverage)),
            exchange=exchange,
            bot_id=bot_id
        )

        self.positions[position_id] = position
        self.symbol_positions[pos_key] = position_id

        # Redis 캐시
        if self._redis_enabled:
            await self._cache_position(position)

        # 콜백
        if self.on_position_update:
            self.on_position_update(position)

        logger.info(f"Position opened: {side.value} {amount} {symbol} @ {order.avg_fill_price}")
        return position

    async def close_position(
        self,
        position_id: str,
        price: Optional[Decimal] = None
    ) -> Optional[Decimal]:
        """
        포지션 청산

        Args:
            position_id: 포지션 ID
            price: 청산 가격 (None이면 시장가)

        Returns:
            실현 손익
        """
        position = self.positions.get(position_id)
        if not position:
            logger.error(f"Position not found: {position_id}")
            return None

        # 반대 주문 실행
        close_side = OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY

        if price:
            order = await self.execution_engine.place_limit_order(
                symbol=position.symbol,
                side=close_side,
                amount=position.amount,
                price=price,
                bot_id=position.bot_id,
                metadata={"close_position": position_id}
            )
        else:
            order = await self.execution_engine.place_market_order(
                symbol=position.symbol,
                side=close_side,
                amount=position.amount,
                bot_id=position.bot_id,
                metadata={"close_position": position_id}
            )

        # 체결 확인 대기
        await asyncio.sleep(0.5)
        order = await self.execution_engine.get_order_status(order.id)

        if order.status != OrderStatus.FILLED:
            logger.error(f"Close order not filled: {order.id}")
            return None

        # 실현 손익 계산
        if position.side == PositionSide.LONG:
            realized_pnl = (order.avg_fill_price - position.entry_price) * position.amount
        else:
            realized_pnl = (position.entry_price - order.avg_fill_price) * position.amount

        # 수수료 차감
        realized_pnl -= order.fee

        # 포지션 업데이트
        position.realized_pnl = realized_pnl
        position.side = PositionSide.NONE
        position.amount = Decimal("0")
        position.updated_at = datetime.utcnow()

        # 일일 통계 업데이트
        await self._update_daily_stats(position, realized_pnl)

        # Redis 캐시 업데이트
        if self._redis_enabled:
            await self._cache_position(position)

        # 콜백
        if self.on_position_update:
            self.on_position_update(position)
        if self.on_pnl_update:
            self.on_pnl_update(realized_pnl)

        logger.info(f"Position closed: {position_id} PnL: {realized_pnl}")
        return realized_pnl

    async def update_position_price(self, position_id: str, current_price: Decimal):
        """포지션 현재가 업데이트"""
        position = self.positions.get(position_id)
        if not position or position.side == PositionSide.NONE:
            return

        position.update_pnl(current_price)

        # Redis 캐시
        if self._redis_enabled:
            await self._cache_position(position)

    async def get_position(self, position_id: str) -> Optional[Position]:
        """포지션 조회"""
        position = self.positions.get(position_id)

        # Redis에서 확인
        if not position and self._redis_enabled:
            position = await self._get_cached_position(position_id)
            if position:
                self.positions[position_id] = position

        return position

    async def get_position_by_symbol(
        self,
        symbol: str,
        exchange: str = "binance"
    ) -> Optional[Position]:
        """심볼로 포지션 조회"""
        pos_key = f"{exchange}:{symbol}"
        position_id = self.symbol_positions.get(pos_key)
        if position_id:
            return await self.get_position(position_id)
        return None

    async def get_open_positions(
        self,
        bot_id: Optional[str] = None
    ) -> List[Position]:
        """열린 포지션 목록"""
        positions = [
            p for p in self.positions.values()
            if p.side != PositionSide.NONE
        ]

        if bot_id:
            positions = [p for p in positions if p.bot_id == bot_id]

        return positions

    async def get_total_pnl(
        self,
        bot_id: Optional[str] = None,
        unrealized: bool = True
    ) -> Decimal:
        """
        총 손익 조회

        Args:
            bot_id: 특정 봇 필터
            unrealized: 미실현 손익 포함

        Returns:
            총 손익
        """
        total = Decimal("0")

        positions = self.positions.values()
        if bot_id:
            positions = [p for p in positions if p.bot_id == bot_id]

        for pos in positions:
            total += pos.realized_pnl
            if unrealized:
                total += pos.unrealized_pnl

        return total

    async def get_daily_stats(
        self,
        date: Optional[str] = None,
        bot_id: Optional[str] = None
    ) -> DailyStats:
        """일일 통계 조회"""
        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")

        key = f"{date}:{bot_id or 'all'}"

        if key not in self.daily_stats:
            self.daily_stats[key] = DailyStats(
                date=date,
                bot_id=bot_id,
                exchange="binance"
            )

        return self.daily_stats[key]

    def _on_trade(self, trade: Trade):
        """체결 콜백"""
        # 포지션 업데이트 로직
        asyncio.create_task(self._handle_trade(trade))

    async def _handle_trade(self, trade: Trade):
        """체결 처리"""
        # 관련 포지션 찾기
        pos_key = f"{trade.exchange}:{trade.symbol}"
        position_id = self.symbol_positions.get(pos_key)

        if not position_id:
            return

        position = self.positions.get(position_id)
        if not position:
            return

        # 포지션 업데이트
        position.updated_at = datetime.utcnow()

        # Redis 캐시
        if self._redis_enabled:
            await self._cache_position(position)

    async def _update_daily_stats(self, position: Position, realized_pnl: Decimal):
        """일일 통계 업데이트"""
        date = datetime.utcnow().strftime("%Y-%m-%d")

        # 봇별 통계
        if position.bot_id:
            key = f"{date}:{position.bot_id}"
            if key not in self.daily_stats:
                self.daily_stats[key] = DailyStats(
                    date=date,
                    bot_id=position.bot_id,
                    exchange=position.exchange
                )
            self.daily_stats[key].net_pnl += realized_pnl

        # 전체 통계
        all_key = f"{date}:all"
        if all_key not in self.daily_stats:
            self.daily_stats[all_key] = DailyStats(
                date=date,
                bot_id=None,
                exchange=position.exchange
            )
        self.daily_stats[all_key].net_pnl += realized_pnl

    async def _cache_position(self, position: Position):
        """Redis에 포지션 캐시"""
        if not self.redis_client:
            return

        try:
            await self.redis_client.setex(
                f"position:{position.id}",
                3600,  # 1시간 TTL
                str(position.to_dict())
            )
        except Exception as e:
            logger.error(f"Redis cache error: {e}")

    async def _get_cached_position(self, position_id: str) -> Optional[Position]:
        """Redis에서 포지션 조회"""
        if not self.redis_client:
            return None

        try:
            data = await self.redis_client.get(f"position:{position_id}")
            if data:
                # 파싱 로직 필요
                pass
        except Exception as e:
            logger.error(f"Redis get error: {e}")

        return None

    def get_position_summary(self, bot_id: Optional[str] = None) -> Dict[str, Any]:
        """포지션 요약"""
        positions = list(self.positions.values())
        if bot_id:
            positions = [p for p in positions if p.bot_id == bot_id]

        open_positions = [p for p in positions if p.side != PositionSide.NONE]

        total_unrealized = sum(p.unrealized_pnl for p in open_positions)
        total_realized = sum(p.realized_pnl for p in positions)

        longs = [p for p in open_positions if p.side == PositionSide.LONG]
        shorts = [p for p in open_positions if p.side == PositionSide.SHORT]

        return {
            "open_positions": len(open_positions),
            "long_positions": len(longs),
            "short_positions": len(shorts),
            "total_unrealized_pnl": total_unrealized,
            "total_realized_pnl": total_realized,
            "total_pnl": total_unrealized + total_realized,
            "symbols": list(set(p.symbol for p in open_positions))
        }


if __name__ == "__main__":
    # 테스트
    async def test():
        engine = ExecutionEngine(dry_run=True)
        await engine.start()

        pm = PositionManager(engine)
        await pm.connect()

        # 포지션 진입
        pos = await pm.open_position(
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            amount=Decimal("0.001"),
            bot_id="test-bot"
        )
        print(f"Position opened: {pos.to_dict()}")

        # 포지션 조회
        fetched = await pm.get_position(pos.id)
        print(f"Position fetched: {fetched.id}")

        # 포지션 청산
        pnl = await pm.close_position(pos.id)
        print(f"Position closed with PnL: {pnl}")

        # 요약
        summary = pm.get_position_summary()
        print(f"Summary: {summary}")

        await pm.disconnect()
        await engine.stop()

    asyncio.run(test())

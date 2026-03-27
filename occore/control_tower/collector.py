"""
OZ_A2M 제1부서: 관제탑센터 - 통합 데이터 수집기

CCXT 기반 다중 거래소 데이터 통합 수집 및 캐싱
"""

import os
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable, Set
from decimal import Decimal
from collections import defaultdict
import json

from .exchange_adapter import (
    ExchangeAdapter, CCXTAdapter, AdapterFactory,
    TickerData, OrderBookData, TradeData
)
from .normalizer import DataNormalizer

logger = logging.getLogger(__name__)


@dataclass
class ExchangeData:
    """통합 거래소 데이터"""
    exchange_id: str
    timestamp: datetime
    tickers: Dict[str, TickerData] = field(default_factory=dict)
    order_books: Dict[str, OrderBookData] = field(default_factory=dict)
    recent_trades: Dict[str, List[TradeData]] = field(default_factory=dict)
    connection_status: str = "disconnected"
    latency_ms: float = 0.0
    error_count: int = 0


@dataclass
class MarketSnapshot:
    """시장 스냅샷 (모든 거래소 통합)"""
    timestamp: datetime
    symbol: str
    exchanges: Dict[str, TickerData] = field(default_factory=dict)
    arbitrage_opportunities: List[Dict] = field(default_factory=list)
    average_price: Decimal = Decimal('0')
    total_volume: Decimal = Decimal('0')
    price_variance: float = 0.0


class DataCollector:
    """
    통합 데이터 수집기

    기능:
    - 다중 거래소 동시 연결
    - 실시간 데이터 수집 및 캐싱
    - 데이터 정제 및 표준화
    - 장애 대응 (자동 재연결)
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.adapters: Dict[str, ExchangeAdapter] = {}
        self.data_cache: Dict[str, ExchangeData] = {}
        self.snapshot_cache: Dict[str, MarketSnapshot] = {}
        self._callbacks: List[Callable] = []
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._normalizer = DataNormalizer()

        # 캐싱 설정
        self._cache_ttl = self.config.get('cache_ttl_seconds', 5)
        self._collection_interval = self.config.get('collection_interval_seconds', 10)

    async def add_exchange(self, exchange_id: str, adapter_type: str = 'ccxt',
                           config: Optional[Dict] = None) -> bool:
        """거래소 추가 및 연결"""
        try:
            adapter = AdapterFactory.create_adapter(exchange_id, adapter_type, config)
            connected = await adapter.connect()

            if connected:
                self.adapters[exchange_id] = adapter
                adapter.on_data(self._on_exchange_data)
                logger.info(f"Added exchange: {exchange_id}")
                return True
            else:
                logger.error(f"Failed to connect to {exchange_id}")
                return False

        except Exception as e:
            logger.error(f"Error adding exchange {exchange_id}: {e}")
            return False

    async def remove_exchange(self, exchange_id: str):
        """거래소 제거"""
        if exchange_id in self.adapters:
            adapter = self.adapters[exchange_id]
            await adapter.disconnect()
            del self.adapters[exchange_id]
            if exchange_id in self.data_cache:
                del self.data_cache[exchange_id]
            logger.info(f"Removed exchange: {exchange_id}")

    async def start_collection(self, symbols: List[str]):
        """데이터 수집 시작"""
        if self._running:
            logger.warning("Collection already running")
            return

        self._running = True
        logger.info(f"Starting data collection for symbols: {symbols}")

        # 각 거래소별 수집 태스크 시작
        for exchange_id in self.adapters:
            task = asyncio.create_task(
                self._collect_loop(exchange_id, symbols),
                name=f"collector_{exchange_id}"
            )
            self._tasks.append(task)

        # 시장 스냅샷 생성 태스크
        snapshot_task = asyncio.create_task(
            self._snapshot_loop(symbols),
            name="snapshot_generator"
        )
        self._tasks.append(snapshot_task)

    async def stop_collection(self):
        """데이터 수집 중지"""
        self._running = False

        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        logger.info("Data collection stopped")

    async def _collect_loop(self, exchange_id: str, symbols: List[str]):
        """거래소별 데이터 수집 루프"""
        adapter = self.adapters[exchange_id]

        while self._running:
            start_time = asyncio.get_event_loop().time()

            try:
                exchange_data = ExchangeData(
                    exchange_id=exchange_id,
                    timestamp=datetime.now(),
                    connection_status="connected"
                )

                for symbol in symbols:
                    try:
                        # 티커 데이터 수집
                        ticker = await adapter.fetch_ticker(symbol)
                        exchange_data.tickers[symbol] = ticker

                        # 오더북 데이터 수집 (최소화)
                        if self.config.get('fetch_orderbook', False):
                            order_book = await adapter.fetch_order_book(symbol, limit=10)
                            exchange_data.order_books[symbol] = order_book

                        # 최근 거래 내역 수집
                        if self.config.get('fetch_trades', False):
                            trades = await adapter.fetch_trades(symbol, limit=50)
                            exchange_data.recent_trades[symbol] = trades

                    except Exception as e:
                        logger.warning(f"Error fetching {symbol} from {exchange_id}: {e}")
                        exchange_data.error_count += 1

                # 데이터 정제
                exchange_data = self._normalizer.normalize_exchange_data(exchange_data)

                # 캐시 업데이트
                self.data_cache[exchange_id] = exchange_data

                # 콜백 알림
                self._notify('exchange_data', exchange_data)

                # 지연 시간 계산
                elapsed = (asyncio.get_event_loop().time() - start_time) * 1000
                exchange_data.latency_ms = elapsed

            except Exception as e:
                logger.error(f"Collection loop error for {exchange_id}: {e}")
                exchange_data.connection_status = "error"

            # 다음 수집까지 대기
            await asyncio.sleep(self._collection_interval)

    async def _snapshot_loop(self, symbols: List[str]):
        """시장 스냅샷 생성 루프"""
        while self._running:
            try:
                for symbol in symbols:
                    snapshot = self._create_market_snapshot(symbol)
                    if snapshot:
                        self.snapshot_cache[symbol] = snapshot
                        self._notify('market_snapshot', snapshot)

            except Exception as e:
                logger.error(f"Snapshot generation error: {e}")

            await asyncio.sleep(self._collection_interval)

    def _create_market_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        """특정 심볼의 시장 스냅샷 생성"""
        tickers = {}

        for exchange_id, data in self.data_cache.items():
            if symbol in data.tickers:
                tickers[exchange_id] = data.tickers[symbol]

        if not tickers:
            return None

        # 가격 통계 계산
        prices = [t.last for t in tickers.values()]
        volumes = [t.volume_24h for t in tickers.values()]

        avg_price = sum(prices) / len(prices) if prices else Decimal('0')
        total_volume = sum(volumes) if volumes else Decimal('0')

        # 가격 분산 계산
        if len(prices) > 1:
            price_list = [float(p) for p in prices]
            mean_price = sum(price_list) / len(price_list)
            variance = sum((p - mean_price) ** 2 for p in price_list) / len(price_list)
            price_variance = (variance ** 0.5) / mean_price * 100 if mean_price > 0 else 0
        else:
            price_variance = 0

        # 아비트라지 기회 감지
        arbitrage = self._detect_arbitrage(tickers)

        return MarketSnapshot(
            timestamp=datetime.now(),
            symbol=symbol,
            exchanges=tickers,
            arbitrage_opportunities=arbitrage,
            average_price=avg_price,
            total_volume=total_volume,
            price_variance=price_variance
        )

    def _detect_arbitrage(self, tickers: Dict[str, TickerData]) -> List[Dict]:
        """아비트라지 기회 감지"""
        opportunities = []

        exchanges = list(tickers.keys())
        for i, ex1 in enumerate(exchanges):
            for ex2 in exchanges[i+1:]:
                t1 = tickers[ex1]
                t2 = tickers[ex2]

                # 매도가가 높은 거래소에서 매수가가 낮은 거래소로
                if t1.bid > t2.ask:
                    spread = float(t1.bid - t2.ask) / float(t2.ask) * 100
                    if spread > 0.5:  # 0.5% 이상 스프레드
                        opportunities.append({
                            'buy_exchange': ex2,
                            'sell_exchange': ex1,
                            'buy_price': float(t2.ask),
                            'sell_price': float(t1.bid),
                            'spread_pct': spread,
                            'potential_profit_pct': spread
                        })

                elif t2.bid > t1.ask:
                    spread = float(t2.bid - t1.ask) / float(t1.ask) * 100
                    if spread > 0.5:
                        opportunities.append({
                            'buy_exchange': ex1,
                            'sell_exchange': ex2,
                            'buy_price': float(t1.ask),
                            'sell_price': float(t2.bid),
                            'spread_pct': spread,
                            'potential_profit_pct': spread
                        })

        return opportunities

    def _on_exchange_data(self, data_type: str, exchange_id: str, data: Any):
        """거래소 데이터 콜백"""
        pass  # 내부적으로 처리됨

    def on_data(self, callback: Callable):
        """데이터 수신 콜백 등록"""
        self._callbacks.append(callback)

    def _notify(self, data_type: str, data: Any):
        """콜백 알림"""
        for callback in self._callbacks:
            try:
                callback(data_type, data)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def get_exchange_data(self, exchange_id: str) -> Optional[ExchangeData]:
        """특정 거래소 데이터 조회"""
        return self.data_cache.get(exchange_id)

    def get_market_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        """특정 심볼 시장 스냅샷 조회"""
        return self.snapshot_cache.get(symbol)

    def get_all_snapshots(self) -> Dict[str, MarketSnapshot]:
        """모든 시장 스냅샷 조회"""
        return self.snapshot_cache.copy()

    def get_exchange_status(self) -> Dict[str, Dict]:
        """모든 거래소 연결 상태 조회"""
        status = {}
        for exchange_id, data in self.data_cache.items():
            status[exchange_id] = {
                'connection': data.connection_status,
                'latency_ms': data.latency_ms,
                'error_count': data.error_count,
                'last_update': data.timestamp.isoformat(),
                'symbols_tracked': len(data.tickers)
            }
        return status

    async def get_historical_data(self, exchange_id: str, symbol: str,
                                   timeframe: str = '1h', limit: int = 100) -> List[Dict]:
        """과거 데이터 조회 (OHLCV)"""
        if exchange_id not in self.adapters:
            raise ValueError(f"Exchange {exchange_id} not found")

        adapter = self.adapters[exchange_id]
        if not isinstance(adapter, CCXTAdapter):
            raise ValueError("Historical data only supported for CCXT adapters")

        try:
            import ccxt.async_support as ccxt
            ohlcv = await adapter.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

            return [
                {
                    'timestamp': candle[0],
                    'open': Decimal(str(candle[1])),
                    'high': Decimal(str(candle[2])),
                    'low': Decimal(str(candle[3])),
                    'close': Decimal(str(candle[4])),
                    'volume': Decimal(str(candle[5]))
                }
                for candle in ohlcv
            ]

        except Exception as e:
            logger.error(f"Error fetching historical data: {e}")
            return []

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.stop_collection()
        for adapter in self.adapters.values():
            await adapter.disconnect()

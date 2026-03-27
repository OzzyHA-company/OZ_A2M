"""
OZ_A2M 제1부서: 관제탑센터 - 거래소 어댑터

CCXT 기반 거래소 연결 및 데이터 수집
"""

import os
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from decimal import Decimal

logger = logging.getLogger(__name__)


@dataclass
class TickerData:
    """통일된 티커 데이터"""
    symbol: str
    exchange: str
    timestamp: datetime
    bid: Decimal
    ask: Decimal
    last: Decimal
    volume_24h: Decimal
    change_24h_pct: float
    high_24h: Decimal
    low_24h: Decimal
    raw_data: Dict = field(default_factory=dict)


@dataclass
class OrderBookData:
    """통일된 오더북 데이터"""
    symbol: str
    exchange: str
    timestamp: datetime
    bids: List[tuple]  # [(price, amount), ...]
    asks: List[tuple]
    raw_data: Dict = field(default_factory=dict)


@dataclass
class TradeData:
    """통일된 거래 데이터"""
    symbol: str
    exchange: str
    timestamp: datetime
    side: str  # 'buy' or 'sell'
    amount: Decimal
    price: Decimal
    trade_id: str
    raw_data: Dict = field(default_factory=dict)


class ExchangeAdapter(ABC):
    """거래소 어댑터 기본 클래스"""

    def __init__(self, exchange_id: str, config: Optional[Dict] = None):
        self.exchange_id = exchange_id
        self.config = config or {}
        self.is_connected = False
        self._callbacks: List[Callable] = []

    @abstractmethod
    async def connect(self) -> bool:
        """거래소 연결"""
        pass

    @abstractmethod
    async def disconnect(self):
        """거래소 연결 해제"""
        pass

    @abstractmethod
    async def fetch_ticker(self, symbol: str) -> TickerData:
        """티커 데이터 조회"""
        pass

    @abstractmethod
    async def fetch_order_book(self, symbol: str, limit: int = 20) -> OrderBookData:
        """오더북 데이터 조회"""
        pass

    @abstractmethod
    async def fetch_trades(self, symbol: str, limit: int = 100) -> List[TradeData]:
        """최근 거래 내역 조회"""
        pass

    def on_data(self, callback: Callable):
        """데이터 수신 콜백 등록"""
        self._callbacks.append(callback)

    def _notify(self, data_type: str, data: Any):
        """콜백 알림"""
        for callback in self._callbacks:
            try:
                callback(data_type, self.exchange_id, data)
            except Exception as e:
                logger.error(f"Callback error: {e}")


class CCXTAdapter(ExchangeAdapter):
    """CCXT 기반 거래소 어댑터 (110+ 거래소 지원)"""

    def __init__(self, exchange_id: str, config: Optional[Dict] = None):
        super().__init__(exchange_id, config)
        self.exchange = None
        self._rate_limit_remaining = 100
        self._rate_limit_reset = 0

    async def connect(self) -> bool:
        """CCXT 거래소 연결"""
        try:
            import ccxt.async_support as ccxt

            exchange_class = getattr(ccxt, self.exchange_id)
            if not exchange_class:
                logger.error(f"Exchange {self.exchange_id} not found in CCXT")
                return False

            api_key = self.config.get('api_key') or os.getenv(f"{self.exchange_id.upper()}_API_KEY")
            api_secret = self.config.get('api_secret') or os.getenv(f"{self.exchange_id.upper()}_API_SECRET")

            self.exchange = exchange_class({
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot',
                }
            })

            await self.exchange.load_markets()
            self.is_connected = True
            logger.info(f"Connected to {self.exchange_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to {self.exchange_id}: {e}")
            return False

    async def disconnect(self):
        """연결 해제"""
        if self.exchange:
            await self.exchange.close()
            self.is_connected = False
            logger.info(f"Disconnected from {self.exchange_id}")

    async def fetch_ticker(self, symbol: str) -> TickerData:
        """티커 데이터 조회"""
        if not self.is_connected:
            raise ConnectionError(f"Not connected to {self.exchange_id}")

        try:
            ticker = await self.exchange.fetch_ticker(symbol)

            return TickerData(
                symbol=symbol,
                exchange=self.exchange_id,
                timestamp=datetime.fromtimestamp(ticker['timestamp'] / 1000) if ticker['timestamp'] else datetime.now(),
                bid=Decimal(str(ticker['bid'])) if ticker['bid'] else Decimal('0'),
                ask=Decimal(str(ticker['ask'])) if ticker['ask'] else Decimal('0'),
                last=Decimal(str(ticker['last'])) if ticker['last'] else Decimal('0'),
                volume_24h=Decimal(str(ticker['quoteVolume'])) if ticker['quoteVolume'] else Decimal('0'),
                change_24h_pct=ticker.get('percentage', 0.0),
                high_24h=Decimal(str(ticker['high'])) if ticker['high'] else Decimal('0'),
                low_24h=Decimal(str(ticker['low'])) if ticker['low'] else Decimal('0'),
                raw_data=ticker
            )

        except Exception as e:
            logger.error(f"Error fetching ticker from {self.exchange_id}: {e}")
            raise

    async def fetch_order_book(self, symbol: str, limit: int = 20) -> OrderBookData:
        """오더북 데이터 조회"""
        if not self.is_connected:
            raise ConnectionError(f"Not connected to {self.exchange_id}")

        try:
            order_book = await self.exchange.fetch_order_book(symbol, limit)

            bids = [(Decimal(str(p)), Decimal(str(a))) for p, a in order_book['bids'][:limit]]
            asks = [(Decimal(str(p)), Decimal(str(a))) for p, a in order_book['asks'][:limit]]

            return OrderBookData(
                symbol=symbol,
                exchange=self.exchange_id,
                timestamp=datetime.fromtimestamp(order_book['timestamp'] / 1000) if order_book['timestamp'] else datetime.now(),
                bids=bids,
                asks=asks,
                raw_data=order_book
            )

        except Exception as e:
            logger.error(f"Error fetching order book from {self.exchange_id}: {e}")
            raise

    async def fetch_trades(self, symbol: str, limit: int = 100) -> List[TradeData]:
        """최근 거래 내역 조회"""
        if not self.is_connected:
            raise ConnectionError(f"Not connected to {self.exchange_id}")

        try:
            trades = await self.exchange.fetch_trades(symbol, limit=limit)

            result = []
            for trade in trades:
                result.append(TradeData(
                    symbol=symbol,
                    exchange=self.exchange_id,
                    timestamp=datetime.fromtimestamp(trade['timestamp'] / 1000) if trade['timestamp'] else datetime.now(),
                    side=trade['side'],
                    amount=Decimal(str(trade['amount'])),
                    price=Decimal(str(trade['price'])),
                    trade_id=str(trade['id']),
                    raw_data=trade
                ))

            return result

        except Exception as e:
            logger.error(f"Error fetching trades from {self.exchange_id}: {e}")
            raise

    async def fetch_balance(self) -> Dict[str, Decimal]:
        """잔고 조회 (API key 필요)"""
        if not self.is_connected:
            raise ConnectionError(f"Not connected to {self.exchange_id}")

        try:
            balance = await self.exchange.fetch_balance()
            return {
                asset: Decimal(str(info['free'])) + Decimal(str(info['used']))
                for asset, info in balance.items()
                if isinstance(info, dict) and 'free' in info
            }
        except Exception as e:
            logger.error(f"Error fetching balance from {self.exchange_id}: {e}")
            raise

    def get_supported_symbols(self) -> List[str]:
        """지원하는 심볼 목록"""
        if not self.exchange:
            return []
        return list(self.exchange.symbols)

    def get_rate_limit_status(self) -> Dict[str, Any]:
        """Rate limit 상태 조회"""
        return {
            'remaining': self._rate_limit_remaining,
            'reset_at': self._rate_limit_reset,
            'exchange': self.exchange_id
        }


class CustomAdapter(ExchangeAdapter):
    """커스텀 거래소 어댑터 (Drift, Pump 등 특수 거래소용)"""

    async def connect(self) -> bool:
        """커스텀 연결 로직"""
        # Drift, Pump 등 특수 거래소용 커스텀 구현
        self.is_connected = True
        return True

    async def disconnect(self):
        """연결 해제"""
        self.is_connected = False

    async def fetch_ticker(self, symbol: str) -> TickerData:
        """커스텀 티커 조회"""
        raise NotImplementedError("Custom adapter requires implementation")

    async def fetch_order_book(self, symbol: str, limit: int = 20) -> OrderBookData:
        """커스텀 오더북 조회"""
        raise NotImplementedError("Custom adapter requires implementation")

    async def fetch_trades(self, symbol: str, limit: int = 100) -> List[TradeData]:
        """커스텀 거래 내역 조회"""
        raise NotImplementedError("Custom adapter requires implementation")


class AdapterFactory:
    """거래소 어댑터 팩토리"""

    _adapters: Dict[str, type] = {
        'ccxt': CCXTAdapter,
        'custom': CustomAdapter,
    }

    @classmethod
    def create_adapter(cls, exchange_id: str, adapter_type: str = 'ccxt',
                       config: Optional[Dict] = None) -> ExchangeAdapter:
        """어댑터 생성"""
        adapter_class = cls._adapters.get(adapter_type)
        if not adapter_class:
            raise ValueError(f"Unknown adapter type: {adapter_type}")

        return adapter_class(exchange_id, config)

    @classmethod
    def register_adapter(cls, name: str, adapter_class: type):
        """커스텀 어댑터 등록"""
        cls._adapters[name] = adapter_class

    @classmethod
    def get_supported_ccxt_exchanges(cls) -> List[str]:
        """CCXT 지원 거래소 목록"""
        try:
            import ccxt
            return ccxt.exchanges
        except ImportError:
            return []

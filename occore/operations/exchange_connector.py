"""
OZ_A2M Phase 5: 제7부서 운영팀 - 거래소 연결 모듈

ccxt 기반 거래소 연결, API 키 관리, 잔고/심볼 정보 조회
"""

import asyncio
import os
from decimal import Decimal
from typing import Dict, List, Optional, Any
import logging

try:
    import ccxt.async_support as ccxt
except ImportError:
    ccxt = None

from .models import OrderSide, OrderType, OrderStatus

logger = logging.getLogger(__name__)


class ExchangeConnector:
    """거래소 연결 관리자"""

    SUPPORTED_EXCHANGES = ["binance", "bybit", "okx", "bitget", "gateio"]

    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        passphrase: Optional[str] = None,
        sandbox: bool = True,
        testnet: bool = True
    ):
        """
        거래소 연결 초기화

        Args:
            exchange_id: 거래소 ID (binance, bybit, etc.)
            api_key: API 키 (None이면 환경변수에서 로드)
            api_secret: API 시크릿 (None이면 환경변수에서 로드)
            passphrase: API 패스프레이즈 (OKX 등)
            sandbox: 샌드박스 모드
            testnet: 테스트넷 모드
        """
        self.exchange_id = exchange_id.lower()
        self.sandbox = sandbox
        self.testnet = testnet

        # API 키 로드
        self.api_key = api_key or self._load_env_key(f"{exchange_id.upper()}_API_KEY")
        self.api_secret = api_secret or self._load_env_key(f"{exchange_id.upper()}_API_SECRET")
        self.passphrase = passphrase or self._load_env_key(f"{exchange_id.upper()}_PASSPHRASE")

        # ccxt 거래소 인스턴스
        self.exchange = None
        self._connected = False

        # 캐시
        self._balance_cache: Dict = {}
        self._markets_cache: Dict = {}
        self._tickers_cache: Dict = {}

    def _load_env_key(self, key: str) -> Optional[str]:
        """환경변수에서 API 키 로드"""
        return os.environ.get(key)

    async def connect(self) -> bool:
        """거래소 연결"""
        if ccxt is None:
            logger.error("ccxt not installed. Install: pip install ccxt")
            return False

        if self.exchange_id not in self.SUPPORTED_EXCHANGES:
            logger.error(f"Unsupported exchange: {self.exchange_id}")
            return False

        try:
            # 거래소 클래스 동적 로드
            exchange_class = getattr(ccxt, self.exchange_id)

            config = {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "options": {}
            }

            if self.passphrase:
                config["password"] = self.passphrase

            # 샌드박스/테스트넷 설정
            if self.exchange_id == "binance":
                config["options"]["defaultType"] = "spot"
                if self.testnet:
                    config["options"]["testnet"] = True
            elif self.exchange_id == "bybit":
                if self.testnet:
                    config["options"]["testnet"] = True

            self.exchange = exchange_class(config)

            if self.sandbox and hasattr(self.exchange, "set_sandbox_mode"):
                self.exchange.set_sandbox_mode(True)

            # 거래소 로드
            await self.exchange.load_markets()
            self._connected = True
            self._markets_cache = self.exchange.markets

            logger.info(f"Connected to {self.exchange_id} (sandbox={self.sandbox})")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to {self.exchange_id}: {e}")
            self._connected = False
            return False

    async def disconnect(self):
        """거래소 연결 해제"""
        if self.exchange:
            await self.exchange.close()
            self._connected = False
            logger.info(f"Disconnected from {self.exchange_id}")

    @property
    def is_connected(self) -> bool:
        """연결 상태 확인"""
        return self._connected and self.exchange is not None

    async def get_balance(self, currency: Optional[str] = None) -> Dict[str, Any]:
        """
        잔고 조회

        Args:
            currency: 특정 화폐 (None이면 전체)

        Returns:
            잔고 정보 딕셔너리
        """
        if not self.is_connected:
            return {"error": "Not connected"}

        try:
            balance = await self.exchange.fetch_balance()
            self._balance_cache = balance

            if currency:
                return {
                    "free": Decimal(str(balance.get(currency, {}).get("free", 0))),
                    "used": Decimal(str(balance.get(currency, {}).get("used", 0))),
                    "total": Decimal(str(balance.get(currency, {}).get("total", 0)))
                }
            return balance

        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return {"error": str(e)}

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        현재가 조회

        Args:
            symbol: 거래 심볼 (BTC/USDT)

        Returns:
            티커 정보
        """
        if not self.is_connected:
            return {"error": "Not connected"}

        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            self._tickers_cache[symbol] = ticker
            return {
                "symbol": symbol,
                "last": Decimal(str(ticker.get("last", 0))),
                "bid": Decimal(str(ticker.get("bid", 0))),
                "ask": Decimal(str(ticker.get("ask", 0))),
                "high": Decimal(str(ticker.get("high", 0))),
                "low": Decimal(str(ticker.get("low", 0))),
                "volume": Decimal(str(ticker.get("volume", 0))),
                "timestamp": ticker.get("timestamp")
            }
        except Exception as e:
            logger.error(f"Failed to fetch ticker for {symbol}: {e}")
            return {"error": str(e)}

    async def get_orderbook(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """
        호가 조회

        Args:
            symbol: 거래 심볼
            limit: 깊이

        Returns:
            호가 정보
        """
        if not self.is_connected:
            return {"error": "Not connected"}

        try:
            orderbook = await self.exchange.fetch_order_book(symbol, limit)
            return {
                "symbol": symbol,
                "bids": orderbook.get("bids", []),
                "asks": orderbook.get("asks", []),
                "timestamp": orderbook.get("timestamp")
            }
        except Exception as e:
            logger.error(f"Failed to fetch orderbook for {symbol}: {e}")
            return {"error": str(e)}

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 100,
        since: Optional[int] = None
    ) -> List[List]:
        """
        OHLCV 데이터 조회

        Args:
            symbol: 거래 심볼
            timeframe: 시간프레임 (1m, 5m, 1h, 1d)
            limit: 개수
            since: 시작 타임스탬프 (ms)

        Returns:
            OHLCV 리스트 [[timestamp, open, high, low, close, volume], ...]
        """
        if not self.is_connected:
            return []

        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            return ohlcv
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV for {symbol}: {e}")
            return []

    def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """
        심볼 정보 조회

        Args:
            symbol: 거래 심볼

        Returns:
            심볼 정보 (precision, limits 등)
        """
        if not self._markets_cache:
            return {"error": "Markets not loaded"}

        market = self._markets_cache.get(symbol)
        if not market:
            return {"error": f"Symbol {symbol} not found"}

        return {
            "symbol": symbol,
            "base": market.get("base"),
            "quote": market.get("quote"),
            "type": market.get("type"),
            "precision": market.get("precision", {}),
            "limits": market.get("limits", {}),
            "active": market.get("active", True)
        }

    def format_amount(self, symbol: str, amount: Decimal) -> Decimal:
        """수량 포맷팅 (심볼 precision 적용)"""
        info = self.get_symbol_info(symbol)
        if "error" in info:
            return amount

        precision = info.get("precision", {}).get("amount", 8)
        return Decimal(str(amount)).quantize(
            Decimal("0.1") ** precision
        )

    def format_price(self, symbol: str, price: Decimal) -> Decimal:
        """가격 포맷팅 (심볼 precision 적용)"""
        info = self.get_symbol_info(symbol)
        if "error" in info:
            return price

        precision = info.get("precision", {}).get("price", 8)
        return Decimal(str(price)).quantize(
            Decimal("0.1") ** precision
        )

    async def test_connection(self) -> Dict[str, Any]:
        """연결 테스트"""
        result = {
            "exchange": self.exchange_id,
            "connected": self.is_connected,
            "sandbox": self.sandbox,
            "testnet": self.testnet
        }

        if self.is_connected:
            try:
                # 시간 조회로 연결 확인
                time = await self.exchange.fetch_time()
                result["server_time"] = time
                result["status"] = "ok"
            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)

        return result


class ExchangeManager:
    """다중 거래소 관리자"""

    def __init__(self):
        self.connectors: Dict[str, ExchangeConnector] = {}

    async def add_exchange(
        self,
        exchange_id: str,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        sandbox: bool = True
    ) -> bool:
        """거래소 추가 및 연결"""
        connector = ExchangeConnector(
            exchange_id=exchange_id,
            api_key=api_key,
            api_secret=api_secret,
            sandbox=sandbox
        )

        if await connector.connect():
            self.connectors[exchange_id] = connector
            return True
        return False

    def get_connector(self, exchange_id: str) -> Optional[ExchangeConnector]:
        """거래소 커넥터 조회"""
        return self.connectors.get(exchange_id)

    async def close_all(self):
        """모든 거래소 연결 해제"""
        for connector in self.connectors.values():
            await connector.disconnect()
        self.connectors.clear()

    async def get_all_balances(self, currency: Optional[str] = None) -> Dict[str, Any]:
        """모든 거래소 잔고 조회"""
        balances = {}
        for exchange_id, connector in self.connectors.items():
            balances[exchange_id] = await connector.get_balance(currency)
        return balances


class MockExchangeConnector(ExchangeConnector):
    """테스트용 Mock 거래소 연결"""

    def __init__(self, exchange_id: str = "binance"):
        super().__init__(exchange_id=exchange_id, sandbox=True)
        self._mock_balance = {
            "USDT": {"free": 10000.0, "used": 0.0, "total": 10000.0},
            "BTC": {"free": 1.0, "used": 0.0, "total": 1.0}
        }
        self._mock_price = 50000.0
        self._orders = []

    async def connect(self) -> bool:
        """Mock 연결"""
        self._connected = True
        logger.info(f"Mock connected to {self.exchange_id}")
        return True

    async def disconnect(self):
        """Mock 연결 해제"""
        self._connected = False

    async def get_balance(self, currency: Optional[str] = None) -> Dict[str, Any]:
        """Mock 잔고"""
        if currency:
            return self._mock_balance.get(currency, {"free": 0, "used": 0, "total": 0})
        return self._mock_balance

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Mock 티커"""
        return {
            "symbol": symbol,
            "last": Decimal(str(self._mock_price)),
            "bid": Decimal(str(self._mock_price * 0.999)),
            "ask": Decimal(str(self._mock_price * 1.001)),
            "high": Decimal(str(self._mock_price * 1.05)),
            "low": Decimal(str(self._mock_price * 0.95)),
            "volume": Decimal("1000"),
            "timestamp": 1234567890
        }

    def set_mock_price(self, price: float):
        """Mock 가격 설정"""
        self._mock_price = price

    def set_mock_balance(self, currency: str, amount: float):
        """Mock 잔고 설정"""
        self._mock_balance[currency] = {
            "free": amount,
            "used": 0.0,
            "total": amount
        }


# 전역 인스턴스
_default_connector: Optional[ExchangeConnector] = None

async def get_default_connector() -> ExchangeConnector:
    """기본 거래소 커넥터 반환 (싱글톤)"""
    global _default_connector
    if _default_connector is None:
        _default_connector = ExchangeConnector()
        await _default_connector.connect()
    return _default_connector


def reset_default_connector():
    """기본 커넥터 초기화"""
    global _default_connector
    _default_connector = None


if __name__ == "__main__":
    # 테스트
    async def test():
        # Mock 커넥터 테스트
        mock = MockExchangeConnector("binance")
        await mock.connect()

        print("Mock Balance:", await mock.get_balance("USDT"))
        print("Mock Ticker:", await mock.get_ticker("BTC/USDT"))

        await mock.disconnect()

    asyncio.run(test())

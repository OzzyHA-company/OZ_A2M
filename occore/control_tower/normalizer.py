"""
OZ_A2M 제1부서: 관제탑센터 - 데이터 정제 파이프라인

다양한 거래소의 데이터를 표준 포맷으로 변환 및 검증
"""

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, Optional, List, Union

from .exchange_adapter import TickerData, OrderBookData, TradeData

logger = logging.getLogger(__name__)


class DataNormalizer:
    """
    데이터 정제 및 표준화

    기능:
    - 가격/수량 정밀도 표준화
    - 데이터 유효성 검증
    - 이상치 탐지 및 필터링
    - 시간대 표준화 (UTC)
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._price_precision = self.config.get('price_precision', 8)
        self._quantity_precision = self.config.get('quantity_precision', 8)
        self._max_price_deviation = self.config.get('max_price_deviation', 0.5)  # 50%

    def normalize_ticker(self, ticker: TickerData) -> TickerData:
        """티커 데이터 정제"""
        try:
            # 가격 유효성 검증
            if ticker.last <= 0:
                logger.warning(f"Invalid last price for {ticker.symbol}: {ticker.last}")
                ticker.last = Decimal('0')

            if ticker.bid <= 0 or ticker.ask <= 0:
                logger.warning(f"Invalid bid/ask for {ticker.symbol}: bid={ticker.bid}, ask={ticker.ask}")

            # 스프레드 검증
            if ticker.ask < ticker.bid:
                logger.warning(f"Negative spread for {ticker.symbol}")
                # bid/ask 교환
                ticker.bid, ticker.ask = ticker.ask, ticker.bid

            # 가격 정밀도 표준화
            ticker.last = self._normalize_decimal(ticker.last, self._price_precision)
            ticker.bid = self._normalize_decimal(ticker.bid, self._price_precision)
            ticker.ask = self._normalize_decimal(ticker.ask, self._price_precision)
            ticker.high_24h = self._normalize_decimal(ticker.high_24h, self._price_precision)
            ticker.low_24h = self._normalize_decimal(ticker.low_24h, self._price_precision)

            # 수량 정밀도 표준화
            ticker.volume_24h = self._normalize_decimal(ticker.volume_24h, self._quantity_precision)

            # 24시간 변동률 범위 제한
            ticker.change_24h_pct = max(-100, min(100, ticker.change_24h_pct))

            return ticker

        except Exception as e:
            logger.error(f"Error normalizing ticker: {e}")
            return ticker

    def normalize_order_book(self, order_book: OrderBookData) -> OrderBookData:
        """오더북 데이터 정제"""
        try:
            # bid/ask 정렬 및 필터링
            order_book.bids = self._normalize_orders(order_book.bids, is_bid=True)
            order_book.asks = self._normalize_orders(order_book.asks, is_bid=False)

            # 가격 역전 검증
            if order_book.bids and order_book.asks:
                highest_bid = order_book.bids[0][0]
                lowest_ask = order_book.asks[0][0]

                if highest_bid >= lowest_ask:
                    logger.warning(f"Order book crossed for {order_book.symbol}")

            return order_book

        except Exception as e:
            logger.error(f"Error normalizing order book: {e}")
            return order_book

    def normalize_trades(self, trades: List[TradeData]) -> List[TradeData]:
        """거래 데이터 정제"""
        normalized = []

        for trade in trades:
            try:
                # 가격/수량 정밀도 표준화
                trade.price = self._normalize_decimal(trade.price, self._price_precision)
                trade.amount = self._normalize_decimal(trade.amount, self._quantity_precision)

                # side 표준화
                trade.side = trade.side.lower()
                if trade.side not in ['buy', 'sell']:
                    logger.warning(f"Invalid trade side: {trade.side}")
                    continue

                normalized.append(trade)

            except Exception as e:
                logger.error(f"Error normalizing trade: {e}")

        return normalized

    def normalize_exchange_data(self, data: Any) -> Any:
        """거래소 데이터 패키지 정제"""
        try:
            # 티커 데이터 정제
            for symbol, ticker in data.tickers.items():
                data.tickers[symbol] = self.normalize_ticker(ticker)

            # 오더북 데이터 정제
            for symbol, order_book in data.order_books.items():
                data.order_books[symbol] = self.normalize_order_book(order_book)

            # 거래 데이터 정제
            for symbol, trades in data.recent_trades.items():
                data.recent_trades[symbol] = self.normalize_trades(trades)

            return data

        except Exception as e:
            logger.error(f"Error normalizing exchange data: {e}")
            return data

    def _normalize_decimal(self, value: Decimal, precision: int) -> Decimal:
        """Decimal 값 정밀도 표준화"""
        try:
            if value is None or value < 0:
                return Decimal('0')

            # 지수 표기법 방지 및 정밀도 적용
            quantize_str = '0.' + '0' * precision
            return value.quantize(Decimal(quantize_str))

        except (InvalidOperation, ValueError):
            return Decimal('0')

    def _normalize_orders(self, orders: List[tuple], is_bid: bool) -> List[tuple]:
        """오더 정렬 및 필터링"""
        # 유효한 오더만 필터링
        valid_orders = [
            (price, amount)
            for price, amount in orders
            if price > 0 and amount > 0
        ]

        # 가격 기준 정렬
        valid_orders.sort(key=lambda x: x[0], reverse=is_bid)

        # 정밀도 표준화
        normalized = [
            (
                self._normalize_decimal(price, self._price_precision),
                self._normalize_decimal(amount, self._quantity_precision)
            )
            for price, amount in valid_orders
        ]

        return normalized

    def detect_outliers(self, data_points: List[Decimal], threshold: float = 3.0) -> List[int]:
        """이상치 탐지 (Z-score 기반)"""
        if len(data_points) < 3:
            return []

        values = [float(d) for d in data_points]
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std_dev = variance ** 0.5

        if std_dev == 0:
            return []

        outliers = []
        for i, value in enumerate(values):
            z_score = abs(value - mean) / std_dev
            if z_score > threshold:
                outliers.append(i)

        return outliers

    def validate_price_consistency(self, tickers: Dict[str, TickerData]) -> Dict[str, Any]:
        """다중 거래소 가격 일관성 검증"""
        if len(tickers) < 2:
            return {'valid': True, 'issues': []}

        prices = {ex: float(t.last) for ex, t in tickers.items() if t.last > 0}

        if len(prices) < 2:
            return {'valid': True, 'issues': []}

        avg_price = sum(prices.values()) / len(prices)
        issues = []

        for exchange, price in prices.items():
            deviation = abs(price - avg_price) / avg_price
            if deviation > self._max_price_deviation:
                issues.append({
                    'exchange': exchange,
                    'price': price,
                    'avg_price': avg_price,
                    'deviation_pct': deviation * 100,
                    'severity': 'high' if deviation > 0.8 else 'medium'
                })

        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'avg_price': avg_price,
            'price_count': len(prices)
        }

    def sanitize_symbol(self, symbol: str) -> str:
        """심볼 문자열 정제"""
        # 대문자 표준화
        symbol = symbol.upper()

        # 공백 제거
        symbol = symbol.replace(' ', '')

        # 구분자 표준화 (BTC/USDT -> BTC-USDT)
        symbol = symbol.replace('/', '-')

        return symbol

    def format_for_storage(self, data: Any) -> Dict:
        """저장용 포맷으로 변환"""
        if isinstance(data, TickerData):
            return {
                'symbol': data.symbol,
                'exchange': data.exchange,
                'timestamp': data.timestamp.isoformat(),
                'bid': str(data.bid),
                'ask': str(data.ask),
                'last': str(data.last),
                'volume_24h': str(data.volume_24h),
                'change_24h_pct': data.change_24h_pct,
                'high_24h': str(data.high_24h),
                'low_24h': str(data.low_24h)
            }

        elif isinstance(data, TradeData):
            return {
                'symbol': data.symbol,
                'exchange': data.exchange,
                'timestamp': data.timestamp.isoformat(),
                'side': data.side,
                'amount': str(data.amount),
                'price': str(data.price),
                'trade_id': data.trade_id
            }

        return {}

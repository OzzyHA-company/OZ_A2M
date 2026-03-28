"""
OZ_A2M 제1부서: 관제탑센터 - OpenBB 통합 어댑터

OpenBB Platform을 통한 주식, ETF, 경제, 뉴스 데이터 수집
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)


class OpenBBAdapter:
    """
    OpenBB Platform 통합 어댑터

    기능:
    - 주식 가격/거래량 데이터 수집 (yfinance, etc)
    - ETF 정보 및 성과 데이터
    - 경제 캘린더 및 지표
    - SEC 공시 데이터
    - 암호화폐 가격 데이터
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._ob = None
        self._connected = False

    def connect(self) -> bool:
        """OpenBB Platform 연결"""
        try:
            from openbb import ob
            self._ob = ob
            self._connected = True
            logger.info("OpenBB adapter connected")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to OpenBB: {e}")
            return False

    def get_stock_price(self, symbol: str, interval: str = "1d",
                       start: Optional[str] = None,
                       end: Optional[str] = None) -> Optional[Dict]:
        """
        주식 가격 데이터 수집

        Args:
            symbol: 종목 티커 (AAPL, TSLA, etc)
            interval: 시간 간격 (1m, 5m, 1h, 1d)
            start: 시작일 (YYYY-MM-DD)
            end: 종료일 (YYYY-MM-DD)
        """
        if not self._connected:
            if not self.connect():
                return None

        try:
            # 기본값 설정
            if not end:
                end = datetime.now().strftime("%Y-%m-%d")
            if not start:
                start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

            # OpenBB 데이터 조회
            data = self._ob.equity.price.historical(
                symbol=symbol,
                start_date=start,
                end_date=end,
                interval=interval
            )

            return {
                "symbol": symbol,
                "interval": interval,
                "data": data.to_dict() if hasattr(data, 'to_dict') else data,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Error fetching stock price for {symbol}: {e}")
            # Fallback to yfinance
            return self._get_stock_price_yfinance(symbol, interval, start, end)

    def _get_stock_price_yfinance(self, symbol: str, interval: str,
                                  start: Optional[str] = None,
                                  end: Optional[str] = None) -> Optional[Dict]:
        """yfinance fallback"""
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            data = ticker.history(start=start, end=end, interval=interval)

            return {
                "symbol": symbol,
                "interval": interval,
                "data": data.to_dict(),
                "timestamp": datetime.now().isoformat(),
                "source": "yfinance"
            }
        except Exception as e:
            logger.error(f"yfinance fallback failed: {e}")
            return None

    def get_economic_calendar(self, start: Optional[str] = None,
                              end: Optional[str] = None) -> Optional[List[Dict]]:
        """경제 캘린더 데이터"""
        if not self._connected:
            if not self.connect():
                return None

        try:
            if not start:
                start = datetime.now().strftime("%Y-%m-%d")
            if not end:
                end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

            calendar = self._ob.economy.calendar(
                start_date=start,
                end_date=end
            )

            return calendar.to_dict('records') if hasattr(calendar, 'to_dict') else []

        except Exception as e:
            logger.error(f"Error fetching economic calendar: {e}")
            return None

    def get_etf_holdings(self, symbol: str) -> Optional[Dict]:
        """ETF 보유 종목 데이터"""
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            holdings = ticker.institutional_holders

            if holdings is not None:
                return {
                    "symbol": symbol,
                    "holdings": holdings.to_dict(),
                    "timestamp": datetime.now().isoformat()
                }
            return None

        except Exception as e:
            logger.error(f"Error fetching ETF holdings for {symbol}: {e}")
            return None

    def get_crypto_price(self, symbol: str = "BTC-USD") -> Optional[Dict]:
        """암호화폐 가격 데이터"""
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d", interval="1m")

            if not data.empty:
                latest = data.iloc[-1]
                return {
                    "symbol": symbol,
                    "price": float(latest['Close']),
                    "volume": float(latest['Volume']),
                    "timestamp": datetime.now().isoformat()
                }
            return None

        except Exception as e:
            logger.error(f"Error fetching crypto price for {symbol}: {e}")
            return None

    def get_company_news(self, symbol: str, limit: int = 10) -> Optional[List[Dict]]:
        """기업 뉴스 수집"""
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            news = ticker.news[:limit]

            return [
                {
                    "title": item.get('title'),
                    "publisher": item.get('publisher'),
                    "published": item.get('published'),
                    "link": item.get('link'),
                    "symbol": symbol
                }
                for item in news
            ]

        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")
            return None


# 싱글톤 인스턴스
_ob_adapter_instance: Optional[OpenBBAdapter] = None


def get_openbb_adapter() -> OpenBBAdapter:
    """OpenBB 어댑터 싱글톤 인스턴스 가져오기"""
    global _ob_adapter_instance
    if _ob_adapter_instance is None:
        _ob_adapter_instance = OpenBBAdapter()
    return _ob_adapter_instance

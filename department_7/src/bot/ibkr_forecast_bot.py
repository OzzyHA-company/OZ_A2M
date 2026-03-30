"""
IBKR Forecast Trader Bot - 인터랙티브 브로커스 예측 트레이더 봇
STEP 12: OZ_A2M 완결판

설정:
- 거래소: Interactive Brokers (TWS/Gateway)
- AI 기반 예측 매매
- 자본: $10
- Mock 모드 지원 (연결 실패 시)
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from decimal import Decimal
from enum import Enum

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger
from lib.messaging.mqtt_client import MQTTClient, MQTTConfig
from lib.messaging.event_bus import EventBus, get_event_bus
from occore.control_tower.llm_analyzer import LLMAnalyzer

logger = get_logger(__name__)

# IBKR SDK import (optional)
try:
    from ib_insync import IB, Stock, MarketOrder
    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False
    logger.warning("ib-insync not installed, using mock mode")


class IBKRStatus(str, Enum):
    """IBKR 봇 상태"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    MOCK = "mock"


@dataclass
class IBKRPosition:
    """IBKR 포지션"""
    symbol: str
    side: str
    quantity: int
    avg_cost: float
    unrealized_pnl: float


@dataclass
class IBKRTrade:
    """IBKR 거래 기록"""
    id: str
    symbol: str
    side: str
    quantity: int
    price: float
    timestamp: datetime
    pnl: Optional[float] = None
    forecast_confidence: float = 0.0


class IBKRForecastTraderBot:
    """
    Interactive Brokers AI 예측 트레이더 봇

    전략:
    - LLM 기반 시장 예측
    - 예측 확률 기반 포지션 사이징
    - AAPL, MSFT, GOOGL 등 주요 주식 대상
    """

    def __init__(
        self,
        bot_id: str = "ibkr_forecast_001",
        symbols: List[str] = None,
        capital: float = 10.0,
        forecast_threshold: float = 0.7,
        tws_host: str = "127.0.0.1",
        tws_port: int = 7497,
        client_id: int = 1,
        mock_mode: bool = False,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        telegram_alerts: bool = True
    ):
        self.bot_id = bot_id
        self.symbols = symbols or ["AAPL", "MSFT", "GOOGL"]
        self.capital = capital
        self.forecast_threshold = forecast_threshold
        self.tws_host = tws_host
        self.tws_port = tws_port
        self.client_id = client_id
        self.mock_mode = mock_mode
        self.telegram_alerts = telegram_alerts

        # 상태
        self.status = IBKRStatus.IDLE
        self.ib: Optional[Any] = None
        self.positions: Dict[str, IBKRPosition] = {}
        self.trades: List[IBKRTrade] = []
        self.market_data: Dict[str, Any] = {}

        # LLM Analyzer
        self.llm_analyzer = LLMAnalyzer()

        # MQTT
        mqtt_config = MQTTConfig(host=mqtt_host, port=mqtt_port, client_id=bot_id)
        self.mqtt = MQTTClient(config=mqtt_config)

        # EventBus
        self.event_bus: Optional[EventBus] = None

        # Telegram
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        # 통계
        self.total_trades: int = 0
        self.winning_trades: int = 0
        self.total_pnl: float = 0.0
        self.forecasts_made: int = 0

        # 콜백
        self.on_trade: Optional[Callable[[IBKRTrade], None]] = None
        self.on_forecast: Optional[Callable[[Dict], None]] = None

        logger.info(f"IBKRForecastTraderBot {bot_id} initialized (capital=${capital})")

    def _load_credentials(self) -> Dict[str, str]:
        """.env에서 IBKR 자격증명 로드"""
        return {
            "client_id": os.environ.get("IBKR_CLIENT_ID", "1"),
            "tws_userid": os.environ.get("TWS_USERID", ""),
            "tws_password": os.environ.get("TWS_PASSWORD", "")
        }

    async def initialize(self):
        """봇 초기화"""
        if not IBKR_AVAILABLE:
            logger.warning("ib-insync not available, using mock mode")
            self.mock_mode = True

        if self.mock_mode:
            await self._initialize_mock()
        else:
            await self._initialize_live()

        # EventBus 연결
        try:
            self.event_bus = get_event_bus(mqtt_host="localhost", mqtt_port=1883)
            await self.event_bus.connect()
            logger.info("EventBus connected")
        except Exception as e:
            logger.warning(f"EventBus connection failed: {e}")
            self.event_bus = None

    async def _initialize_live(self):
        """실제 TWS 연결 초기화"""
        try:
            self.ib = IB()
            await self.ib.connectAsync(self.tws_host, self.tws_port, clientId=self.client_id)

            logger.info(f"Connected to TWS at {self.tws_host}:{self.tws_port}")
            self.status = IBKRStatus.RUNNING

            # 시작 알림
            await self._send_telegram_notification(
                f"📈 IBKR 예측트레이더 시작\n"
                f"종목: {', '.join(self.symbols)}\n"
                f"자본: ${self.capital}\n"
                f"예측 임계값: {self.forecast_threshold}"
            )

        except Exception as e:
            logger.error(f"Failed to connect to TWS: {e}")
            logger.info("Falling back to mock mode")
            await self._initialize_mock()

    async def _initialize_mock(self):
        """Mock 모드 초기화"""
        self.mock_mode = True
        self.status = IBKRStatus.MOCK

        # Mock 데이터 초기화
        for symbol in self.symbols:
            self.market_data[symbol] = {
                "price": 150.0 + hash(symbol) % 100,
                "volume": 1000000
            }

        logger.info("IBKR mock mode initialized")

        # 시작 알림
        await self._send_telegram_notification(
            f"📈 IBKR 예측트레이더 시작 (Mock)\n"
            f"종목: {', '.join(self.symbols)}\n"
            f"자본: ${self.capital}"
        )

    async def run(self):
        """메인 루프"""
        try:
            await self.initialize()
        except Exception as e:
            logger.error(f"IBKR bot initialization failed: {e}")
            self.status = IBKRStatus.ERROR
            raise

        try:
            while self.status in [IBKRStatus.RUNNING, IBKRStatus.MOCK]:
                try:
                    # 시장 데이터 업데이트
                    await self._update_market_data()

                    # AI 예측 수행
                    for symbol in self.symbols:
                        forecast = await self._generate_forecast(symbol)

                        if forecast and forecast.get("confidence", 0) > self.forecast_threshold:
                            await self._execute_based_on_forecast(symbol, forecast)

                    # 포지션 관리
                    await self._manage_positions()

                    await asyncio.sleep(60)  # 1분마다 체크

                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    await asyncio.sleep(30)

        except asyncio.CancelledError:
            logger.info("IBKR bot cancelled")
            await self.stop()
        except Exception as e:
            logger.error(f"IBKR bot error: {e}")
            self.status = IBKRStatus.ERROR
            await self.stop()
            raise

    async def _update_market_data(self):
        """시장 데이터 업데이트"""
        if self.mock_mode:
            # Mock 데이터 업데이트
            import random
            for symbol in self.symbols:
                if symbol in self.market_data:
                    self.market_data[symbol]["price"] *= (1 + random.uniform(-0.005, 0.005))
        else:
            # 실제 TWS에서 데이터 조회
            try:
                for symbol in self.symbols:
                    contract = Stock(symbol, "SMART", "USD")
                    ticker = self.ib.reqMktData(contract)
                    if ticker.last:
                        self.market_data[symbol] = {
                            "price": ticker.last,
                            "volume": ticker.volume or 0
                        }
            except Exception as e:
                logger.error(f"Failed to update market data: {e}")

    async def _generate_forecast(self, symbol: str) -> Optional[Dict]:
        """LLM 기반 예측 생성"""
        try:
            # 시장 데이터 준비
            market_context = {
                "symbol": symbol,
                "price": self.market_data.get(symbol, {}).get("price", 0),
                "volume": self.market_data.get(symbol, {}).get("volume", 0)
            }

            # LLM 분석
            analysis = await self.llm_analyzer.analyze(market_context)
            self.forecasts_made += 1

            forecast = {
                "symbol": symbol,
                "direction": analysis.get("direction", "neutral"),
                "confidence": analysis.get("confidence", 0.5),
                "target_price": analysis.get("target_price", market_context["price"]),
                "reasoning": analysis.get("reasoning", "")
            }

            if self.on_forecast:
                self.on_forecast(forecast)

            return forecast

        except Exception as e:
            logger.error(f"Failed to generate forecast for {symbol}: {e}")
            return None

    async def _execute_based_on_forecast(self, symbol: str, forecast: Dict):
        """예측 기반 거래 실행"""
        direction = forecast.get("direction", "neutral")
        confidence = forecast.get("confidence", 0)

        # 현재 포지션 확인
        current_position = self.positions.get(symbol)

        if direction == "bullish" and not current_position:
            # 매수 신호
            await self._place_buy_order(symbol, forecast)
        elif direction == "bearish" and current_position:
            # 매도 신호
            await self._place_sell_order(symbol, forecast)

    async def _place_buy_order(self, symbol: str, forecast: Dict):
        """매수 주문"""
        try:
            price = self.market_data.get(symbol, {}).get("price", 0)
            quantity = int(self.capital / len(self.symbols) / price)

            if quantity <= 0:
                return

            if self.mock_mode:
                # Mock 주문
                order_id = f"mock_{datetime.utcnow().timestamp()}"
            else:
                # 실제 주문
                contract = Stock(symbol, "SMART", "USD")
                order = MarketOrder("BUY", quantity)
                trade = self.ib.placeOrder(contract, order)
                order_id = str(trade.order.orderId)

            # 포지션 기록
            self.positions[symbol] = IBKRPosition(
                symbol=symbol,
                side="long",
                quantity=quantity,
                avg_cost=price,
                unrealized_pnl=0.0
            )

            # 거래 기록
            trade_record = IBKRTrade(
                id=order_id,
                symbol=symbol,
                side="buy",
                quantity=quantity,
                price=price,
                timestamp=datetime.utcnow(),
                forecast_confidence=forecast.get("confidence", 0)
            )
            self.trades.append(trade_record)
            self.total_trades += 1

            logger.info(f"Buy order placed: {symbol} x {quantity} @ ${price}")

            # Telegram 알림
            await self._send_telegram_notification(
                f"📥 IBKR 매수 체결\n"
                f"종목: {symbol}\n"
                f"수량: {quantity}\n"
                f"가격: ${price:.2f}\n"
                f"예측 신뢰도: {forecast.get('confidence', 0):.1%}"
            )

            if self.on_trade:
                self.on_trade(trade_record)

        except Exception as e:
            logger.error(f"Failed to place buy order for {symbol}: {e}")

    async def _place_sell_order(self, symbol: str, forecast: Dict):
        """매도 주문"""
        try:
            position = self.positions.get(symbol)
            if not position:
                return

            price = self.market_data.get(symbol, {}).get("price", 0)
            quantity = position.quantity

            # 손익 계산
            pnl = (price - position.avg_cost) * quantity

            if self.mock_mode:
                order_id = f"mock_{datetime.utcnow().timestamp()}"
            else:
                contract = Stock(symbol, "SMART", "USD")
                order = MarketOrder("SELL", quantity)
                trade = self.ib.placeOrder(contract, order)
                order_id = str(trade.order.orderId)

            # 거래 기록
            trade_record = IBKRTrade(
                id=order_id,
                symbol=symbol,
                side="sell",
                quantity=quantity,
                price=price,
                timestamp=datetime.utcnow(),
                pnl=pnl,
                forecast_confidence=forecast.get("confidence", 0)
            )
            self.trades.append(trade_record)
            self.total_trades += 1
            self.total_pnl += pnl

            if pnl > 0:
                self.winning_trades += 1

            # 포지션 클리어
            del self.positions[symbol]

            logger.info(f"Sell order placed: {symbol} x {quantity} @ ${price}, PnL: ${pnl:.2f}")

            # Telegram 알림
            emoji = "🟢" if pnl > 0 else "🔴"
            await self._send_telegram_notification(
                f"{emoji} IBKR 매도 체결\n"
                f"종목: {symbol}\n"
                f"수량: {quantity}\n"
                f"가격: ${price:.2f}\n"
                f"PnL: ${pnl:.2f}"
            )

            if self.on_trade:
                self.on_trade(trade_record)

        except Exception as e:
            logger.error(f"Failed to place sell order for {symbol}: {e}")

    async def _manage_positions(self):
        """포지션 관리"""
        for symbol, position in list(self.positions.items()):
            try:
                current_price = self.market_data.get(symbol, {}).get("price", 0)
                if current_price > 0:
                    unrealized_pnl = (current_price - position.avg_cost) * position.quantity
                    position.unrealized_pnl = unrealized_pnl

                    # 손절 로직 (-5%)
                    if unrealized_pnl < -position.avg_cost * position.quantity * 0.05:
                        logger.info(f"Stop loss triggered for {symbol}")
                        await self._place_sell_order(symbol, {"confidence": 0.5})

            except Exception as e:
                logger.error(f"Error managing position for {symbol}: {e}")

    async def stop(self):
        """봇 중지"""
        self.status = IBKRStatus.IDLE

        # 모든 포지션 정리
        for symbol in list(self.positions.keys()):
            await self._place_sell_order(symbol, {"confidence": 0.5})

        # TWS 연결 해제
        if not self.mock_mode and self.ib:
            try:
                self.ib.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting from TWS: {e}")

        # EventBus 연결 해제
        if self.event_bus:
            await self.event_bus.disconnect()

        await self.mqtt.disconnect()

        # 일일 리포트
        await self._send_daily_report()

        logger.info(f"IBKR Forecast bot {self.bot_id} stopped")

    async def _send_telegram_notification(self, message: str):
        """Telegram 알림 발송"""
        if not self.telegram_alerts or not self.telegram_bot_token or not self.telegram_chat_id:
            return

        try:
            import aiohttp
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        logger.warning(f"Telegram notification failed: {resp.status}")
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")

    async def _send_daily_report(self):
        """일일 리포트 발송"""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        await self._send_telegram_notification(
            f"📊 IBKR Forecast Bot 일일 리포트\n"
            f"모드: {'Mock' if self.mock_mode else 'Live'}\n"
            f"예측 횟수: {self.forecasts_made}회\n"
            f"총 거래: {self.total_trades}회\n"
            f"승률: {win_rate:.1f}%\n"
            f"총 PnL: ${self.total_pnl:.2f}"
        )

    def get_status(self) -> Dict[str, Any]:
        """봇 상태 반환"""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0

        return {
            "bot_id": self.bot_id,
            "bot_type": "ibkr_forecast",
            "status": self.status.value,
            "symbols": self.symbols,
            "capital": self.capital,
            "mock_mode": self.mock_mode,
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_cost": p.avg_cost,
                    "unrealized_pnl": p.unrealized_pnl
                }
                for p in self.positions.values()
            ],
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "win_rate": win_rate,
            "total_pnl": self.total_pnl,
            "forecasts_made": self.forecasts_made,
            "timestamp": datetime.utcnow().isoformat()
        }


async def main():
    """단독 실행용"""
    bot = IBKRForecastTraderBot(
        bot_id="ibkr_forecast_001",
        symbols=["AAPL", "MSFT"],
        capital=10.0,
        mock_mode=True
    )

    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()
        print("\n📊 Final Stats:")
        status = bot.get_status()
        print(f"   Total Trades: {status['total_trades']}")
        print(f"   Win Rate: {status['win_rate']:.1f}%")
        print(f"   Total PnL: ${status['total_pnl']:.2f}")


if __name__ == "__main__":
    asyncio.run(main())

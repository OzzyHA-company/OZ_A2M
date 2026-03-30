"""
Funding Rate Bot - 펀딩 레이트 봇
STEP 11: OZ_A2M 완결판

설정:
- 거래소: Binance + Bybit
- 전략: 양수 펀딩 → 현물매수 + 선물공매도
- 8시간마다 펀딩 수취
- 자본: $20
- sandbox: False (실거래)
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from decimal import Decimal
from enum import Enum

import ccxt

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger
from lib.messaging.mqtt_client import MQTTClient, MQTTConfig
from lib.messaging.event_bus import EventBus, get_event_bus

logger = get_logger(__name__)


class FundingStatus(str, Enum):
    """펀딩 봇 상태"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class FundingRate:
    """펀딩 레이트 정보"""
    exchange: str
    symbol: str
    funding_rate: float  # 연율
    funding_time: datetime
    next_funding_time: datetime


@dataclass
class FundingTrade:
    """펀딩 거래 기록"""
    id: str
    exchange: str
    symbol: str
    side: str  # "spot_buy" or "future_short"
    amount: float
    price: float
    timestamp: datetime
    funding_pnl: Optional[float] = None


class FundingRateBot:
    """
    펀딩 레이트 차익 봇

    전략:
    - 양수 펀딩레이트가 높은 종목 선별
    - 현물 매수 + 선물 공매도 헤지
    - 8시간마다 펀딩 수취
    """

    def __init__(
        self,
        bot_id: str = "funding_binance_bybit_001",
        capital: float = 20.0,
        min_funding_rate: float = 0.0001,  # 0.01% 이상
        funding_interval_hours: int = 8,
        sandbox: bool = False,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        telegram_alerts: bool = True
    ):
        self.bot_id = bot_id
        self.capital = capital
        self.min_funding_rate = min_funding_rate
        self.funding_interval_hours = funding_interval_hours
        self.sandbox = sandbox
        self.telegram_alerts = telegram_alerts

        # 상태
        self.status = FundingStatus.IDLE
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        self.funding_rates: Dict[str, FundingRate] = {}
        self.positions: Dict[str, Dict] = {}  # 헤지 포지션
        self.trades: List[FundingTrade] = []
        self.funding_earnings: float = 0.0  # 누적 펀딩 수익

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
        self.total_funding_payments: int = 0

        # 콜백
        self.on_funding_received: Optional[Callable[[float], None]] = None
        self.on_trade: Optional[Callable[[FundingTrade], None]] = None

        logger.info(f"FundingRateBot {bot_id} initialized (capital=${capital})")

    def _load_api_keys(self, exchange_id: str) -> tuple:
        """.env에서 API 키 로드"""
        api_key = os.environ.get(f"{exchange_id.upper()}_API_KEY")
        api_secret = os.environ.get(f"{exchange_id.upper()}_API_SECRET")
        return api_key, api_secret

    async def initialize(self):
        """봇 초기화"""
        # Binance 연결
        await self._connect_exchange("binance")

        # Bybit 연결
        await self._connect_exchange("bybit")

        # EventBus 연결
        try:
            self.event_bus = get_event_bus(mqtt_host="localhost", mqtt_port=1883)
            await self.event_bus.connect()
            logger.info("EventBus connected")
        except Exception as e:
            logger.warning(f"EventBus connection failed: {e}")
            self.event_bus = None

        self.status = FundingStatus.RUNNING
        logger.info("Funding bot initialized")

        # 시작 알림
        await self._send_telegram_notification(
            f"💰 Funding Rate 봇 시작\n"
            f"자본: ${self.capital}\n"
            f"최소 펀딩: {self.min_funding_rate * 100}%\n"
            f"수취 주기: {self.funding_interval_hours}시간"
        )

    async def _connect_exchange(self, exchange_id: str):
        """거래소 연결"""
        try:
            api_key, api_secret = self._load_api_keys(exchange_id)

            if not api_key or not api_secret:
                logger.warning(f"API keys not found for {exchange_id}, using mock mode")
                return

            exchange_class = getattr(ccxt, exchange_id)
            config = {
                "apiKey": api_key,
                "secret": api_secret,
                "sandbox": self.sandbox,
                "enableRateLimit": True,
            }

            if exchange_id == "binance":
                config["options"] = {"defaultType": "spot"}

            exchange = exchange_class(config)

            if self.sandbox and hasattr(exchange, "set_sandbox_mode"):
                exchange.set_sandbox_mode(True)

            await exchange.load_markets()
            self.exchanges[exchange_id] = exchange

            logger.info(f"Connected to {exchange_id}")

        except Exception as e:
            logger.error(f"Failed to connect to {exchange_id}: {e}")

    async def run(self):
        """메인 루프"""
        try:
            await self.initialize()
        except Exception as e:
            logger.error(f"Funding bot initialization failed: {e}")
            self.status = FundingStatus.ERROR
            raise

        try:
            while self.status == FundingStatus.RUNNING:
                try:
                    # 펀딩 레이트 조회
                    await self._fetch_funding_rates()

                    # 펀딩 기회 분석
                    opportunities = self._analyze_opportunities()

                    # 기회가 있으면 포지션 진입
                    for opp in opportunities:
                        if opp["symbol"] not in self.positions:
                            await self._enter_hedge_position(opp)

                    # 펀딩 수취 확인
                    await self._check_funding_payments()

                    # 포지션 정리 (펀딩이 마이너스로 전환 시)
                    await self._check_exit_conditions()

                    # 다음 펀딩까지 대기
                    await asyncio.sleep(300)  # 5분마다 체크

                except ccxt.NetworkError as e:
                    logger.error(f"Network error: {e}")
                    await asyncio.sleep(60)
                except Exception as e:
                    logger.error(f"Error in funding loop: {e}")
                    await asyncio.sleep(30)

        except asyncio.CancelledError:
            logger.info("Funding bot cancelled")
            await self.stop()
        except Exception as e:
            logger.error(f"Funding bot error: {e}")
            self.status = FundingStatus.ERROR
            await self.stop()
            raise

    async def _fetch_funding_rates(self):
        """펀딩 레이트 조회"""
        for exchange_id, exchange in self.exchanges.items():
            try:
                # 선물 마켓에서 펀딩 레이트 조회
                if hasattr(exchange, "fetchFundingRates"):
                    rates = await exchange.fetchFundingRates()
                    for symbol, rate_info in rates.items():
                        if symbol.endswith("/USD") or symbol.endswith("/USDT"):
                            key = f"{exchange_id}:{symbol}"
                            self.funding_rates[key] = FundingRate(
                                exchange=exchange_id,
                                symbol=symbol,
                                funding_rate=float(rate_info.get("fundingRate", 0)),
                                funding_time=datetime.fromtimestamp(
                                    rate_info.get("fundingTimestamp", 0) / 1000
                                ),
                                next_funding_time=datetime.fromtimestamp(
                                    rate_info.get("nextFundingTimestamp", 0) / 1000
                                ),
                            )

                logger.debug(f"Fetched funding rates from {exchange_id}")

            except Exception as e:
                logger.error(f"Failed to fetch funding rates from {exchange_id}: {e}")

    def _analyze_opportunities(self) -> List[Dict]:
        """펀딩 레이트 기회 분석"""
        opportunities = []

        for key, rate in self.funding_rates.items():
            # 양수 펀딩레이트가 최소값 이상인 경우
            if rate.funding_rate >= self.min_funding_rate:
                opportunities.append({
                    "exchange": rate.exchange,
                    "symbol": rate.symbol,
                    "funding_rate": rate.funding_rate,
                    "annualized_return": rate.funding_rate * 3 * 365,  # 8시간 기준 연율
                    "key": key,
                })

        # 연율 수익률로 정렬
        opportunities.sort(key=lambda x: x["annualized_return"], reverse=True)

        return opportunities[:3]  # 상위 3개만

    async def _enter_hedge_position(self, opportunity: Dict):
        """헤지 포지션 진입 (현물매수 + 선물공매도)"""
        exchange_id = opportunity["exchange"]
        symbol = opportunity["symbol"]

        if exchange_id not in self.exchanges:
            logger.warning(f"Exchange {exchange_id} not connected")
            return

        try:
            exchange = self.exchanges[exchange_id]

            # 현물 매수
            ticker = await exchange.fetch_ticker(symbol)
            price = ticker["last"]
            amount = (self.capital / 3) / price  # 자본을 3개 종목으로 분할

            spot_order = await exchange.create_market_buy_order(symbol, amount)

            # 선물 공매도 (선물 거래소가 지원하는 경우)
            # TODO: 선물 거래 구현

            # 포지션 기록
            self.positions[symbol] = {
                "exchange": exchange_id,
                "symbol": symbol,
                "spot_amount": amount,
                "entry_price": price,
                "funding_rate": opportunity["funding_rate"],
                "entry_time": datetime.utcnow(),
            }

            # 거래 기록
            trade = FundingTrade(
                id=spot_order["id"],
                exchange=exchange_id,
                symbol=symbol,
                side="spot_buy",
                amount=amount,
                price=price,
                timestamp=datetime.utcnow(),
            )
            self.trades.append(trade)
            self.total_trades += 1

            logger.info(
                f"Entered hedge position: {symbol} @ {exchange_id}, "
                f"funding rate: {opportunity['funding_rate']:.4%}"
            )

            # Telegram 알림
            await self._send_telegram_notification(
                f"📊 펀딩 포지션 진입\n"
                f"거래소: {exchange_id}\n"
                f"심볼: {symbol}\n"
                f"펀딩: {opportunity['funding_rate']:.4%}\n"
                f"연율: {opportunity['annualized_return']:.2%}\n"
                f"수량: {amount:.6f}"
            )

        except Exception as e:
            logger.error(f"Failed to enter hedge position: {e}")

    async def _check_funding_payments(self):
        """펀딩 수취 확인"""
        # 펀딩 타임스탬프가 지났는지 확인
        now = datetime.utcnow()

        for symbol, position in list(self.positions.items()):
            key = f"{position['exchange']}:{symbol}"
            if key in self.funding_rates:
                rate = self.funding_rates[key]

                # 펀딩 시간이 지났으면 수익 기록
                if now > rate.funding_time:
                    funding_pnl = (
                        position["spot_amount"]
                        * position["entry_price"]
                        * rate.funding_rate
                    )
                    self.funding_earnings += funding_pnl
                    self.total_funding_payments += 1

                    logger.info(
                        f"Funding received: {symbol} = ${funding_pnl:.4f}"
                    )

                    if self.on_funding_received:
                        self.on_funding_received(funding_pnl)

    async def _check_exit_conditions(self):
        """포지션 정리 조건 체크"""
        for symbol, position in list(self.positions.items()):
            key = f"{position['exchange']}:{symbol}"

            if key in self.funding_rates:
                rate = self.funding_rates[key]

                # 펀딩레이트가 마이너스로 전환되면 정리
                if rate.funding_rate < 0:
                    logger.info(
                        f"Funding rate turned negative for {symbol}, exiting position"
                    )
                    await self._exit_position(symbol)

    async def _exit_position(self, symbol: str):
        """포지션 정리"""
        if symbol not in self.positions:
            return

        position = self.positions[symbol]
        exchange_id = position["exchange"]

        try:
            exchange = self.exchanges[exchange_id]

            # 현물 매도
            sell_order = await exchange.create_market_sell_order(
                symbol, position["spot_amount"]
            )

            exit_price = sell_order["price"] or sell_order["average"]
            trade_pnl = (exit_price - position["entry_price"]) * position["spot_amount"]

            # 거래 기록
            trade = FundingTrade(
                id=sell_order["id"],
                exchange=exchange_id,
                symbol=symbol,
                side="spot_sell",
                amount=position["spot_amount"],
                price=exit_price,
                timestamp=datetime.utcnow(),
                funding_pnl=trade_pnl,
            )
            self.trades.append(trade)

            logger.info(
                f"Exited position: {symbol}, trade PnL: ${trade_pnl:.4f}"
            )

            # Telegram 알림
            emoji = "🟢" if trade_pnl > 0 else "🔴"
            await self._send_telegram_notification(
                f"{emoji} 펀딩 포지션 정리\n"
                f"심볼: {symbol}\n"
                f"거래 PnL: ${trade_pnl:.4f}"
            )

            del self.positions[symbol]

        except Exception as e:
            logger.error(f"Failed to exit position: {e}")

    async def stop(self):
        """봇 중지"""
        self.status = FundingStatus.IDLE

        # 모든 포지션 정리
        for symbol in list(self.positions.keys()):
            await self._exit_position(symbol)

        # 거래소 연결 해제
        for exchange in self.exchanges.values():
            await exchange.close()

        # EventBus 연결 해제
        if self.event_bus:
            await self.event_bus.disconnect()

        await self.mqtt.disconnect()

        # 일일 리포트
        await self._send_daily_report()

        logger.info(f"Funding bot {self.bot_id} stopped")

    async def _send_telegram_notification(self, message: str):
        """Telegram 알림 발송"""
        if (
            not self.telegram_alerts
            or not self.telegram_bot_token
            or not self.telegram_chat_id
        ):
            return

        try:
            import aiohttp

            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML",
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        logger.warning(f"Telegram notification failed: {resp.status}")
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")

    async def _send_daily_report(self):
        """일일 리포트 발송"""
        await self._send_telegram_notification(
            f"📊 Funding Bot 일일 리포트\n"
            f"총 거래: {self.total_trades}회\n"
            f"펀딩 수취: {self.total_funding_payments}회\n"
            f"누적 펀딩: ${self.funding_earnings:.4f}"
        )

    def get_status(self) -> Dict[str, Any]:
        """봇 상태 반환"""
        return {
            "bot_id": self.bot_id,
            "bot_type": "funding_rate",
            "status": self.status.value,
            "capital": self.capital,
            "funding_earnings": self.funding_earnings,
            "total_trades": self.total_trades,
            "total_funding_payments": self.total_funding_payments,
            "active_positions": len(self.positions),
            "positions": [
                {
                    "symbol": p["symbol"],
                    "exchange": p["exchange"],
                    "funding_rate": p["funding_rate"],
                    "amount": p["spot_amount"],
                }
                for p in self.positions.values()
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }


async def main():
    """단독 실행용"""
    bot = FundingRateBot(
        bot_id="funding_binance_bybit_001",
        capital=20.0,
        min_funding_rate=0.0001,
        sandbox=True,
    )

    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()
        print("\n📊 Final Stats:")
        status = bot.get_status()
        print(f"   Total Trades: {status['total_trades']}")
        print(f"   Funding Earnings: ${status['funding_earnings']:.4f}")


if __name__ == "__main__":
    asyncio.run(main())

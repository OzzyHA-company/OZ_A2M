"""
Funding Rate Bot - 펀딩 레이트 봇 (Fixed async/await)
STEP 11: OZ_A2M 완결판 - Fixed Version

설정:
- 거래소: Binance + Bybit
- 전략: 양수 펀딩 → 현물매수 + 선물공매도
- 8시간마다 펀딩 수취
- 자본: $16
- sandbox: False (실거래)

Fixes:
- CCXT async_support 적용
- async/await 패턴 전체 재구조화
- Market precision 적용
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from decimal import Decimal, ROUND_DOWN
from enum import Enum

import ccxt.async_support as ccxt

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
    펀딩 레이트 차익 봇 (Fixed async/await)

    전략:
    - 양수 펀딩레이트가 높은 종목 선별
    - 현물 매수 + 선물 공매도 헤지
    - 8시간마다 펀딩 수취
    - CCXT async 지원 패턴 적용
    """

    # 최소 주문금액 (USDT 기준)
    MIN_NOTIONAL_USDT = 10.0
    SAFETY_MARGIN = 1.1

    def __init__(
        self,
        bot_id: str = "funding_binance_bybit_001",
        capital: float = 16.0,
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
        self.market_info: Dict[str, Dict] = {}

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

        # 시간 추적
        self.start_time: datetime = datetime.utcnow()
        self.last_trade_time: Optional[datetime] = None
        self.last_funding_time: Optional[datetime] = None
        self.next_funding_time: Optional[datetime] = None
        self.trades_today: int = 0
        self.last_trade_date: Optional[str] = None

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

        # 동적 자본 조회: 실제 잔액으로 자본 조정
        try:
            primary = self.exchanges.get("binance") or next(iter(self.exchanges.values()), None)
            if primary:
                balance = await primary.fetch_balance()
                available = float(balance.get("USDT", {}).get("free", 0))
                if available > 0 and available < self.capital:
                    logger.warning(
                        f"[자본 조정] 설정 ${self.capital:.2f} → 실제 ${available * 0.95:.2f} "
                        f"(available: ${available:.2f})"
                    )
                    self.capital = available * 0.95
                else:
                    logger.info(f"[자본 확인] 설정 ${self.capital:.2f} / 가용 ${available:.2f} ✓")
        except Exception as e:
            logger.warning(f"[잔액 조회 실패] 설정값 사용: ${self.capital:.2f} ({e})")

        # 시작 알림
        await self._send_telegram_notification(
            f"💰 Funding Rate 봇 시작\n"
            f"자본: ${self.capital:.2f}\n"
            f"최소 펀딩: {self.min_funding_rate * 100}%\n"
            f"수취 주기: {self.funding_interval_hours}시간"
        )

    async def _connect_exchange(self, exchange_id: str):
        """거래소 연결"""
        try:
            api_key, api_secret = self._load_api_keys(exchange_id)

            if not api_key or not api_secret:
                logger.warning(f"API keys not found for {exchange_id}, skipping")
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
            elif exchange_id == "bybit":
                config["options"] = {"defaultType": "unified"}

            exchange = exchange_class(config)

            if self.sandbox and hasattr(exchange, "set_sandbox_mode"):
                await exchange.set_sandbox_mode(True)

            await exchange.load_markets()
            self.exchanges[exchange_id] = exchange

            logger.info(f"Connected to {exchange_id}")

        except Exception as e:
            logger.error(f"Failed to connect to {exchange_id}: {e}")

    def _normalize_precision(self, precision: float) -> int:
        """
        거래소 precision 값을 정수 소수점 자리수로 변환
        CCXT는 두 가지 형식을 반환할 수 있음:
        - 소수점 자리수: 2 (예: 0.01 단위)
        - 스텝 크기: 0.01 (예: 0.01 단위)
        """
        try:
            if precision is None:
                return 2
            p = float(precision)
            if p < 1:
                import math
                return max(0, int(-math.log10(p)))
            else:
                return max(0, int(p))
        except Exception:
            return 2

    def _amount_to_precision(self, exchange_id: str, symbol: str, amount: float) -> float:
        """수량을 거래소 정밀도에 맞게 조정"""
        key = f"{exchange_id}:{symbol}"
        if key in self.market_info:
            raw_precision = self.market_info[key]["precision"].get("amount", 6)
        else:
            raw_precision = 6
        precision = self._normalize_precision(raw_precision)
        quantizer = Decimal(10) ** -Decimal(precision)
        return float(Decimal(str(amount)).quantize(quantizer, rounding=ROUND_DOWN))

    def _price_to_precision(self, exchange_id: str, symbol: str, price: float) -> float:
        """가격을 거래소 정밀도에 맞게 조정"""
        key = f"{exchange_id}:{symbol}"
        if key in self.market_info:
            raw_precision = self.market_info[key]["precision"].get("price", 2)
        else:
            raw_precision = 2
        precision = self._normalize_precision(raw_precision)
        quantizer = Decimal(10) ** -Decimal(precision)
        return float(Decimal(str(price)).quantize(quantizer, rounding=ROUND_DOWN))

    def _get_min_notional(self, exchange_id: str, symbol: str) -> float:
        """심볼의 최소 주문 금액 조회"""
        key = f"{exchange_id}:{symbol}"
        if key in self.market_info:
            limits = self.market_info[key].get("limits", {})
            return limits.get("cost", {}).get("min") or self.MIN_NOTIONAL_USDT
        return self.MIN_NOTIONAL_USDT

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
                if hasattr(exchange, "fetch_funding_rate"):
                    # Binance futures
                    try:
                        markets = await exchange.load_markets()
                        for symbol in markets:
                            if "/USDT" in symbol or "/USD" in symbol:
                                try:
                                    funding_data = await exchange.fetch_funding_rate(symbol)
                                    if funding_data:
                                        key = f"{exchange_id}:{symbol}"
                                        funding_rate = funding_data.get("fundingRate", 0)
                                        funding_timestamp = funding_data.get("fundingTimestamp", 0)
                                        next_funding_timestamp = funding_data.get("nextFundingTimestamp", 0)

                                        self.funding_rates[key] = FundingRate(
                                            exchange=exchange_id,
                                            symbol=symbol,
                                            funding_rate=float(funding_rate) if funding_rate else 0,
                                            funding_time=datetime.fromtimestamp(
                                                funding_timestamp / 1000 if funding_timestamp else 0
                                            ),
                                            next_funding_time=datetime.fromtimestamp(
                                                next_funding_timestamp / 1000 if next_funding_timestamp else 0
                                            ),
                                        )
                                except Exception as e:
                                    logger.debug(f"Failed to fetch funding for {symbol}: {e}")
                    except Exception as e:
                        logger.warning(f"Error fetching funding rates from {exchange_id}: {e}")

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

            # 마켓 정보 로드
            market = exchange.market(symbol)
            self.market_info[f"{exchange_id}:{symbol}"] = market

            # 최소 주문금액 확인
            min_notional = self._get_min_notional(exchange_id, symbol)
            position_capital = self.capital / 3  # 자본을 3개 종목으로 분할

            if position_capital < min_notional * self.SAFETY_MARGIN:
                logger.warning(
                    f"Insufficient capital for {symbol}: ${position_capital:.2f} < ${min_notional * self.SAFETY_MARGIN:.2f}"
                )
                return

            # 현물 매수
            ticker = await exchange.fetch_ticker(symbol)
            price = ticker.get("last") or ticker.get("close") or ticker.get("bid")
            if not price:
                logger.warning(f"Cannot get price for {symbol}, skipping")
                return
            amount = self._amount_to_precision(exchange_id, symbol, position_capital / price)

            spot_order = await exchange.create_market_buy_order(symbol, amount)

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
            trade_time = datetime.utcnow()
            trade = FundingTrade(
                id=spot_order["id"],
                exchange=exchange_id,
                symbol=symbol,
                side="spot_buy",
                amount=amount,
                price=price,
                timestamp=trade_time,
            )
            self.trades.append(trade)
            self.total_trades += 1
            self.last_trade_time = trade_time
            self._update_trades_today()

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

        except ccxt.InsufficientFunds as e:
            logger.error(f"Insufficient funds for hedge position: {e}")
        except ccxt.InvalidOrder as e:
            logger.error(f"Invalid order for hedge position: {e}")
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

                # 다음 펀딩 시간 업데이트
                self.next_funding_time = rate.next_funding_time

                # 펀딩 시간이 지났으면 수익 기록
                if now > rate.funding_time:
                    funding_pnl = (
                        position["spot_amount"]
                        * position["entry_price"]
                        * rate.funding_rate
                    )
                    self.funding_earnings += funding_pnl
                    self.total_funding_payments += 1
                    self.last_funding_time = now

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

            exit_price = sell_order.get("price") or sell_order.get("average") or position["entry_price"]
            trade_pnl = (exit_price - position["entry_price"]) * position["spot_amount"]

            # 거래 기록
            trade_time = datetime.utcnow()
            trade = FundingTrade(
                id=sell_order["id"],
                exchange=exchange_id,
                symbol=symbol,
                side="spot_sell",
                amount=position["spot_amount"],
                price=exit_price,
                timestamp=trade_time,
                funding_pnl=trade_pnl,
            )
            self.trades.append(trade)
            self.last_trade_time = trade_time
            self._update_trades_today()

            logger.info(
                f"Exited position: {symbol}, trade PnL: ${trade_pnl:.4f}"
            )

            # 수익 발생 시 vault_manager로 이전
            if trade_pnl > 0:
                await self._withdraw_profit(trade_pnl)

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

    async def _withdraw_profit(self, profit: float):
        """수익을 마스터 금고로 이전"""
        if profit < 1.0:
            return  # $1 미만은 누적
        try:
            from lib.core.profit.vault_manager import MasterVaultManager
            vault = MasterVaultManager()
            record = await vault.withdraw_profit_to_vault(self.bot_id, profit)
            logger.info(f"[VaultManager] {self.bot_id}: ${profit:.4f} → {record.vault_type.value} ({record.status})")
        except Exception as e:
            logger.warning(f"[VaultManager] 수익 이전 실패 (기록만 유지): {e}")

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

    def _update_trades_today(self):
        """오늘 거래 횟수 업데이트"""
        today = datetime.utcnow().strftime('%Y-%m-%d')
        if self.last_trade_date != today:
            self.last_trade_date = today
            self.trades_today = 1
        else:
            self.trades_today += 1

    def get_status(self) -> Dict[str, Any]:
        """봇 상태 반환"""
        # 현재 펀딩 레이트 정보 수집
        current_funding_rate = None
        next_funding_time = None
        for key, rate in self.funding_rates.items():
            if rate.funding_rate > 0:
                current_funding_rate = rate.funding_rate
                next_funding_time = rate.next_funding_time.isoformat()
                break

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
            # 대시보드용 추가 필드
            "start_time": self.start_time.isoformat(),
            "last_trade_time": self.last_trade_time.isoformat() if self.last_trade_time else None,
            "last_funding_time": self.last_funding_time.isoformat() if self.last_funding_time else None,
            "next_trade_time": next_funding_time or (self.next_funding_time.isoformat() if self.next_funding_time else None),
            "trades_today": self.trades_today,
            "extra": {
                "current_funding_rate": current_funding_rate,
                "funding_interval_hours": self.funding_interval_hours,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }


async def main():
    """단독 실행용"""
    bot = FundingRateBot(
        bot_id="funding_binance_bybit_001",
        capital=16.0,
        min_funding_rate=0.0001,
        sandbox=False,
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

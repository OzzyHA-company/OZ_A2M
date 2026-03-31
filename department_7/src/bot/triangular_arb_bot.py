"""
Triangular Arbitrage Bot - 삼각 아비트라지 봇 (Fixed async/await)
STEP 11: OZ_A2M 완결판 - Fixed Version

설정:
- 거래소: Binance
- 경로: BTC → ETH → BNB → BTC
- 최소 수익률: 0.1%
- 수수료 자동 계산
- 자본: $10.35
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
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, Tuple
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
from occore.verification.signal_generator import SignalGenerator

logger = get_logger(__name__)


class ArbStatus(str, Enum):
    """아비트라지 봇 상태"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class ArbOpportunity:
    """아비트라지 기회"""
    path: List[str]  # ["BTC", "ETH", "BNB", "BTC"]
    symbols: List[str]  # ["BTC/ETH", "ETH/BNB", "BNB/BTC"]
    profit_pct: float
    amount: float
    timestamp: datetime


@dataclass
class ArbTrade:
    """아비트라지 거래 기록"""
    id: str
    path: str
    profit_pct: float
    profit_amount: float
    timestamp: datetime
    fees: float


class TriangularArbBot:
    """
    삼각 아비트라지 봇 (Fixed async/await)

    전략:
    - 세 개의 거래쌍을 통해 순환 거래
    - BTC → ETH → BNB → BTC
    - 수수료 고려 후 0.1% 이상 수익 시 실행
    - CCXT async 지원 패턴 적용
    """

    # Binance Spot 최소 주문금액 (USDT 기준)
    MIN_NOTIONAL_USDT = 10.0
    SAFETY_MARGIN = 1.1

    def __init__(
        self,
        bot_id: str = "triarb_binance_001",
        exchange_id: str = "binance",
        capital: float = 10.35,
        min_profit_pct: float = 0.001,  # 0.1%
        base_currency: str = "USDT",
        arb_path: List[str] = None,  # ["BTC", "ETH"]
        sandbox: bool = False,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        telegram_alerts: bool = True
    ):
        self.bot_id = bot_id
        self.exchange_id = exchange_id
        self.capital = capital
        self.min_profit_pct = min_profit_pct
        self.base_currency = base_currency
        self.arb_path = arb_path or ["ETH", "BNB"]
        self.sandbox = sandbox
        self.telegram_alerts = telegram_alerts

        # 상태
        self.status = ArbStatus.IDLE
        self.exchange: Optional[ccxt.Exchange] = None
        self.tickers: Dict[str, Dict] = {}
        self.trades: List[ArbTrade] = []
        self.market_info: Dict[str, Dict] = {}

        # 아비트라지 경로 설정
        self.full_path = [base_currency] + self.arb_path + [base_currency]
        self.symbols = self._build_symbols()

        # 유효한 심볼인지 확인
        logger.info(f"Arbitrage symbols: {self.symbols}")

        # 수수료 설정 (Binance 기준)
        self.trading_fee_pct = 0.001  # 0.1%
        self.total_fee_pct = self.trading_fee_pct * 3  # 3번 거래

        # MQTT
        mqtt_config = MQTTConfig(host=mqtt_host, port=mqtt_port, client_id=bot_id)
        self.mqtt = MQTTClient(config=mqtt_config)

        # EventBus
        self.event_bus: Optional[EventBus] = None

        # Signal Generator
        self.signal_generator = SignalGenerator()

        # Telegram
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        # 통계
        self.total_checks: int = 0
        self.opportunities_found: int = 0
        self.executed_trades: int = 0
        self.total_profit: float = 0.0

        # 콜백
        self.on_opportunity: Optional[Callable[[ArbOpportunity], None]] = None
        self.on_trade: Optional[Callable[[ArbTrade], None]] = None

        logger.info(f"TriangularArbBot {bot_id} initialized (path: {' -> '.join(self.full_path)})")

    def _build_symbols(self) -> List[str]:
        """아비트라지 경로의 거래쌍 생성 (Binance 실제 존재 심볼)"""
        symbols = []
        path = self.full_path

        # Binance에서 실제 존재하는 심볼 조합
        # USDT -> BTC -> ETH -> USDT 경로:
        # 1. BTC/USDT (USDT로 BTC 매수)
        # 2. ETH/BTC (BTC로 ETH 매수)
        # 3. ETH/USDT (ETH를 USDT로 매도)
        for i in range(len(path) - 1):
            curr = path[i]
            next_curr = path[i + 1]

            # 일반적인 심볼 조합 시도
            symbol1 = f"{next_curr}/{curr}"  # 예: BTC/USDT
            symbol2 = f"{curr}/{next_curr}"  # 예: USDT/BTC (역방향)

            # Binance에서 일반적으로 사용되는 형식 선택
            # USDT가 quote인 경우가 더 일반적
            if curr == "USDT":
                symbols.append(f"{next_curr}/USDT")
            elif next_curr == "USDT":
                symbols.append(f"{curr}/USDT")
            elif curr == "BTC" and next_curr == "ETH":
                symbols.append("ETH/BTC")  # ETH/BTC 존재
            elif curr == "ETH" and next_curr == "BTC":
                symbols.append("ETH/BTC")
            elif curr == "BTC" and next_curr == "BNB":
                symbols.append("BNB/BTC")
            elif curr == "BNB" and next_curr == "BTC":
                symbols.append("BNB/BTC")
            elif curr == "ETH" and next_curr == "BNB":
                symbols.append("BNB/ETH")
            elif curr == "BNB" and next_curr == "ETH":
                symbols.append("BNB/ETH")
            else:
                # 기본적으로 USDT 마켓 사용
                symbols.append(f"{next_curr}/USDT")

        return symbols

    def _load_api_keys(self) -> tuple:
        """.env에서 API 키 로드"""
        api_key = os.environ.get("BINANCE_API_KEY")
        api_secret = os.environ.get("BINANCE_API_SECRET")
        return api_key, api_secret

    async def initialize(self):
        """봇 초기화"""
        api_key, api_secret = self._load_api_keys()

        if not api_key or not api_secret:
            logger.warning("API keys not found, using mock mode")
            self.status = ArbStatus.ERROR
            return

        # 거래소 설정 (async_support 사용)
        exchange_class = getattr(ccxt, self.exchange_id)
        config = {
            "apiKey": api_key,
            "secret": api_secret,
            "sandbox": self.sandbox,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"}
        }
        self.exchange = exchange_class(config)

        if self.sandbox:
            await self.exchange.set_sandbox_mode(True)

        # 마켓 로드
        await self.exchange.load_markets()

        # 각 심볼의 마켓 정보 저장
        for symbol in self.symbols:
            try:
                self.market_info[symbol] = self.exchange.market(symbol)
            except Exception as e:
                logger.warning(f"Could not load market info for {symbol}: {e}")

        # EventBus 연결
        try:
            self.event_bus = get_event_bus(mqtt_host="localhost", mqtt_port=1883)
            await self.event_bus.connect()
            logger.info("EventBus connected")
        except Exception as e:
            logger.warning(f"EventBus connection failed: {e}")
            self.event_bus = None

        self.status = ArbStatus.RUNNING
        logger.info(f"Triangular Arb bot initialized: {' -> '.join(self.full_path)}")

        # 시작 알림
        await self._send_telegram_notification(
            f"🔺 삼각 아비트라지 봇 시작\n"
            f"경로: {' -> '.join(self.full_path)}\n"
            f"최소 수익: {self.min_profit_pct * 100}%\n"
            f"자본: ${self.capital}"
        )

    def _amount_to_precision(self, symbol: str, amount: float) -> float:
        """수량을 거래소 정밀도에 맞게 조정"""
        if symbol in self.market_info:
            precision = self.market_info[symbol]["precision"].get("amount", 6)
        else:
            precision = 6
        quantizer = Decimal(10) ** -Decimal(precision)
        return float(Decimal(str(amount)).quantize(quantizer, rounding=ROUND_DOWN))

    def _price_to_precision(self, symbol: str, price: float) -> float:
        """가격을 거래소 정밀도에 맞게 조정"""
        if symbol in self.market_info:
            precision = self.market_info[symbol]["precision"].get("price", 2)
        else:
            precision = 2
        quantizer = Decimal(10) ** -Decimal(precision)
        return float(Decimal(str(price)).quantize(quantizer, rounding=ROUND_DOWN))

    def _get_min_notional(self, symbol: str) -> float:
        """심볼의 최소 주문 금액 조회"""
        if symbol in self.market_info:
            limits = self.market_info[symbol].get("limits", {})
            return limits.get("cost", {}).get("min", self.MIN_NOTIONAL_USDT)
        return self.MIN_NOTIONAL_USDT

    async def run(self):
        """메인 루프"""
        try:
            await self.initialize()
        except Exception as e:
            logger.error(f"Arb bot initialization failed: {e}")
            self.status = ArbStatus.ERROR
            raise

        try:
            while self.status == ArbStatus.RUNNING:
                try:
                    # 티커 업데이트
                    await self._update_tickers()

                    # 아비트라지 기회 분석
                    opportunity = self._analyze_arbitrage()

                    if opportunity and opportunity.profit_pct > self.min_profit_pct:
                        logger.info(
                            f"Arbitrage opportunity found: {opportunity.profit_pct:.4%}"
                        )
                        self.opportunities_found += 1

                        # 검증
                        if await self._validate_opportunity(opportunity):
                            await self._execute_arbitrage(opportunity)

                    self.total_checks += 1

                    # 5초마다 체크
                    await asyncio.sleep(5)

                except ccxt.NetworkError as e:
                    logger.error(f"Network error: {e}")
                    await asyncio.sleep(30)
                except Exception as e:
                    logger.error(f"Error in arb loop: {e}")
                    await asyncio.sleep(10)

        except asyncio.CancelledError:
            logger.info("Arb bot cancelled")
            await self.stop()
        except Exception as e:
            logger.error(f"Arb bot error: {e}")
            self.status = ArbStatus.ERROR
            await self.stop()
            raise

    async def _update_tickers(self):
        """티커 업데이트"""
        try:
            for symbol in self.symbols:
                ticker = await self.exchange.fetch_ticker(symbol)
                self.tickers[symbol] = ticker

        except Exception as e:
            logger.error(f"Failed to update tickers: {e}")

    def _analyze_arbitrage(self) -> Optional[ArbOpportunity]:
        """아비트라지 기회 분석"""
        try:
            # 각 단계의 가격 확인
            prices = []
            for symbol in self.symbols:
                if symbol not in self.tickers:
                    return None
                prices.append(self.tickers[symbol]["ask"])  # 매수가

            # 이론적 수익률 계산
            # BTC -> ETH -> BNB -> BTC
            # start: 1 BTC
            # step1: 1 * (ETH/BTC) = X ETH
            # step2: X * (BNB/ETH) = Y BNB
            # step3: Y * (BTC/BNB) = Z BTC
            # profit = (Z - 1) / 1

            amount = 1.0
            for price in prices:
                amount = amount * price

            profit_pct = (amount - 1) / 1

            # 수수료 차감
            net_profit_pct = profit_pct - self.total_fee_pct

            if net_profit_pct > 0:
                return ArbOpportunity(
                    path=self.full_path,
                    symbols=self.symbols,
                    profit_pct=net_profit_pct,
                    amount=self.capital,
                    timestamp=datetime.utcnow()
                )

            return None

        except Exception as e:
            logger.error(f"Error analyzing arbitrage: {e}")
            return None

    async def _validate_opportunity(self, opportunity: ArbOpportunity) -> bool:
        """아비트라지 기회 검증"""
        try:
            # 기본 검증: 수익률이 최소 기준 이상인지
            if opportunity.profit_pct < self.min_profit_pct:
                return False

            # 추가 검증: 시장 데이터 신선도 확인
            for symbol in opportunity.symbols:
                if symbol not in self.tickers:
                    return False
                # 60초 이내 데이터인지 확인
                ticker_timestamp = self.tickers[symbol].get('timestamp', 0)
                if ticker_timestamp:
                    if (datetime.utcnow().timestamp() - ticker_timestamp / 1000) > 60:
                        logger.debug(f"Stale ticker data for {symbol}")
                        return False

            # 최소 주문 금액 검증 (실제 잔액 기준)
            available_usdt = await self._get_available_balance_usdt()
            trade_capital = min(self.capital, available_usdt * 0.95)

            for symbol in opportunity.symbols:
                min_notional = self._get_min_notional(symbol)
                if trade_capital < min_notional * self.SAFETY_MARGIN:
                    logger.warning(f"Available ${trade_capital:.2f} below minimum for {symbol} (need ${min_notional * self.SAFETY_MARGIN:.2f})")
                    return False

            return True

        except Exception as e:
            logger.error(f"Error validating opportunity: {e}")
            return False

    async def _get_available_balance_usdt(self) -> float:
        """사용 가능한 USDT 잔액 조회 (SOL 가치 포함)"""
        try:
            balance = await self.exchange.fetch_balance()
            usdt_free = balance.get('USDT', {}).get('free', 0)
            sol_free = balance.get('SOL', {}).get('free', 0)

            # SOL 가치를 USDT로 환산 (tickers에 없으면 직접 조회)
            sol_value_usdt = 0
            if sol_free > 0:
                sol_price = 0
                if 'SOL/USDT' in self.tickers:
                    sol_price = self.tickers['SOL/USDT'].get('bid', 0)
                else:
                    # 직접 가격 조회
                    try:
                        ticker = await self.exchange.fetch_ticker('SOL/USDT')
                        sol_price = ticker.get('bid', 0)
                    except Exception as e:
                        logger.warning(f"Could not fetch SOL price: {e}")
                        sol_price = 150.0  # fallback price
                sol_value_usdt = sol_free * sol_price

            total_available = usdt_free + sol_value_usdt
            logger.info(f"Available balance: ${total_available:.2f} (USDT: ${usdt_free:.2f}, SOL: ${sol_value_usdt:.2f})")
            return total_available
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return 0

    async def _execute_arbitrage(self, opportunity: ArbOpportunity):
        """아비트라지 실행 (잔액 기반 주문 사이즈 조정)"""
        try:
            # 실제 사용 가능한 잔액 확인
            available_usdt = await self._get_available_balance_usdt()

            # 사용할 자본 결정 (설정 자본 vs 실제 잔액 중 작은 값)
            trade_capital = min(self.capital, available_usdt * 0.95)  # 5% 여유 두고 주문

            if trade_capital < self.MIN_NOTIONAL_USDT * self.SAFETY_MARGIN:
                logger.warning(f"Insufficient balance for arbitrage: ${trade_capital:.2f} (min: ${self.MIN_NOTIONAL_USDT * self.SAFETY_MARGIN:.2f})")
                return

            logger.info(f"Executing arbitrage with capital: ${trade_capital:.2f} (available: ${available_usdt:.2f})")

            # 첫 번째 거래
            symbol1 = self.symbols[0]
            amount1 = self._amount_to_precision(symbol1, trade_capital / self.tickers[symbol1]["ask"])
            order1 = await self.exchange.create_market_buy_order(symbol1, amount1)
            logger.info(f"Step 1: Bought {amount1} {symbol1.split('/')[1]} @ {self.tickers[symbol1]['ask']}")

            # 두 번째 거래
            symbol2 = self.symbols[1]
            amount2 = self._amount_to_precision(symbol2, amount1 / self.tickers[symbol2]["ask"])
            order2 = await self.exchange.create_market_buy_order(symbol2, amount2)
            logger.info(f"Step 2: Bought {amount2} {symbol2.split('/')[1]} @ {self.tickers[symbol2]['ask']}")

            # 세 번째 거래
            symbol3 = self.symbols[2]
            amount3 = self._amount_to_precision(symbol3, amount2 / self.tickers[symbol3]["ask"])
            order3 = await self.exchange.create_market_buy_order(symbol3, amount3)
            logger.info(f"Step 3: Bought {amount3} {symbol3.split('/')[1]} @ {self.tickers[symbol3]['ask']}")

            # 수익 계산
            final_btc = amount3
            initial_btc = trade_capital / self.tickers[symbol1]["ask"]
            profit = final_btc - initial_btc
            profit_pct = profit / initial_btc if initial_btc > 0 else 0

            # 거래 기록
            trade = ArbTrade(
                id=f"arb_{datetime.utcnow().timestamp()}",
                path=" -> ".join(opportunity.path),
                profit_pct=profit_pct,
                profit_amount=profit,
                timestamp=datetime.utcnow(),
                fees=self.total_fee_pct * trade_capital
            )
            self.trades.append(trade)
            self.executed_trades += 1
            self.total_profit += profit

            logger.info(
                f"Arbitrage executed: profit = {profit_pct:.4%} (${profit:.2f})"
            )

            # Telegram 알림
            emoji = "🟢" if profit > 0 else "🔴"
            await self._send_telegram_notification(
                f"{emoji} 아비트라지 실행 완료\n"
                f"경로: {' -> '.join(opportunity.path)}\n"
                f"예상 수익: {opportunity.profit_pct:.4%}\n"
                f"실제 수익: {profit_pct:.4%}\n"
                f"수익금: ${profit:.2f}"
            )

            if self.on_trade:
                self.on_trade(trade)

        except ccxt.InsufficientFunds as e:
            logger.error(f"Insufficient funds for arbitrage: {e}")
        except ccxt.InvalidOrder as e:
            logger.error(f"Invalid order in arbitrage: {e}")
        except Exception as e:
            logger.error(f"Failed to execute arbitrage: {e}")

    async def stop(self):
        """봇 중지"""
        self.status = ArbStatus.IDLE

        # 거래소 연결 해제
        if self.exchange:
            await self.exchange.close()

        # EventBus 연결 해제
        if self.event_bus:
            await self.event_bus.disconnect()

        await self.mqtt.disconnect()

        # 일일 리포트
        await self._send_daily_report()

        logger.info(f"Triangular Arb bot {self.bot_id} stopped")

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
        await self._send_telegram_notification(
            f"📊 Triangular Arb Bot 일일 리포트\n"
            f"체크 횟수: {self.total_checks}회\n"
            f"기회 발견: {self.opportunities_found}회\n"
            f"실행 거래: {self.executed_trades}회\n"
            f"총 수익: ${self.total_profit:.2f}"
        )

    def get_status(self) -> Dict[str, Any]:
        """봇 상태 반환"""
        return {
            "bot_id": self.bot_id,
            "bot_type": "triangular_arb",
            "exchange": self.exchange_id,
            "status": self.status.value,
            "capital": self.capital,
            "path": " -> ".join(self.full_path),
            "min_profit_pct": self.min_profit_pct,
            "total_checks": self.total_checks,
            "opportunities_found": self.opportunities_found,
            "executed_trades": self.executed_trades,
            "total_profit": self.total_profit,
            "timestamp": datetime.utcnow().isoformat()
        }


async def main():
    """단독 실행용"""
    bot = TriangularArbBot(
        bot_id="triarb_binance_001",
        capital=10.35,
        min_profit_pct=0.001,
        sandbox=False
    )

    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()
        print("\n📊 Final Stats:")
        status = bot.get_status()
        print(f"   Total Checks: {status['total_checks']}")
        print(f"   Opportunities: {status['opportunities_found']}")
        print(f"   Executed: {status['executed_trades']}")
        print(f"   Total Profit: ${status['total_profit']:.2f}")


if __name__ == "__main__":
    asyncio.run(main())

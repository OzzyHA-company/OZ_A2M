"""
Triangular Arbitrage Bot - 삼각 아비트라지 봇
STEP 11: OZ_A2M 완결판

설정:
- 거래소: Binance
- 경로: BTC → ETH → BNB → BTC
- 최소 수익률: 0.1%
- 수수료 자동 계산
- 자본: $20
- sandbox: False (실거래)
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, Tuple
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
    삼각 아비트라지 봇

    전략:
    - 세 개의 거래쌍을 통해 순환 거래
    - BTC → ETH → BNB → BTC
    - 수수료 고려 후 0.1% 이상 수익 시 실행
    """

    def __init__(
        self,
        bot_id: str = "triarb_binance_001",
        exchange_id: str = "binance",
        capital: float = 20.0,
        min_profit_pct: float = 0.001,  # 0.1%
        base_currency: str = "BTC",
        arb_path: List[str] = None,  # ["ETH", "BNB"]
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

        # 아비트라지 경로 설정
        self.full_path = [base_currency] + self.arb_path + [base_currency]
        self.symbols = self._build_symbols()

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
        """아비트라지 경로의 거래쌍 생성"""
        symbols = []
        for i in range(len(self.full_path) - 1):
            base = self.full_path[i]
            quote = self.full_path[i + 1]
            # Binance 형식: BTC/ETH, ETH/BNB 등
            symbols.append(f"{base}/{quote}")
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

        # 거래소 설정
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
            self.exchange.set_sandbox_mode(True)

        # 마켓 로드
        await self.exchange.load_markets()

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
            # Signal Generator를 통한 검증
            signal = await self.signal_generator.generate_signal({
                "type": "triangular_arbitrage",
                "path": opportunity.path,
                "profit_pct": opportunity.profit_pct,
                "symbols": opportunity.symbols
            })

            if signal and signal.get("valid", False):
                return True

            logger.debug(f"Opportunity validation failed: {opportunity}")
            return False

        except Exception as e:
            logger.error(f"Error validating opportunity: {e}")
            return False

    async def _execute_arbitrage(self, opportunity: ArbOpportunity):
        """아비트라지 실행"""
        try:
            # 첫 번째 거래: BTC -> ETH
            amount1 = self.capital / self.tickers[self.symbols[0]]["ask"]
            order1 = await self.exchange.create_market_buy_order(
                self.symbols[0], amount1
            )

            # 두 번째 거래: ETH -> BNB
            amount2 = amount1 / self.tickers[self.symbols[1]]["ask"]
            order2 = await self.exchange.create_market_buy_order(
                self.symbols[1], amount2
            )

            # 세 번째 거래: BNB -> BTC
            amount3 = amount2 / self.tickers[self.symbols[2]]["ask"]
            order3 = await self.exchange.create_market_buy_order(
                self.symbols[2], amount3
            )

            # 수익 계산
            final_btc = amount3
            profit = final_btc - (self.capital / self.tickers[self.symbols[0]]["ask"])
            profit_pct = profit / (self.capital / self.tickers[self.symbols[0]]["ask"])

            # 거래 기록
            trade = ArbTrade(
                id=f"arb_{datetime.utcnow().timestamp()}",
                path=" -> ".join(opportunity.path),
                profit_pct=profit_pct,
                profit_amount=profit,
                timestamp=datetime.utcnow(),
                fees=self.total_fee_pct * self.capital
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
        capital=20.0,
        min_profit_pct=0.001,
        sandbox=True
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

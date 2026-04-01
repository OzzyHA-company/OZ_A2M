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
    # ETH/USDT, BNB/USDT 등은 $5 미만도 거래 가능
    MIN_NOTIONAL_USDT = 5.0
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

        # 시간 추적
        self.start_time: datetime = datetime.utcnow()
        self.last_trade_time: Optional[datetime] = None
        self.last_check_time: Optional[datetime] = None
        self.trades_today: int = 0
        self.last_trade_date: Optional[str] = None

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

    def _amount_to_precision(self, symbol: str, amount: float) -> float:
        """수량을 거래소 정밀도에 맞게 조정"""
        if symbol in self.market_info:
            raw_precision = self.market_info[symbol]["precision"].get("amount", 6)
        else:
            raw_precision = 6
        precision = self._normalize_precision(raw_precision)
        quantizer = Decimal(10) ** -Decimal(precision)
        return float(Decimal(str(amount)).quantize(quantizer, rounding=ROUND_DOWN))

    def _price_to_precision(self, symbol: str, price: float) -> float:
        """가격을 거래소 정밀도에 맞게 조정"""
        if symbol in self.market_info:
            raw_precision = self.market_info[symbol]["precision"].get("price", 2)
        else:
            raw_precision = 2
        precision = self._normalize_precision(raw_precision)
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
                    self.last_check_time = datetime.utcnow()
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
        """아비트라지 기회 분석 (정확한 수익률 계산)"""
        try:
            # 각 단계의 티커 확인
            if not all(s in self.tickers for s in self.symbols):
                return None

            # USDT 기준 삼각아비트라지 경로:
            # USDT -> BTC (buy BTC/USDT @ ask)
            # BTC -> ETH (buy ETH/BTC @ ask - BTC로 ETH 매수)
            # ETH -> USDT (sell ETH/USDT @ bid - ETH를 USDT로 매도)
            #
            # 또는
            # USDT -> BTC @ ask1
            # BTC -> ETH @ ask2 (ETH/BTC)
            # ETH -> USDT @ bid3 (ETH/USDT)

            symbol1, symbol2, symbol3 = self.symbols[0], self.symbols[1], self.symbols[2]

            # 가격 추출
            try:
                # 1단계: USDT -> 첫 번째 코인 (매수 @ ask)
                if "/USDT" in symbol1:
                    # BTC/USDT: USDT로 BTC 삼
                    price1 = self.tickers[symbol1]["ask"]  # BTC 1개 가격 in USDT
                    start_usdt = 100  # 가정: 100 USDT 시작
                    coin1_amount = start_usdt / price1  # 산 BTC 수량
                else:
                    return None

                # 2단계: 첫 번째 코인 -> 두 번째 코인
                if "/BTC" in symbol2:
                    # ETH/BTC: BTC로 ETH 삼
                    price2 = self.tickers[symbol2]["ask"]  # ETH 1개 가격 in BTC
                    coin2_amount = coin1_amount / price2  # 산 ETH 수량
                elif "/ETH" in symbol2:
                    price2 = self.tickers[symbol2]["ask"]
                    coin2_amount = coin1_amount / price2
                else:
                    return None

                # 3단계: 두 번째 코인 -> USDT (매도 @ bid)
                if "/USDT" in symbol3:
                    # ETH/USDT: ETH를 USDT로 팜
                    price3 = self.tickers[symbol3]["bid"]  # ETH 1개 가격 in USDT
                    final_usdt = coin2_amount * price3
                else:
                    return None

                # 수익률 계산
                profit = final_usdt - start_usdt
                profit_pct = profit / start_usdt

            except (KeyError, ZeroDivisionError) as e:
                logger.debug(f"Price calculation error: {e}")
                return None

            # 수수료 차감 (3번 거래)
            net_profit_pct = profit_pct - self.total_fee_pct

            # 디버그 로깅 (과도한 수익률 경고)
            if net_profit_pct > 0.1:  # 10% 이상은 의심
                logger.warning(f"Suspicious arbitrage profit detected: {net_profit_pct:.2%}. Skipping.")
                return None

            if net_profit_pct > self.min_profit_pct:
                logger.info(f"Valid arbitrage opportunity: {net_profit_pct:.4%} (gross: {profit_pct:.4%})")
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

    async def _withdraw_profit(self, profit_usdt: float, trade_id: str):
        """수익금 즉시 출금

        원금은 그대로 유지, 수익분만 출금
        출금처: Binance -> MetaMask (Polygon) USDC
        """
        if profit_usdt <= 0:
            return

        try:
            # 출금 정보 설정
            withdraw_address = os.environ.get("METAMASK_PROFIT_WALLET", "0x567C027e81469225A070656ebca7227C1F6cf95d")
            withdraw_network = "MATIC"  # Polygon 메인넷

            logger.info(f"Initiating profit withdrawal: ${profit_usdt:.2f} USDT to {withdraw_address}")

            # Binance 출금 실행 (USDT -> Polygon USDC)
            try:
                withdraw_result = await self.exchange.withdraw(
                    code="USDT",
                    amount=profit_usdt,
                    address=withdraw_address,
                    tag=None,
                    params={
                        "network": withdraw_network,
                        "addressTag": None
                    }
                )

                withdraw_id = withdraw_result.get('id', 'N/A')
                logger.info(f"Profit withdrawal submitted: ID={withdraw_id}, Amount=${profit_usdt:.2f}")

                # 출금 성공 알림
                await self._send_telegram_notification(
                    f"💰 수익 즉시 출금 완료\n"
                    f"거래 ID: {trade_id}\n"
                    f"출금액: ${profit_usdt:.2f} USDT\n"
                    f"출금처: MetaMask (Polygon)\n"
                    f"주소: {withdraw_address[:10]}...{withdraw_address[-6:]}\n"
                    f"출금 ID: {withdraw_id}\n"
                    f"원금 유지: ${self.capital:.2f}"
                )

                # EventBus로 대시보드에 출금 이벤트 발행
                if self.event_bus:
                    await self.event_bus.publish("profit_withdrawal", {
                        "bot_id": self.bot_id,
                        "trade_id": trade_id,
                        "amount": profit_usdt,
                        "currency": "USDT",
                        "to_address": withdraw_address,
                        "network": "Polygon",
                        "withdraw_id": withdraw_id,
                        "timestamp": datetime.utcnow().isoformat(),
                        "type": "immediate_profit_withdrawal"
                    })

                return True

            except ccxt.NotSupported as e:
                # 출금 API가 지원되지 않는 경우 (테스트넷 등)
                logger.warning(f"Withdrawal not supported (testnet?): {e}")
                await self._send_telegram_notification(
                    f"⚠️ 수익 출금 대기 (API 제한)\n"
                    f"거래 ID: {trade_id}\n"
                    f"출금 예정액: ${profit_usdt:.2f} USDT\n"
                    f"출금처: MetaMask (Polygon)\n"
                    f"수동 출금 필요"
                )
                return False

        except Exception as e:
            logger.error(f"Profit withdrawal failed: {e}")
            await self._send_telegram_notification(
                f"🔴 수익 출금 실패\n"
                f"거래 ID: {trade_id}\n"
                f"출금 시도액: ${profit_usdt:.2f}\n"
                f"오류: {str(e)[:100]}"
            )
            return False

    async def _execute_arbitrage(self, opportunity: ArbOpportunity):
        """아비트라지 실행 (잔액 기반 주문 사이즈 자동 조정 + 수익 즉시 출금)"""
        try:
            # 실제 사용 가능한 USDT 잔액만 확인 (SOL은 삼각아비트라지에 사용 불가)
            balance = await self.exchange.fetch_balance()
            usdt_free = balance.get('USDT', {}).get('free', 0)
            sol_free = balance.get('SOL', {}).get('free', 0)

            # SOL 가치도 로깅용으로 계산
            sol_value_usdt = 0
            if sol_free > 0:
                try:
                    ticker = await self.exchange.fetch_ticker('SOL/USDT')
                    sol_price = ticker.get('bid', 150.0)
                    sol_value_usdt = sol_free * sol_price
                except:
                    sol_value_usdt = sol_free * 150.0

            total_value = usdt_free + sol_value_usdt
            logger.info(f"Balance check: USDT=${usdt_free:.2f}, SOL=${sol_value_usdt:.2f} (total=${total_value:.2f})")

            # 사용할 자본 결정 (USDT만 사용 가능, 설정 자본과 실제 잔액 중 작은 값)
            max_trade_capital = min(self.capital, usdt_free * 0.95)  # 5% 여유 두고 주문

            # 최소 주문 금액 검증
            if max_trade_capital < self.MIN_NOTIONAL_USDT * self.SAFETY_MARGIN:
                logger.warning(f"Insufficient USDT for arbitrage: ${max_trade_capital:.2f} (min: ${self.MIN_NOTIONAL_USDT * self.SAFETY_MARGIN:.2f})")
                return

            # 실제 사용할 자본 (원금 한도 내에서)
            trade_capital = min(max_trade_capital, self.capital)
            logger.info(f"Executing arbitrage with capital: ${trade_capital:.2f} (USDT available: ${usdt_free:.2f}, Max allowed: ${self.capital:.2f})")

            # 첫 번째 거래
            symbol1 = self.symbols[0]
            amount1 = self._amount_to_precision(symbol1, trade_capital / self.tickers[symbol1]["ask"])
            order1 = await self.exchange.create_market_buy_order(symbol1, amount1)
            logger.info(f"Step 1: Bought {amount1} {symbol1.split('/')[0]} @ {self.tickers[symbol1]['ask']}")

            # 두 번째 거래
            symbol2 = self.symbols[1]
            amount2 = self._amount_to_precision(symbol2, amount1 / self.tickers[symbol2]["ask"])
            order2 = await self.exchange.create_market_buy_order(symbol2, amount2)
            logger.info(f"Step 2: Bought {amount2} {symbol2.split('/')[0]} @ {self.tickers[symbol2]['ask']}")

            # 세 번째 거래
            symbol3 = self.symbols[2]
            amount3 = self._amount_to_precision(symbol3, amount2 / self.tickers[symbol3]["ask"])
            order3 = await self.exchange.create_market_buy_order(symbol3, amount3)
            logger.info(f"Step 3: Bought {amount3} {symbol3.split('/')[0]} @ {self.tickers[symbol3]['ask']}")

            # 수익 계산 (USDT 기준)
            final_usdt_value = amount3 * self.tickers[symbol3]["bid"]
            profit = final_usdt_value - trade_capital
            profit_pct = profit / trade_capital if trade_capital > 0 else 0

            # 거래 기록
            trade_time = datetime.utcnow()
            trade_id = f"arb_{trade_time.timestamp()}"
            trade = ArbTrade(
                id=trade_id,
                path=" -> ".join(opportunity.path),
                profit_pct=profit_pct,
                profit_amount=profit,
                timestamp=trade_time,
                fees=self.total_fee_pct * trade_capital
            )
            self.trades.append(trade)
            self.executed_trades += 1
            self.total_profit += profit
            self.last_trade_time = trade_time
            self._update_trades_today()

            logger.info(
                f"Arbitrage executed: profit = {profit_pct:.4%} (${profit:.2f})"
            )

            # Telegram 알림
            emoji = "🟢" if profit > 0 else "🔴"
            await self._send_telegram_notification(
                f"{emoji} 아비트라지 실행 완료\n"
                f"경로: {' -> '.join(opportunity.path)}\n"
                f"투입 자본: ${trade_capital:.2f}\n"
                f"최종 가치: ${final_usdt_value:.2f}\n"
                f"수익률: {profit_pct:.4%}\n"
                f"수익금: ${profit:.2f}"
            )

            # 수익 즉시 출금 (원금 유지, 수익분만 출금)
            if profit > 0:
                logger.info(f"Initiating immediate profit withdrawal: ${profit:.2f}")
                await self._withdraw_profit(profit, trade_id)

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
            # 대시보드용 추가 필드
            "start_time": self.start_time.isoformat(),
            "last_trade_time": self.last_trade_time.isoformat() if self.last_trade_time else None,
            "last_check_time": self.last_check_time.isoformat() if self.last_check_time else None,
            "next_trade_time": None,  # 아비트라지는 기회 발견 기반
            "trades_today": self.trades_today,
            "extra": {
                "symbols": self.symbols,
                "total_fee_pct": self.total_fee_pct,
            },
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

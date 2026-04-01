"""
Hyperliquid Market Maker Bot - 하이퍼리퀴드 마켓메이커 봇
STEP 12: OZ_A2M 완결판

설정:
- 거래소: Hyperliquid
- 마켓메이커 전략 (기존 market_maker_bot.py 기반)
- 자본: $10.12
- 레버리지: 5배
- 도파민봇 (고위험/고수익)
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

logger = get_logger(__name__)

# Hyperliquid SDK import (optional)
try:
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
    HYPERLIQUID_AVAILABLE = True
except ImportError:
    HYPERLIQUID_AVAILABLE = False
    logger.warning("hyperliquid-python-sdk not installed, using mock mode")


class HyperliquidStatus(str, Enum):
    """Hyperliquid 봇 상태"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    MOCK = "mock"  # Mock 모드


@dataclass
class HLPosition:
    """Hyperliquid 포지션"""
    symbol: str
    side: str
    size: float
    entry_price: float
    unrealized_pnl: float


@dataclass
class HLTrade:
    """Hyperliquid 거래 기록"""
    id: str
    symbol: str
    side: str
    size: float
    price: float
    timestamp: datetime
    pnl: Optional[float] = None


class HyperliquidMarketMakerBot:
    """
    Hyperliquid 마켓메이커 봇

    전략:
    - 오더북 기반 양방향 호가 제시
    - 스프레드 조정
    - 인벤토리 헤지
    """

    def __init__(
        self,
        bot_id: str = "hyperliquid_mm_001",
        symbol: str = "SOL-PERP",
        capital: float = 10.12,
        base_spread_bps: float = 10.0,  # 0.1%
        inventory_target: float = 0.5,  # 목표 인벤토리 비율
        sandbox: bool = False,
        mock_mode: bool = False,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        telegram_alerts: bool = True
    ):
        self.bot_id = bot_id
        self.symbol = symbol
        self.capital = capital
        self.base_spread_bps = base_spread_bps
        self.inventory_target = inventory_target
        self.sandbox = sandbox
        self.mock_mode = mock_mode
        self.telegram_alerts = telegram_alerts

        # 상태
        self.status = HyperliquidStatus.IDLE
        self.exchange: Optional[Any] = None
        self.info: Optional[Any] = None
        self.wallet_address: Optional[str] = None

        # 주문 및 포지션
        self.open_orders: Dict[str, Any] = {}
        self.position: Optional[HLPosition] = None
        self.trades: List[HLTrade] = []
        self.inventory_ratio: float = 0.5

        # MQTT
        mqtt_config = MQTTConfig(host=mqtt_host, port=mqtt_port, client_id=bot_id)
        self.mqtt = MQTTClient(config=mqtt_config)

        # EventBus
        self.event_bus: Optional[EventBus] = None

        # Telegram
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        # 출금 설정 (수익 즉시 출금)
        self.metamask_address = os.environ.get("METAMASK_PROFIT_WALLET") or os.environ.get("METAMASK_ADDRESS")

        # 통계
        self.total_trades: int = 0
        self.maker_volume: float = 0.0
        self.total_pnl: float = 0.0

        # Mock 데이터 (테스트용)
        if self.mock_mode:
            self._mock_price = 150.0
            self._mock_balance = {"USDC": self.capital, "SOL": 0.0}

        # 콜백
        self.on_trade: Optional[Callable[[HLTrade], None]] = None
        self.on_position_change: Optional[Callable[[Optional[HLPosition]], None]] = None

        logger.info(f"HyperliquidMarketMakerBot {bot_id} initialized (capital=${capital})")

    def _load_wallet(self) -> Optional[str]:
        """.env에서 Phantom 지갑 주소 로드"""
        return os.environ.get("PHANTOM_WALLET_A")

    async def initialize(self):
        """봇 초기화"""
        if not HYPERLIQUID_AVAILABLE:
            logger.warning("Hyperliquid SDK not available, using mock mode")
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
        """실제 거래소 연결 초기화"""
        try:
            self.wallet_address = self._load_wallet()

            if not self.wallet_address:
                logger.warning("Wallet address not found, switching to mock mode")
                await self._initialize_mock()
                return

            # Info API 연결 (읽기 전용)
            self.info = Info()

            # Exchange API 연결 (거래용) - 프라이빗 키 로드
            private_key = os.environ.get("METAMASK_PRIVATE_KEY")
            if private_key and HYPERLIQUID_AVAILABLE:
                try:
                    from eth_account import Account
                    eth_wallet = Account.from_key(private_key)
                    self.exchange = Exchange(wallet=eth_wallet, base_url=None)
                    logger.info(f"Hyperliquid Exchange connected (wallet: {self.wallet_address[:10]}...)")
                except Exception as e:
                    logger.warning(f"Exchange init failed: {e}, running info-only mode")
                    self.exchange = None
            else:
                logger.warning("METAMASK_PRIVATE_KEY not set, running info-only mode")
                self.exchange = None

            logger.info("Hyperliquid live mode initialized")
            self.status = HyperliquidStatus.RUNNING

        except Exception as e:
            logger.error(f"Failed to initialize Hyperliquid live mode: {e}")
            logger.info("Falling back to mock mode")
            await self._initialize_mock()

    async def _initialize_mock(self):
        """Mock 모드 초기화"""
        self.mock_mode = True
        self.status = HyperliquidStatus.MOCK
        self.wallet_address = "0xMockWallet123"

        # Mock 데이터 초기화
        self._mock_price = 150.0
        self._mock_balance = {"USDC": self.capital, "SOL": 0.0}

        logger.info("Hyperliquid mock mode initialized")

        # 시작 알림
        await self._send_telegram_notification(
            f"⚡ Hyperliquid MM 봇 시작 (Mock)\n"
            f"심볼: {self.symbol}\n"
            f"자본: ${self.capital}\n"
            f"스프레드: {self.base_spread_bps} bps"
        )

    async def run(self):
        """메인 루프"""
        try:
            await self.initialize()
        except Exception as e:
            logger.error(f"Hyperliquid bot initialization failed: {e}")
            self.status = HyperliquidStatus.ERROR
            raise

        try:
            while self.status in [HyperliquidStatus.RUNNING, HyperliquidStatus.MOCK]:
                try:
                    if self.mock_mode:
                        await self._run_mock_loop()
                    else:
                        await self._run_live_loop()

                    await asyncio.sleep(5)

                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    await asyncio.sleep(10)

        except asyncio.CancelledError:
            logger.info("Hyperliquid bot cancelled")
            await self.stop()
        except Exception as e:
            logger.error(f"Hyperliquid bot error: {e}")
            self.status = HyperliquidStatus.ERROR
            await self.stop()
            raise

    async def _run_live_loop(self):
        """실제 거래소 루프 - 마켓메이커 주문 관리 (30초 주기)"""
        coin = self.symbol.replace("-PERP", "")
        try:
            if self.info and self.wallet_address:
                # 계좌 상태 조회
                user_state = self.info.user_state(self.wallet_address)
                margin_summary = user_state.get("marginSummary", {})
                account_value = float(margin_summary.get("accountValue", 0))
                if account_value > 0:
                    self._live_balance = account_value
                    logger.debug(f"Hyperliquid account value: ${account_value:.2f}")

            # 기존 open_orders 취소
            if self.exchange and self.open_orders:
                try:
                    cancels = [{"coin": coin, "oid": int(oid)} for oid in list(self.open_orders.keys())]
                    self.exchange.bulk_cancel(cancels)
                    self.open_orders.clear()
                    logger.debug(f"Cancelled {len(cancels)} existing orders")
                except Exception as e:
                    logger.debug(f"Cancel orders error: {e}")
                    self.open_orders.clear()

            # L2 스냅샷으로 중간 가격 조회
            if self.info and self.exchange:
                try:
                    l2 = self.info.l2_snapshot(coin)
                    bid_levels = l2.get("levels", [[], []])[0]
                    ask_levels = l2.get("levels", [[], []])[1]

                    if not bid_levels or not ask_levels:
                        logger.debug("Empty L2 snapshot, skipping order placement")
                        await asyncio.sleep(30)
                        return

                    best_bid = float(bid_levels[0]["px"])
                    best_ask = float(ask_levels[0]["px"])
                    mid = (best_bid + best_ask) / 2

                    # 스프레드 적용 (base_spread_bps의 절반씩 양쪽)
                    half_spread = mid * (self.base_spread_bps / 20000)
                    bid_px = round(mid - half_spread, 1)
                    ask_px = round(mid + half_spread, 1)

                    # 주문 크기: 자본의 10% (최소 0.001 SOL)
                    sz = round(self.capital * 0.1 / mid, 3)
                    if sz < 0.001:
                        logger.warning(f"Order size too small: {sz} SOL, skipping")
                        await asyncio.sleep(30)
                        return

                    # 매수 호가 (Add-Liquidity-Only = maker 수수료)
                    bid_result = self.exchange.order(coin, True, sz, bid_px, {"limit": {"tif": "Alo"}})
                    if bid_result.get("status") == "ok":
                        statuses = bid_result.get("response", {}).get("data", {}).get("statuses", [])
                        if statuses and "resting" in statuses[0]:
                            oid = str(statuses[0]["resting"]["oid"])
                            self.open_orders[oid] = "bid"

                    # 매도 호가
                    ask_result = self.exchange.order(coin, False, sz, ask_px, {"limit": {"tif": "Alo"}})
                    if ask_result.get("status") == "ok":
                        statuses = ask_result.get("response", {}).get("data", {}).get("statuses", [])
                        if statuses and "resting" in statuses[0]:
                            oid = str(statuses[0]["resting"]["oid"])
                            self.open_orders[oid] = "ask"

                    self.total_trades += 1
                    logger.info(f"MM orders: bid={bid_px} ask={ask_px} sz={sz} SOL (mid={mid:.2f})")

                except Exception as e:
                    logger.error(f"Order placement error: {e}")

        except Exception as e:
            logger.debug(f"Hyperliquid live loop error: {e}")

        await asyncio.sleep(30)

    async def _run_mock_loop(self):
        """Mock 모드 루프"""
        # 가격 변동 시뮬레이션
        import random
        self._mock_price *= (1 + random.uniform(-0.001, 0.001))

        # 랜덤 거래 시뮬레이션
        if random.random() < 0.1:  # 10% 확률로 거래 발생
            trade_pnl = random.uniform(-0.1, 0.5)
            trade = HLTrade(
                id=f"mock_{datetime.utcnow().timestamp()}",
                symbol=self.symbol,
                side="buy" if random.random() > 0.5 else "sell",
                size=random.uniform(0.01, 0.1),
                price=self._mock_price,
                timestamp=datetime.utcnow(),
                pnl=trade_pnl
            )
            self.trades.append(trade)
            self.total_trades += 1
            self.total_pnl += trade_pnl

            # 🎯 수익 즉시 출금 (도파민 봇 핵심 기능)
            if trade_pnl > 0:
                try:
                    withdraw_result = await self._withdraw_profits_usdc(trade_pnl)
                    if withdraw_result:
                        logger.info(f"Profit withdrawn: {trade_pnl:.2f} USDC")
                        await self._send_telegram_notification(
                            f"💰 Hyperliquid 수익 출금 완료\n"
                            f"금액: ${trade_pnl:.2f} USDC\n"
                            f"잭팟 즉시 확보! 🎯"
                        )
                    else:
                        logger.warning(f"Profit withdrawal failed for {trade_pnl:.2f} USDC")
                except Exception as e:
                    logger.error(f"Profit withdrawal error: {e}")

            if self.on_trade:
                self.on_trade(trade)

    async def stop(self):
        """봇 중지"""
        self.status = HyperliquidStatus.IDLE

        # 모든 주문 취소
        if not self.mock_mode and self.exchange:
            try:
                # TODO: 주문 취소 로직
                pass
            except Exception as e:
                logger.error(f"Error cancelling orders: {e}")

        # EventBus 연결 해제
        if self.event_bus:
            await self.event_bus.disconnect()

        await self.mqtt.disconnect()

        # 일일 리포트
        await self._send_daily_report()

        logger.info(f"Hyperliquid MM bot {self.bot_id} stopped")

    async def _withdraw_profits_usdc(self, amount_usdc: float) -> bool:
        """수익분 즉시 출금 (MetaMask 지갑으로) - 도파민봇 핵심 기능"""
        try:
            withdraw_address = self.metamask_address

            if not withdraw_address:
                logger.warning("No withdrawal address configured (set METAMASK_PROFIT_WALLET)")
                return False

            if self.mock_mode:
                logger.info(f"[MOCK] Would withdraw {amount_usdc:.2f} USDC to {withdraw_address}")
                return True

            # TODO: 실제 Hyperliquid 출금 로직 구현
            logger.info(f"Initiating withdrawal: {amount_usdc:.2f} USDC to {withdraw_address}")
            return True

        except Exception as e:
            logger.error(f"Withdrawal failed: {e}")
            return False

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
            f"📊 Hyperliquid MM Bot 일일 리포트\n"
            f"모드: {'Mock' if self.mock_mode else 'Live'}\n"
            f"총 거래: {self.total_trades}회\n"
            f"총 PnL: ${self.total_pnl:.2f}"
        )

    def get_status(self) -> Dict[str, Any]:
        """봇 상태 반환"""
        return {
            "bot_id": self.bot_id,
            "bot_type": "hyperliquid_mm",
            "status": self.status.value,
            "symbol": self.symbol,
            "capital": self.capital,
            "mock_mode": self.mock_mode,
            "wallet": self.wallet_address[:10] + "..." if self.wallet_address else None,
            "total_trades": self.total_trades,
            "total_pnl": self.total_pnl,
            "timestamp": datetime.utcnow().isoformat()
        }


async def main():
    """단독 실행용"""
    bot = HyperliquidMarketMakerBot(
        bot_id="hyperliquid_mm_001",
        symbol="SOL-PERP",
        capital=10.12,
        mock_mode=False  # 실거래 모드
    )

    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()
        print("\n📊 Final Stats:")
        status = bot.get_status()
        print(f"   Total Trades: {status['total_trades']}")
        print(f"   Total PnL: ${status['total_pnl']:.2f}")


if __name__ == "__main__":
    asyncio.run(main())

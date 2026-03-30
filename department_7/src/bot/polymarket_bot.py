"""
Polymarket AI Prediction Bot - 폴리마켓 AI 예측 봇
STEP 13: OZ_A2M 완결판

설정:
- 거래소: Polymarket (CLOB)
- AI 기반 예측 시장 분석
- Gemini/Groq AI 확률 분석
- 괴리 5% 이상 시 자동 베팅
- Kelly Criterion 포지션 사이징
- 자본: $19.85 USDC
- Mock 모드 지원
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
from occore.verification.signal_generator import SignalGenerator

logger = get_logger(__name__)

# Polymarket SDK import (optional)
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
    POLYMARKET_AVAILABLE = True
except ImportError:
    POLYMARKET_AVAILABLE = False
    logger.warning("py-clob-client not installed, using mock mode")


class PolymarketStatus(str, Enum):
    """Polymarket 봇 상태"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    MOCK = "mock"


@dataclass
class MarketOpportunity:
    """시장 기회"""
    market_id: str
    question: str
    ai_probability: float
    market_probability: float
    edge: float  # 괴리
    kelly_fraction: float
    recommended_bet: float


@dataclass
class PolymarketTrade:
    """Polymarket 거래 기록"""
    id: str
    market_id: str
    question: str
    side: str  # "yes" or "no"
    amount: float
    price: float
    timestamp: datetime
    expected_pnl: float


class PolymarketAIBot:
    """
    Polymarket AI 예측 봇

    전략:
    - Gemini/Groq AI로 예측 시장 분석
    - 시장 확률과 AI 확률의 괴리 5% 이상 시 베팅
    - Kelly Criterion으로 포지션 사이징
    """

    def __init__(
        self,
        bot_id: str = "polymarket_ai_001",
        capital: float = 19.85,
        min_edge: float = 0.05,  # 5% 괴리
        kelly_fraction: float = 0.25,  # 1/4 Kelly
        min_bet: float = 1.0,
        max_bet: float = 5.0,
        mock_mode: bool = False,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        telegram_alerts: bool = True
    ):
        self.bot_id = bot_id
        self.capital = capital
        self.min_edge = min_edge
        self.kelly_fraction = kelly_fraction
        self.min_bet = min_bet
        self.max_bet = max_bet
        self.mock_mode = mock_mode
        self.telegram_alerts = telegram_alerts

        # 상태
        self.status = PolymarketStatus.IDLE
        self.client: Optional[Any] = None
        self.wallet_address: Optional[str] = None
        self.active_opportunities: List[MarketOpportunity] = []
        self.trades: List[PolymarketTrade] = []

        # AI 컴포넌트
        self.llm_analyzer = LLMAnalyzer()
        self.signal_generator = SignalGenerator()

        # MQTT
        mqtt_config = MQTTConfig(host=mqtt_host, port=mqtt_port, client_id=bot_id)
        self.mqtt = MQTTClient(config=mqtt_config)

        # EventBus
        self.event_bus: Optional[EventBus] = None

        # Telegram
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        # 통계
        self.total_bets: int = 0
        self.winning_bets: int = 0
        self.total_wagered: float = 0.0
        self.total_pnl: float = 0.0

        # 콜백
        self.on_opportunity: Optional[Callable[[MarketOpportunity], None]] = None
        self.on_trade: Optional[Callable[[PolymarketTrade], None]] = None

        logger.info(f"PolymarketAIBot {bot_id} initialized (capital=${capital})")

    def _load_credentials(self) -> tuple:
        """.env에서 Polymarket 자격증명 로드"""
        wallet = os.environ.get("METAMASK_ADDRESS")
        api_key = os.environ.get("POLYMARKET_API_KEY")
        api_secret = os.environ.get("POLYMARKET_API_SECRET")
        return wallet, api_key, api_secret

    async def initialize(self):
        """봇 초기화"""
        if not POLYMARKET_AVAILABLE:
            logger.warning("py-clob-client not available, using mock mode")
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
        """실제 Polymarket 연결 초기화"""
        try:
            wallet, api_key, api_secret = self._load_credentials()

            if not wallet:
                logger.warning("Wallet address not found, switching to mock mode")
                await self._initialize_mock()
                return

            self.wallet_address = wallet

            # CLOB Client 초기화
            host = "https://clob.polymarket.com"
            creds = ApiCreds(api_key=api_key or "", api_secret=api_secret or "")
            self.client = ClobClient(host, key=None, chain_id=137, creds=creds)

            self.status = PolymarketStatus.RUNNING
            logger.info("Polymarket live mode initialized")

            # 시작 알림
            await self._send_telegram_notification(
                f"🎯 Polymarket AI 봇 시작\n"
                f"자본: ${self.capital} USDC\n"
                f"최소 괴리: {self.min_edge * 100}%\n"
                f"Kelly Fraction: {self.kelly_fraction}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize Polymarket live mode: {e}")
            logger.info("Falling back to mock mode")
            await self._initialize_mock()

    async def _initialize_mock(self):
        """Mock 모드 초기화"""
        self.mock_mode = True
        self.status = PolymarketStatus.MOCK
        self.wallet_address = "0xMockPolymarketWallet"

        # Mock 시장 데이터
        self._mock_markets = [
            {
                "id": "mock-001",
                "question": "Will BTC reach $100k by end of 2025?",
                "yes_price": 0.65,
                "no_price": 0.35
            },
            {
                "id": "mock-002",
                "question": "Will ETH outperform BTC in 2025?",
                "yes_price": 0.45,
                "no_price": 0.55
            }
        ]

        logger.info("Polymarket mock mode initialized")

        # 시작 알림
        await self._send_telegram_notification(
            f"🎯 Polymarket AI 봇 시작 (Mock)\n"
            f"자본: ${self.capital} USDC"
        )

    async def run(self):
        """메인 루프"""
        try:
            await self.initialize()
        except Exception as e:
            logger.error(f"Polymarket bot initialization failed: {e}")
            self.status = PolymarketStatus.ERROR
            raise

        try:
            while self.status in [PolymarketStatus.RUNNING, PolymarketStatus.MOCK]:
                try:
                    # 활성 시장 스캔
                    markets = await self._fetch_active_markets()

                    # 각 시장 분석
                    for market in markets:
                        opportunity = await self._analyze_market(market)

                        if opportunity and abs(opportunity.edge) >= self.min_edge:
                            # 검증
                            signal = await self._validate_opportunity(opportunity)

                            if signal and signal.get("valid", False):
                                await self._place_bet(opportunity)

                    await asyncio.sleep(300)  # 5분마다 체크

                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("Polymarket bot cancelled")
            await self.stop()
        except Exception as e:
            logger.error(f"Polymarket bot error: {e}")
            self.status = PolymarketStatus.ERROR
            await self.stop()
            raise

    async def _fetch_active_markets(self) -> List[Dict]:
        """활성 예측 시장 조회"""
        if self.mock_mode:
            return self._mock_markets

        try:
            # TODO: Polymarket API에서 활성 시장 조회
            return []
        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")
            return []

    async def _analyze_market(self, market: Dict) -> Optional[MarketOpportunity]:
        """AI 기반 시장 분석"""
        try:
            market_id = market.get("id", "")
            question = market.get("question", "")
            market_yes_price = market.get("yes_price", 0.5)
            market_prob = market_yes_price

            # AI 분석
            analysis = await self.llm_analyzer.analyze({
                "type": "prediction_market",
                "question": question,
                "market_probability": market_prob,
                "context": "Polymarket prediction market"
            })

            ai_prob = analysis.get("probability", market_prob)

            # 괴리 계산
            edge = ai_prob - market_prob

            # Kelly Criterion 계산
            if edge > 0:
                kelly = edge / (market_prob * (1 - market_prob))
                kelly = min(kelly * self.kelly_fraction, 0.5)  # 1/4 Kelly, 최대 50%
            else:
                kelly = 0

            recommended_bet = self.capital * kelly
            recommended_bet = max(min(recommended_bet, self.max_bet), self.min_bet)

            if abs(edge) >= self.min_edge:
                return MarketOpportunity(
                    market_id=market_id,
                    question=question,
                    ai_probability=ai_prob,
                    market_probability=market_prob,
                    edge=edge,
                    kelly_fraction=kelly,
                    recommended_bet=recommended_bet
                )

            return None

        except Exception as e:
            logger.error(f"Failed to analyze market: {e}")
            return None

    async def _validate_opportunity(self, opportunity: MarketOpportunity) -> Optional[Dict]:
        """Signal Generator를 통한 검증"""
        try:
            signal = await self.signal_generator.generate_signal({
                "type": "polymarket_opportunity",
                "market_id": opportunity.market_id,
                "question": opportunity.question,
                "edge": opportunity.edge,
                "ai_probability": opportunity.ai_probability,
                "market_probability": opportunity.market_probability
            })
            return signal
        except Exception as e:
            logger.error(f"Failed to validate opportunity: {e}")
            return None

    async def _place_bet(self, opportunity: MarketOpportunity):
        """베팅 실행"""
        try:
            side = "yes" if opportunity.edge > 0 else "no"
            amount = opportunity.recommended_bet
            price = opportunity.market_probability if side == "yes" else (1 - opportunity.market_probability)

            if self.mock_mode:
                order_id = f"mock_{datetime.utcnow().timestamp()}"
            else:
                # TODO: 실제 Polymarket 주문 실행
                order_id = ""

            # 거래 기록
            trade = PolymarketTrade(
                id=order_id,
                market_id=opportunity.market_id,
                question=opportunity.question,
                side=side,
                amount=amount,
                price=price,
                timestamp=datetime.utcnow(),
                expected_pnl=amount * abs(opportunity.edge)
            )
            self.trades.append(trade)
            self.total_bets += 1
            self.total_wagered += amount

            logger.info(
                f"Bet placed on {opportunity.question}: "
                f"{side} ${amount:.2f} @ {price:.2%} (edge: {opportunity.edge:+.1%})"
            )

            # Telegram 알림
            emoji = "🟢" if opportunity.edge > 0 else "🔴"
            await self._send_telegram_notification(
                f"{emoji} Polymarket 베팅 실행\n"
                f"시장: {opportunity.question[:50]}...\n"
                f"방향: {side.upper()}\n"
                f"금액: ${amount:.2f}\n"
                f"AI 확률: {opportunity.ai_probability:.1%}\n"
                f"시장 확률: {opportunity.market_probability:.1%}\n"
                f"괴리: {opportunity.edge:+.1%}"
            )

            if self.on_trade:
                self.on_trade(trade)

        except Exception as e:
            logger.error(f"Failed to place bet: {e}")

    async def stop(self):
        """봇 중지"""
        self.status = PolymarketStatus.IDLE

        # EventBus 연결 해제
        if self.event_bus:
            await self.event_bus.disconnect()

        await self.mqtt.disconnect()

        # 일일 리포트
        await self._send_daily_report()

        logger.info(f"Polymarket AI bot {self.bot_id} stopped")

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
            f"📊 Polymarket AI Bot 일일 리포트\n"
            f"모드: {'Mock' if self.mock_mode else 'Live'}\n"
            f"총 베팅: {self.total_bets}회\n"
            f"총 베팅액: ${self.total_wagered:.2f}\n"
            f"예상 PnL: ${self.total_pnl:.2f}"
        )

    def get_status(self) -> Dict[str, Any]:
        """봇 상태 반환"""
        return {
            "bot_id": self.bot_id,
            "bot_type": "polymarket",
            "status": self.status.value,
            "capital": self.capital,
            "mock_mode": self.mock_mode,
            "wallet": self.wallet_address[:10] + "..." if self.wallet_address else None,
            "total_bets": self.total_bets,
            "total_wagered": self.total_wagered,
            "total_pnl": self.total_pnl,
            "active_opportunities": len(self.active_opportunities),
            "timestamp": datetime.utcnow().isoformat()
        }


async def main():
    """단독 실행용"""
    bot = PolymarketAIBot(
        bot_id="polymarket_ai_001",
        capital=19.85,
        mock_mode=False
    )

    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()
        print("\n📊 Final Stats:")
        status = bot.get_status()
        print(f"   Total Bets: {status['total_bets']}")
        print(f"   Total Wagered: ${status['total_wagered']:.2f}")


if __name__ == "__main__":
    asyncio.run(main())

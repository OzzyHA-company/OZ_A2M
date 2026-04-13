"""
Hyperliquid AI 방향성 레버리지 봇 - SOL-PERP 5x
OZ_A2M 도파민봇

설정:
- 거래소: Hyperliquid DEX
- 전략: AI 신호 기반 방향성 베팅 (롱/숏)
- 레버리지: 5배
- 자본: $4.69 → 포지션 ~$23.45
- 손절: -20%, 익절: +50%
- 도파민봇 (고위험/고수익)
"""

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from enum import Enum

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger
from lib.messaging.event_bus import EventBus, get_event_bus
from lib.pi_mono_bridge.bridge import get_pi_mono_bridge

logger = get_logger(__name__)

try:
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
    import hyperliquid.utils.constants as hl_constants
    HYPERLIQUID_AVAILABLE = True
except ImportError:
    HYPERLIQUID_AVAILABLE = False
    logger.warning("hyperliquid-python-sdk not installed, mock mode 사용")


class HyperliquidStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    MOCK = "mock"


@dataclass
class HLPosition:
    symbol: str
    side: str        # "long" or "short"
    size: float      # SOL 수량
    entry_price: float
    unrealized_pnl: float
    leverage: int


@dataclass
class HLTrade:
    id: str
    symbol: str
    side: str
    size: float
    entry_price: float
    exit_price: float
    timestamp: datetime
    pnl: float = 0.0


class HyperliquidMarketMakerBot:
    """
    Hyperliquid AI 방향성 레버리지 봇

    전략:
    - PiMonoBridge (Gemini)로 SOL 방향 분석
    - 롱 또는 숏 5배 레버리지 포지션 진입
    - 손절 -20% / 익절 +50% 자동 관리
    - 방향 전환 시 기존 포지션 청산 후 반대 진입
    """

    LEVERAGE = 5
    STOP_LOSS_PCT = 0.20    # -20%
    TAKE_PROFIT_PCT = 0.50  # +50%
    LOOP_INTERVAL = 60      # 60초마다 AI 신호 확인

    def __init__(
        self,
        bot_id: str = "hyperliquid_mm_001",
        symbol: str = "SOL-PERP",
        capital: float = 4.69,
        base_spread_bps: float = 10.0,   # 사용 안 함 (호환성 유지)
        sandbox: bool = False,
        mock_mode: bool = False,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        telegram_alerts: bool = True
    ):
        self.bot_id = bot_id
        self.symbol = symbol
        self.capital = capital
        self.coin = symbol.replace("-PERP", "")  # "SOL"
        self.sandbox = sandbox
        self.mock_mode = mock_mode
        self.telegram_alerts = telegram_alerts

        self.status = HyperliquidStatus.IDLE
        self.exchange: Optional[Any] = None
        self.info: Optional[Any] = None
        self.wallet_address: Optional[str] = None

        # 현재 포지션
        self.position: Optional[HLPosition] = None
        self.trades: List[HLTrade] = []

        # AI 브릿지
        self.bridge = get_pi_mono_bridge()

        # EventBus
        self.event_bus: Optional[EventBus] = None

        # Telegram
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        # 통계
        self.total_trades: int = 0
        self.total_pnl: float = 0.0
        self.start_time = datetime.utcnow()

        # Mock 상태
        self._mock_price: float = 85.0
        self._mock_direction: Optional[str] = None

        # 콜백
        self.on_trade: Optional[Callable[[HLTrade], None]] = None
        self.on_position_change: Optional[Callable] = None

        logger.info(f"HyperliquidMarketMakerBot {bot_id} initialized (capital=${capital}, leverage={self.LEVERAGE}x)")

    # ──────────────────────────────────────────
    # 초기화
    # ──────────────────────────────────────────

    def _load_wallet(self) -> Optional[str]:
        return os.environ.get("PHANTOM_WALLET_A")

    async def initialize(self):
        if not HYPERLIQUID_AVAILABLE:
            logger.warning("Hyperliquid SDK 없음 — mock 모드")
            self.mock_mode = True

        if self.mock_mode:
            await self._initialize_mock()
        else:
            await self._initialize_live()

        try:
            self.event_bus = get_event_bus(mqtt_host="localhost", mqtt_port=1883)
            await self.event_bus.connect()
            logger.info("EventBus connected")
        except Exception as e:
            logger.warning(f"EventBus 연결 실패: {e}")
            self.event_bus = None

    async def _initialize_live(self):
        try:
            private_key = os.environ.get("HYPERLIQUID_PRIVATE_KEY") or os.environ.get("METAMASK_PRIVATE_KEY")
            if not private_key:
                logger.warning("METAMASK_PRIVATE_KEY 없음 — mock 모드")
                await self._initialize_mock()
                return

            from eth_account import Account
            eth_wallet = Account.from_key(private_key)
            self.wallet_address = eth_wallet.address

            self.info = Info(base_url=hl_constants.MAINNET_API_URL, skip_ws=True)
            self.exchange = Exchange(
                wallet=eth_wallet,
                base_url=hl_constants.MAINNET_API_URL,
            )

            # 레버리지 5배 설정
            try:
                result = self.exchange.update_leverage(self.LEVERAGE, self.coin, is_cross=True)
                logger.info(f"레버리지 {self.LEVERAGE}x 설정 완료: {result}")
            except Exception as e:
                logger.warning(f"레버리지 설정 실패 (이미 설정됐을 수 있음): {e}")

            self.status = HyperliquidStatus.RUNNING
            logger.info(f"Hyperliquid 연결 완료 (EVM: {self.wallet_address[:10]}...)")

            await self._send_telegram(
                f"⚡ Hyperliquid AI 레버리지 봇 시작\n"
                f"심볼: {self.symbol}\n"
                f"자본: ${self.capital} × {self.LEVERAGE}배 = ${self.capital * self.LEVERAGE:.2f}\n"
                f"손절: -{self.STOP_LOSS_PCT*100}% / 익절: +{self.TAKE_PROFIT_PCT*100}%"
            )

        except Exception as e:
            logger.error(f"Hyperliquid 초기화 실패: {e}")
            await self._initialize_mock()

    async def _initialize_mock(self):
        self.mock_mode = True
        self.status = HyperliquidStatus.MOCK
        self.wallet_address = "0xMockWallet"
        logger.info("Hyperliquid mock 모드 초기화")
        await self._send_telegram(
            f"⚡ Hyperliquid AI 봇 시작 (Mock)\n"
            f"심볼: {self.symbol} | 자본: ${self.capital}"
        )

    # ──────────────────────────────────────────
    # 메인 루프
    # ──────────────────────────────────────────

    async def run(self):
        try:
            await self.initialize()
        except Exception as e:
            logger.error(f"초기화 실패: {e}")
            self.status = HyperliquidStatus.ERROR
            raise

        try:
            while self.status in [HyperliquidStatus.RUNNING, HyperliquidStatus.MOCK]:
                try:
                    if self.mock_mode:
                        await self._run_mock_loop()
                    else:
                        await self._run_live_loop()
                except Exception as e:
                    logger.error(f"루프 오류: {e}")

                await asyncio.sleep(self.LOOP_INTERVAL)

        except asyncio.CancelledError:
            logger.info("Hyperliquid bot cancelled")
            await self.stop()
        except Exception as e:
            logger.error(f"Hyperliquid bot 오류: {e}")
            self.status = HyperliquidStatus.ERROR
            await self.stop()
            raise

    # ──────────────────────────────────────────
    # 실거래 루프
    # ──────────────────────────────────────────

    async def _run_live_loop(self):
        """AI 신호 → 롱/숏 방향성 베팅"""
        try:
            # 1. 현재 SOL 가격 및 포지션 확인
            mid_price = await self._get_mid_price()
            if not mid_price:
                return

            current_position = await self._get_current_position()

            # 2. 손절/익절 체크 (포지션 있을 때)
            if current_position:
                if await self._check_exit_conditions(current_position, mid_price):
                    return  # 청산 완료, 이번 루프 종료

            # 3. AI 신호 획득
            signal = await self._get_ai_signal(mid_price)
            logger.info(f"AI signal: {signal} (SOL mid: ${mid_price:.2f})")

            if signal == "hold":
                return

            # 4. 기존 포지션과 방향이 같으면 유지
            if current_position:
                if current_position.side == signal:
                    logger.info(f"포지션 유지: {signal} @ ${current_position.entry_price:.2f}")
                    return
                # 반대 신호 → 청산 후 반전
                logger.info(f"방향 전환: {current_position.side} → {signal}, 포지션 청산")
                await self._close_position(current_position, mid_price, reason="방향전환")

            # 5. 새 포지션 진입
            await self._open_position(signal, mid_price)

        except Exception as e:
            logger.error(f"live loop 오류: {e}")

    async def _get_mid_price(self) -> Optional[float]:
        """SOL-PERP 현재가"""
        try:
            l2 = self.info.l2_snapshot(self.coin)
            bids = l2.get("levels", [[], []])[0]
            asks = l2.get("levels", [[], []])[1]
            if bids and asks:
                return (float(bids[0]["px"]) + float(asks[0]["px"])) / 2
        except Exception as e:
            logger.error(f"가격 조회 실패: {e}")
        return None

    async def _get_current_position(self) -> Optional[HLPosition]:
        """현재 오픈 포지션 조회"""
        try:
            state = self.info.user_state(self.wallet_address)
            for p in state.get("assetPositions", []):
                pos = p.get("position", {})
                if pos.get("coin") == self.coin:
                    szi = float(pos.get("szi", 0))
                    if abs(szi) < 0.001:
                        continue
                    entry = float(pos.get("entryPx", 0))
                    pnl = float(pos.get("unrealizedPnl", 0))
                    side = "long" if szi > 0 else "short"
                    lev = int(pos.get("leverage", {}).get("value", self.LEVERAGE))
                    return HLPosition(
                        symbol=self.symbol,
                        side=side,
                        size=abs(szi),
                        entry_price=entry,
                        unrealized_pnl=pnl,
                        leverage=lev,
                    )
        except Exception as e:
            logger.error(f"포지션 조회 실패: {e}")
        return None

    async def _check_exit_conditions(self, pos: HLPosition, mid_price: float) -> bool:
        """손절(-20%) / 익절(+50%) 체크"""
        if pos.entry_price <= 0:
            return False

        pct = (mid_price - pos.entry_price) / pos.entry_price
        if pos.side == "short":
            pct = -pct

        if pct <= -self.STOP_LOSS_PCT:
            logger.warning(f"손절 발동: {pct*100:.1f}% (entry: ${pos.entry_price:.2f}, now: ${mid_price:.2f})")
            await self._close_position(pos, mid_price, reason="손절")
            return True

        if pct >= self.TAKE_PROFIT_PCT:
            logger.info(f"익절 발동: +{pct*100:.1f}% (entry: ${pos.entry_price:.2f}, now: ${mid_price:.2f})")
            await self._close_position(pos, mid_price, reason="익절")
            return True

        return False

    async def _get_ai_signal(self, mid_price: float) -> str:
        """OZ_Central LLM Gateway로 SOL 방향 질의 → 'long' / 'short' / 'hold'"""
        try:
            import httpx
            prompt = (
                f"SOL-PERP 현재가 ${mid_price:.2f}.\n"
                f"지금 {self.LEVERAGE}배 레버리지로 롱 또는 숏 진입해야 하는지 판단해.\n"
                f"반드시 JSON으로만 답해: "
                f'{{\"direction\": \"long\" 또는 \"short\" 또는 \"hold\", '
                f'\"confidence\": 0.0~1.0, \"reason\": \"한줄\"}}'
            )
            oz_central = os.environ.get("OZ_CENTRAL_URL", "http://localhost:8000")
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{oz_central}/llm/analyze-market",
                    json={"symbol": "SOL-PERP", "indicators": {"price": mid_price}}
                )
                data = resp.json()
                direction = data.get("direction", "hold").lower()
                confidence = float(data.get("confidence", 0))

            if confidence < 0.6:
                logger.info(f"AI 신뢰도 낮음 ({confidence:.2f}) → hold")
                return "hold"

            logger.info(f"AI signal: {direction} (신뢰도: {confidence:.2f})")
            return direction if direction in ("long", "short") else "hold"

        except Exception as e:
            logger.warning(f"AI 신호 실패: {e}")

        return "hold"

    async def _open_position(self, side: str, mid_price: float):
        """포지션 진입 (시장가)"""
        is_buy = (side == "long")
        # 포지션 크기: 자본 전체 사용 (레버리지 5배 적용)
        sz = round(self.capital * self.LEVERAGE / mid_price, 3)
        if sz < 0.001:
            logger.warning(f"주문 크기 너무 작음: {sz}")
            return

        try:
            result = self.exchange.market_open(self.coin, is_buy, sz)
            status = result.get("status", "")
            if status == "ok":
                self.total_trades += 1
                logger.info(f"✅ {side.upper()} 진입: {sz} SOL @ ~${mid_price:.2f} (×{self.LEVERAGE})")
                await self._send_telegram(
                    f"{'🟢 롱' if is_buy else '🔴 숏'} 진입\n"
                    f"SOL-PERP {sz} @ ${mid_price:.2f}\n"
                    f"포지션: ${self.capital * self.LEVERAGE:.2f}"
                )
            else:
                logger.error(f"주문 실패: {result}")
        except Exception as e:
            logger.error(f"진입 오류: {e}")

    async def _close_position(self, pos: HLPosition, mid_price: float, reason: str = ""):
        """포지션 청산 (시장가)"""
        is_buy = (pos.side == "short")  # 숏 청산 = 매수, 롱 청산 = 매도
        try:
            result = self.exchange.market_close(self.coin, is_buy, pos.size)
            status = result.get("status", "")
            if status == "ok":
                pct = (mid_price - pos.entry_price) / pos.entry_price
                if pos.side == "short":
                    pct = -pct
                pnl_usd = pct * self.capital * self.LEVERAGE
                self.total_pnl += pnl_usd
                self.total_trades += 1

                logger.info(f"{'✅' if pnl_usd >= 0 else '❌'} 청산 ({reason}): {pct*100:+.1f}% | PnL: ${pnl_usd:+.2f}")
                await self._send_telegram(
                    f"{'✅' if pnl_usd >= 0 else '❌'} 포지션 청산 ({reason})\n"
                    f"{pos.side.upper()} @ ${pos.entry_price:.2f} → ${mid_price:.2f}\n"
                    f"수익: {pct*100:+.1f}% | ${pnl_usd:+.2f}"
                )

                trade = HLTrade(
                    id=f"hl_{self.total_trades}",
                    symbol=self.symbol,
                    side=pos.side,
                    size=pos.size,
                    entry_price=pos.entry_price,
                    exit_price=mid_price,
                    timestamp=datetime.utcnow(),
                    pnl=pnl_usd,
                )
                self.trades.append(trade)
                if self.on_trade:
                    self.on_trade(trade)
            else:
                logger.error(f"청산 실패: {result}")
        except Exception as e:
            logger.error(f"청산 오류: {e}")

    # ──────────────────────────────────────────
    # Mock 루프
    # ──────────────────────────────────────────

    async def _run_mock_loop(self):
        import random
        self._mock_price *= (1 + random.uniform(-0.005, 0.005))
        signal = random.choice(["long", "short", "hold", "hold"])
        logger.info(f"[MOCK] AI signal: {signal} | SOL: ${self._mock_price:.2f}")

        if signal != "hold":
            pnl = random.uniform(-self.capital * 0.2, self.capital * 0.5)
            self.total_pnl += pnl
            self.total_trades += 1
            logger.info(f"[MOCK] {'롱' if signal=='long' else '숏'} | PnL: ${pnl:+.2f}")

    # ──────────────────────────────────────────
    # 유틸
    # ──────────────────────────────────────────

    async def stop(self):
        """봇 정지 - 열린 포지션 먼저 청산 후 중지"""
        logger.info(f"Hyperliquid bot {self.bot_id} stopping...")
        try:
            if self.position:
                mid_price = await self._get_mid_price()
                if mid_price:
                    logger.info(f"Closing open position on stop: {self.position.side} {self.position.size}")
                    await self._close_position(self.position, mid_price, reason="봇중지")
                    self.position = None
        except Exception as e:
            logger.error(f"Position close failed on stop: {e}")
        finally:
            if self.event_bus:
                try:
                    await self.event_bus.disconnect()
                except Exception:
                    pass
        logger.info(f"Hyperliquid bot {self.bot_id} stopped | 총 PnL: ${self.total_pnl:+.2f}")

    async def _safe_stop(self):
        await self.stop()

    async def _send_telegram(self, message: str):
        if not self.telegram_alerts or not self.telegram_bot_token or not self.telegram_chat_id:
            return
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage",
                    json={"chat_id": self.telegram_chat_id, "text": message}
                )
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        return {
            "bot_id": self.bot_id,
            "status": self.status.value,
            "capital": self.capital,
            "leverage": self.LEVERAGE,
            "position": {
                "side": self.position.side if self.position else None,
                "size": self.position.size if self.position else 0,
                "entry_price": self.position.entry_price if self.position else 0,
                "pnl": self.position.unrealized_pnl if self.position else 0,
            },
            "total_trades": self.total_trades,
            "total_pnl": self.total_pnl,
        }

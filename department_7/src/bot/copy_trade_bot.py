"""
GMGN Copy Trade Bot - 스마트머니 카피 트레이드 봇
STEP 14: OZ_A2M 완결판

설정:
- Solana 스마트머니 지갑 추적
- Helius Parse TX API 사용
- 자동 거래 복사
- 자본: 0.067 SOL
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

logger = get_logger(__name__)


class CopyStatus(str, Enum):
    """카피봇 상태"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    MOCK = "mock"


@dataclass
class TrackedWallet:
    """추적 중인 지갑"""
    address: str
    label: str
    success_rate: float
    total_pnl: float
    added_at: datetime


@dataclass
class CopyTrade:
    """복사 거래 기록"""
    id: str
    original_wallet: str
    token_address: str
    token_symbol: str
    side: str
    amount: float
    price: float
    timestamp: datetime
    pnl: Optional[float] = None


class GMGNCopyBot:
    """
    GMGN 스마트머니 카피봇

    전략:
    - Solscan/SolanaFM API로 스마트머니 지갑 추적
    - 성과 좋은 지갑의 거래 자동 복사
    - 위험 관리: 단일 거래 최대 10% 자본
    """

    def __init__(
        self,
        bot_id: str = "gmgn_copy_001",
        capital_sol: float = 0.067,
        copy_percentage: float = 0.1,  # 원 거래의 10% 복사
        max_position_pct: float = 0.1,  # 최대 10% 자본
        min_wallet_success_rate: float = 0.6,  # 60% 이상 승률
        mock_mode: bool = False,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        telegram_alerts: bool = True
    ):
        self.bot_id = bot_id
        self.capital_sol = capital_sol
        self.copy_percentage = copy_percentage
        self.max_position_pct = max_position_pct
        self.min_wallet_success_rate = min_wallet_success_rate
        self.mock_mode = mock_mode
        self.telegram_alerts = telegram_alerts

        # 상태
        self.status = CopyStatus.IDLE
        self.tracked_wallets: Dict[str, TrackedWallet] = {}
        self.active_positions: Dict[str, Dict] = {}
        self.trades: List[CopyTrade] = []
        self.wallet_address: Optional[str] = None

        # API
        self.helius_parse_url = os.environ.get("HELIUS_PARSE_TX_URL")

        # MQTT
        mqtt_config = MQTTConfig(host=mqtt_host, port=mqtt_port, client_id=bot_id)
        self.mqtt = MQTTClient(config=mqtt_config)

        # EventBus
        self.event_bus: Optional[EventBus] = None

        # Telegram
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        # 통계
        self.total_copies: int = 0
        self.successful_copies: int = 0
        self.total_pnl_sol: float = 0.0

        # 콜백
        self.on_copy: Optional[Callable[[CopyTrade], None]] = None
        self.on_trade: Optional[Callable[[CopyTrade], None]] = None

        logger.info(f"GMGNCopyBot {bot_id} initialized (capital={capital_sol} SOL)")

    def _load_wallet(self) -> Optional[str]:
        """.env에서 Phantom 지갑 주소 로드"""
        return os.environ.get("PHANTOM_WALLET_C")

    def _load_tracked_wallets(self) -> List[str]:
        """추적할 스마트머니 지갑 목록"""
        # 기본 스마트머니 지갑 (예시)
        default_wallets = [
            "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVbNUqSJG5",  # 예시
        ]

        # 환경변수에서 추가 지갑 로드
        env_wallets = os.environ.get("TRACKED_WALLETS", "")
        if env_wallets:
            default_wallets.extend(env_wallets.split(","))

        return default_wallets

    async def initialize(self):
        """봇 초기화"""
        self.wallet_address = self._load_wallet()

        # 추적할 지갑 설정
        wallet_addresses = self._load_tracked_wallets()
        for addr in wallet_addresses:
            self.tracked_wallets[addr] = TrackedWallet(
                address=addr,
                label=f"Smart_{addr[:6]}",
                success_rate=0.0,
                total_pnl=0.0,
                added_at=datetime.utcnow()
            )

        if self.mock_mode or not self.helius_parse_url:
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
        """실제 모드 초기화"""
        try:
            self.status = CopyStatus.RUNNING
            logger.info("GMGN copy bot live mode initialized")

            # 시작 알림
            await self._send_telegram_notification(
                f"👥 GMGN 카피봇 시작\n"
                f"자본: {self.capital_sol} SOL\n"
                f"추적 지갑: {len(self.tracked_wallets)}개\n"
                f"복사 비율: {self.copy_percentage * 100}%"
            )

        except Exception as e:
            logger.error(f"Failed to initialize live mode: {e}")
            await self._initialize_mock()

    async def _initialize_mock(self):
        """Mock 모드 초기화"""
        self.mock_mode = True
        self.status = CopyStatus.MOCK

        if not self.wallet_address:
            self.wallet_address = "MockCopyWallet"

        logger.info("GMGN copy bot mock mode initialized")

        # 시작 알림
        await self._send_telegram_notification(
            f"👥 GMGN 카피봇 시작 (Mock)\n"
            f"자본: {self.capital_sol} SOL\n"
            f"추적 지갑: {len(self.tracked_wallets)}개"
        )

    async def run(self):
        """메인 루프"""
        try:
            await self.initialize()
        except Exception as e:
            logger.error(f"GMGN copy bot initialization failed: {e}")
            self.status = CopyStatus.ERROR
            raise

        try:
            while self.status in [CopyStatus.RUNNING, CopyStatus.MOCK]:
                try:
                    # 추적 지갑 모니터링
                    await self._monitor_wallets()

                    # 포지션 관리
                    await self._manage_positions()

                    await asyncio.sleep(30)  # 30초마다 체크

                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    await asyncio.sleep(10)

        except asyncio.CancelledError:
            logger.info("GMGN copy bot cancelled")
            await self.stop()
        except Exception as e:
            logger.error(f"GMGN copy bot error: {e}")
            self.status = CopyStatus.ERROR
            await self.stop()
            raise

    async def _monitor_wallets(self):
        """지갑 모니터링"""
        for address, wallet in list(self.tracked_wallets.items()):
            try:
                # 지갑 거래 내역 조회
                transactions = await self._fetch_wallet_transactions(address)

                for tx in transactions:
                    # 새로운 거래 확인
                    if self._is_new_trade(tx):
                        # 지갑 성과 확인
                        if wallet.success_rate >= self.min_wallet_success_rate:
                            await self._copy_trade(wallet, tx)

            except Exception as e:
                logger.error(f"Error monitoring wallet {address}: {e}")

    async def _fetch_wallet_transactions(self, wallet_address: str) -> List[Dict]:
        """지갑 거래 내역 조회"""
        if self.mock_mode:
            # Mock 거래 데이터
            import random
            if random.random() < 0.1:  # 10% 확률로 거래 발생
                return [{
                    "signature": f"mock_tx_{random.randint(1000, 9999)}",
                    "token": f"MOCK{random.randint(1, 99)}",
                    "side": "buy" if random.random() > 0.5 else "sell",
                    "amount": random.uniform(0.01, 0.1),
                    "price": random.uniform(0.001, 0.01)
                }]
            return []

        # TODO: Helius 또는 Solscan API로 거래 내역 조회
        return []

    def _is_new_trade(self, transaction: Dict) -> bool:
        """새로운 거래 여부 확인"""
        # TODO: 중복 거래 필터링
        return True

    async def _copy_trade(self, wallet: TrackedWallet, transaction: Dict):
        """거래 복사"""
        try:
            token = transaction.get("token", "UNKNOWN")
            side = transaction.get("side", "buy")
            original_amount = transaction.get("amount", 0)

            # 복사 금액 계산
            copy_amount = original_amount * self.copy_percentage
            max_amount = self.capital_sol * self.max_position_pct
            final_amount = min(copy_amount, max_amount)

            if final_amount <= 0:
                return

            # 거래 실행
            self.total_copies += 1

            trade = CopyTrade(
                id=f"copy_{datetime.utcnow().timestamp()}",
                original_wallet=wallet.address,
                token_address=token,
                token_symbol=token,
                side=side,
                amount=final_amount,
                price=transaction.get("price", 0),
                timestamp=datetime.utcnow()
            )
            self.trades.append(trade)

            # 포지션 업데이트
            token_addr = transaction.get("token_address", token)
            if side == "buy":
                self.active_positions[token_addr] = {
                    "token": token,
                    "amount": final_amount,
                    "entry_price": transaction.get("price", 0),
                    "copied_from": wallet.address
                }
            elif side == "sell" and token_addr in self.active_positions:
                position = self.active_positions[token_addr]
                entry = position["entry_price"]
                exit_price = transaction.get("price", entry)

                pnl = (exit_price - entry) / entry * final_amount if entry > 0 else 0
                trade.pnl = pnl
                self.total_pnl_sol += pnl

                if pnl > 0:
                    self.successful_copies += 1

                del self.active_positions[token_addr]

            logger.info(f"Copied trade: {token} {side} {final_amount} SOL from {wallet.label}")

            # Telegram 알림
            emoji = "📥" if side == "buy" else "📤"
            await self._send_telegram_notification(
                f"{emoji} 거래 복사\n"
                f"원본: {wallet.label}\n"
                f"토큰: {token}\n"
                f"방향: {side.upper()}\n"
                f"금액: {final_amount:.3f} SOL"
            )

            if self.on_copy:
                self.on_copy(trade)

        except Exception as e:
            logger.error(f"Failed to copy trade: {e}")

    async def _manage_positions(self):
        """포지션 관리"""
        # TODO: 손절/익절 로직
        pass

    async def stop(self):
        """봇 중지"""
        self.status = CopyStatus.IDLE

        # 모든 포지션 정리
        for token_addr, position in list(self.active_positions.items()):
            logger.info(f"Closing position: {position['token']}")
            # TODO: 매도 실행

        # EventBus 연결 해제
        if self.event_bus:
            await self.event_bus.disconnect()

        await self.mqtt.disconnect()

        # 리포트 발송
        await self._send_daily_report()

        logger.info(f"GMGN copy bot {self.bot_id} stopped")

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
        win_rate = (self.successful_copies / self.total_copies * 100) if self.total_copies > 0 else 0
        await self._send_telegram_notification(
            f"📊 GMGN 카피봇 리포트\n"
            f"총 복사: {self.total_copies}회\n"
            f"성공: {self.successful_copies}회\n"
            f"승률: {win_rate:.1f}%\n"
            f"총 손익: {self.total_pnl_sol:+.3f} SOL\n"
            f"추적 지갑: {len(self.tracked_wallets)}개"
        )

    def get_status(self) -> Dict[str, Any]:
        """봇 상태 반환"""
        win_rate = (self.successful_copies / self.total_copies * 100) if self.total_copies > 0 else 0

        return {
            "bot_id": self.bot_id,
            "bot_type": "copy_trade",
            "status": self.status.value,
            "capital_sol": self.capital_sol,
            "mock_mode": self.mock_mode,
            "tracked_wallets": len(self.tracked_wallets),
            "total_copies": self.total_copies,
            "successful_copies": self.successful_copies,
            "win_rate": win_rate,
            "total_pnl_sol": self.total_pnl_sol,
            "active_positions": len(self.active_positions),
            "timestamp": datetime.utcnow().isoformat()
        }


async def main():
    """단독 실행용"""
    bot = GMGNCopyBot(
        bot_id="gmgn_copy_001",
        capital_sol=0.067,
        mock_mode=False
    )

    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()
        print("\n📊 Final Stats:")
        status = bot.get_status()
        print(f"   Total Copies: {status['total_copies']}")
        print(f"   Win Rate: {status['win_rate']:.1f}%")
        print(f"   Total PnL: {status['total_pnl_sol']:+.3f} SOL")


if __name__ == "__main__":
    asyncio.run(main())

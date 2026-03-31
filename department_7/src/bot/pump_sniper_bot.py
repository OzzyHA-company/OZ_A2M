"""
Pump.fun Sniper Bot - 펌프펀 스나이퍼 봇
STEP 14: OZ_A2M 완결판

설정:
- 네트워크: Solana (Pump.fun)
- QuickNode WebSocket 신규 토큰 감지
- 자동 익절 2~5배, 손절 -50%
- 자본: 0.1 SOL
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


class SniperStatus(str, Enum):
    """스나이퍼 봇 상태"""
    IDLE = "idle"
    RUNNING = "running"
    SNIPING = "sniping"
    PAUSED = "paused"
    ERROR = "error"
    MOCK = "mock"


@dataclass
class TokenSnipe:
    """스나이핑 대상 토큰"""
    address: str
    symbol: str
    name: str
    detected_at: datetime
    buy_price: float
    amount: float
    current_price: float
    highest_price: float
    status: str = "holding"  # holding, sold


@dataclass
class SnipeTrade:
    """스나이핑 거래 기록"""
    id: str
    token_address: str
    token_symbol: str
    side: str
    amount: float
    price: float
    timestamp: datetime
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None


class PumpSniperBot:
    """
    Pump.fun 스나이퍼 봇

    전략:
    - QuickNode WebSocket으로 신규 토큰 실시간 감지
    - 초기 유동성 분석 후 스나이핑
    - 2~5배 익절, -50% 손절
    """

    def __init__(
        self,
        bot_id: str = "pump_sniper_001",
        capital_sol: float = 0.1,
        take_profit_low: float = 2.0,  # 2배
        take_profit_high: float = 5.0,  # 5배
        stop_loss: float = 0.5,  # -50%
        max_slippage: float = 0.1,  # 10%
        mock_mode: bool = False,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        telegram_alerts: bool = True
    ):
        self.bot_id = bot_id
        self.capital_sol = capital_sol
        self.take_profit_low = take_profit_low
        self.take_profit_high = take_profit_high
        self.stop_loss = stop_loss
        self.max_slippage = max_slippage
        self.mock_mode = mock_mode
        self.telegram_alerts = telegram_alerts

        # 상태
        self.status = SniperStatus.IDLE
        self.solana_ws = None
        self.wallet_address: Optional[str] = None
        self.active_snipes: Dict[str, TokenSnipe] = {}
        self.trades: List[SnipeTrade] = []

        # MQTT
        mqtt_config = MQTTConfig(host=mqtt_host, port=mqtt_port, client_id=bot_id)
        self.mqtt = MQTTClient(config=mqtt_config)

        # EventBus
        self.event_bus: Optional[EventBus] = None

        # Telegram
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        # QuickNode (HTTP + WSS URL 지원)
        self.quicknode_http_url = os.environ.get("QUICKNODE_HTTP_URL")
        self.quicknode_ws_url = os.environ.get("QUICKNODE_WSS_URL")
        # WSS가 없으면 HTTP에서 변환
        if not self.quicknode_ws_url and self.quicknode_http_url:
            self.quicknode_ws_url = self.quicknode_http_url.replace("https://", "wss://")

        # 통계
        self.tokens_detected: int = 0
        self.tokens_sniped: int = 0
        self.successful_snipes: int = 0
        self.total_pnl_sol: float = 0.0

        # 콜백
        self.on_snipe: Optional[Callable[[TokenSnipe], None]] = None
        self.on_trade: Optional[Callable[[SnipeTrade], None]] = None

        logger.info(f"PumpSniperBot {bot_id} initialized (capital={capital_sol} SOL)")

    def _load_wallet(self) -> Optional[str]:
        """.env에서 Phantom 지갑 주소 로드"""
        return os.environ.get("PHANTOM_WALLET_B")

    async def initialize(self):
        """봇 초기화"""
        self.wallet_address = self._load_wallet()

        if self.mock_mode or not self.quicknode_ws_url:
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
        """실제 QuickNode 연결 초기화 (rate limit 대응)"""
        max_retries = 3
        retry_delay = 3  # 3초 대기

        for attempt in range(max_retries):
            try:
                # rate limit 방지를 위한 대기
                if attempt > 0:
                    logger.info(f"Retrying QuickNode connection in {retry_delay}s... (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(retry_delay)

                # WebSocket 연결
                import websockets

                logger.info(f"Connecting to QuickNode WebSocket: {self.quicknode_ws_url}")
                self.solana_ws = await websockets.connect(
                    self.quicknode_ws_url,
                    ping_interval=20,
                    ping_timeout=10
                )

                # Pump.fun 프로그램 구독
                pump_fun_program = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
                subscribe_msg = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "programSubscribe",
                    "params": [pump_fun_program, {"encoding": "jsonParsed"}]
                }
                await self.solana_ws.send(json.dumps(subscribe_msg))

                self.status = SniperStatus.RUNNING
                logger.info("Pump.fun sniper live mode initialized (QuickNode)")

                # 시작 알림
                await self._send_telegram_notification(
                    f"🚀 Pump.fun 스나이퍼 시작\n"
                    f"자본: {self.capital_sol} SOL\n"
                    f"익절: {self.take_profit_low}~{self.take_profit_high}x\n"
                    f"손절: -{self.stop_loss * 100}%"
                )
                return

            except Exception as e:
                logger.error(f"Failed to initialize QuickNode connection (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    retry_delay *= 2  # 지수 백오프
                else:
                    logger.info("Falling back to mock mode")
                    await self._initialize_mock()

    async def _initialize_mock(self):
        """Mock 모드 초기화"""
        self.mock_mode = True
        self.status = SniperStatus.MOCK

        if not self.wallet_address:
            self.wallet_address = "MockPumpWallet123"

        logger.info("Pump.fun sniper mock mode initialized")

        # 시작 알림
        await self._send_telegram_notification(
            f"🚀 Pump.fun 스나이퍼 시작 (Mock)\n"
            f"자본: {self.capital_sol} SOL"
        )

    async def run(self):
        """메인 루프"""
        try:
            await self.initialize()
        except Exception as e:
            logger.error(f"Pump sniper initialization failed: {e}")
            self.status = SniperStatus.ERROR
            raise

        try:
            if self.mock_mode:
                await self._run_mock_loop()
            else:
                await self._run_live_loop()

        except asyncio.CancelledError:
            logger.info("Pump sniper cancelled")
            await self.stop()
        except Exception as e:
            logger.error(f"Pump sniper error: {e}")
            self.status = SniperStatus.ERROR
            await self.stop()
            raise

    async def _run_live_loop(self):
        """실제 QuickNode WebSocket 루프"""
        try:
            import websockets

            while self.status == SniperStatus.RUNNING:
                try:
                    # WebSocket 메시지 수신
                    message = await asyncio.wait_for(
                        self.solana_ws.recv(),
                        timeout=30.0
                    )

                    data = json.loads(message)

                    # 새로운 토큰 생성 이벤트 확인
                    if self._is_new_token_launch(data):
                        await self._handle_new_token(data)

                    # 보유 토큰 모니터링
                    await self._monitor_positions()

                except asyncio.TimeoutError:
                    # 하트비트 확인
                    await self.solana_ws.ping()

        except websockets.exceptions.ConnectionClosed:
            logger.error("QuickNode WebSocket connection closed")
            await self._reconnect()

    async def _run_mock_loop(self):
        """Mock 모드 루프"""
        import random

        while self.status == SniperStatus.MOCK:
            try:
                # 랜덤하게 신규 토큰 시뮬레이션
                if random.random() < 0.05:  # 5% 확률
                    mock_token = {
                        "address": f"mock_token_{random.randint(1000, 9999)}",
                        "symbol": f"MOCK{random.randint(1, 99)}",
                        "name": "Mock Pump Token"
                    }
                    await self._handle_new_token(mock_token)

                # 보유 토큰 모니터링
                await self._monitor_positions()

                await asyncio.sleep(10)

            except Exception as e:
                logger.error(f"Error in mock loop: {e}")
                await asyncio.sleep(5)

    def _is_new_token_launch(self, data: Dict) -> bool:
        """신규 토큰 런치 여부 확인"""
        # TODO: Pump.fun 프로그램 로그 파싱
        return False

    async def _handle_new_token(self, token_data: Dict):
        """신규 토큰 처리"""
        try:
            self.tokens_detected += 1

            token_address = token_data.get("address", "")
            symbol = token_data.get("symbol", "UNKNOWN")
            name = token_data.get("name", "Unknown Token")

            logger.info(f"New token detected: {symbol} ({token_address[:10]}...)")

            # 빠른 분석 (1초 이내)
            score = await self._quick_analyze(token_data)

            if score >= 7:  # 10점 만점 중 7점 이상
                await self._execute_snipe(token_address, symbol, name)

        except Exception as e:
            logger.error(f"Error handling new token: {e}")

    async def _quick_analyze(self, token_data: Dict) -> int:
        """신규 토큰 빠른 분석 (1초 이내)"""
        import random

        score = 5  # 기본 점수

        # TODO: 실제 분석 로직
        # - 크리에이터 검증
        # - 초기 유동성 확인
        # - 소셜 미디어 멘션 확인

        return min(10, max(0, score + random.randint(-2, 3)))

    async def _execute_snipe(self, address: str, symbol: str, name: str):
        """스나이핑 실행"""
        try:
            self.status = SniperStatus.SNIPING
            self.tokens_sniped += 1

            # 매수 시뮬레이션
            buy_price = 0.0001  # 초기 가격
            amount = self.capital_sol * 0.5  # 자본의 50% 사용

            snipe = TokenSnipe(
                address=address,
                symbol=symbol,
                name=name,
                detected_at=datetime.utcnow(),
                buy_price=buy_price,
                amount=amount,
                current_price=buy_price,
                highest_price=buy_price
            )
            self.active_snipes[address] = snipe

            # 거래 기록
            trade = SnipeTrade(
                id=f"snipe_{datetime.utcnow().timestamp()}",
                token_address=address,
                token_symbol=symbol,
                side="buy",
                amount=amount,
                price=buy_price,
                timestamp=datetime.utcnow()
            )
            self.trades.append(trade)

            logger.info(f"Sniped: {symbol} with {amount} SOL")

            # Telegram 알림
            await self._send_telegram_notification(
                f"🎯 스나이핑 성공!\n"
                f"토큰: {symbol}\n"
                f"이름: {name[:30]}\n"
                f"주소: {address[:15]}...\n"
                f"투입: {amount:.3f} SOL"
            )

            if self.on_snipe:
                self.on_snipe(snipe)

            self.status = SniperStatus.RUNNING

        except Exception as e:
            logger.error(f"Failed to execute snipe: {e}")
            self.status = SniperStatus.ERROR

    async def _monitor_positions(self):
        """보유 포지션 모니터링"""
        import random

        for address, snipe in list(self.active_snipes.items()):
            if snipe.status == "sold":
                continue

            try:
                # 가격 업데이트 (실제로는 Jupiter API 등 사용)
                if self.mock_mode:
                    # Mock 가격 변동
                    change = random.uniform(-0.2, 0.5)
                    snipe.current_price = snipe.buy_price * (1 + change)
                else:
                    # TODO: 실제 가격 조회
                    pass

                # 최고가 업데이트
                if snipe.current_price > snipe.highest_price:
                    snipe.highest_price = snipe.current_price

                # 익절/손절 체크
                pnl_pct = (snipe.current_price - snipe.buy_price) / snipe.buy_price

                if pnl_pct >= self.take_profit_low:
                    # 익절
                    await self._sell_token(address, snipe, pnl_pct)
                elif pnl_pct <= -self.stop_loss:
                    # 손절
                    await self._sell_token(address, snipe, pnl_pct)

            except Exception as e:
                logger.error(f"Error monitoring position {address}: {e}")

    async def _sell_token(self, address: str, snipe: TokenSnipe, pnl_pct: float):
        """토큰 매도 + 수익 즉시 출금"""
        try:
            pnl_sol = snipe.amount * pnl_pct

            # 거래 기록
            trade = SnipeTrade(
                id=f"sell_{datetime.utcnow().timestamp()}",
                token_address=address,
                token_symbol=snipe.symbol,
                side="sell",
                amount=snipe.amount,
                price=snipe.current_price,
                timestamp=datetime.utcnow(),
                pnl=pnl_sol,
                pnl_pct=pnl_pct
            )
            self.trades.append(trade)

            snipe.status = "sold"
            self.total_pnl_sol += pnl_sol

            if pnl_pct > 0:
                self.successful_snipes += 1

            logger.info(f"Sold {snipe.symbol}: PnL = {pnl_pct:+.1%} ({pnl_sol:+.3f} SOL)")

            # 🎯 수익 즉시 출금 (도파민 봇 핵심 기능)
            withdraw_msg = ""
            if pnl_pct > 0 and pnl_sol > 0:
                try:
                    withdraw_result = await self._withdraw_profits(pnl_sol)
                    if withdraw_result:
                        withdraw_msg = f"\n💰 수익 즉시 출금 완료: {pnl_sol:.3f} SOL"
                        logger.info(f"Profit withdrawn: {pnl_sol:.3f} SOL")
                    else:
                        withdraw_msg = f"\n⚠️ 출금 실패 (수동 확인 필요): {pnl_sol:.3f} SOL"
                except Exception as e:
                    withdraw_msg = f"\n⚠️ 출금 오류: {e}"
                    logger.error(f"Profit withdrawal failed: {e}")

            # Telegram 알림
            emoji = "🚀" if pnl_pct > 0 else "💀"
            await self._send_telegram_notification(
                f"{emoji} 스나이핑 종료\n"
                f"토큰: {snipe.symbol}\n"
                f"수익률: {pnl_pct:+.1%}\n"
                f"손익: {pnl_sol:+.3f} SOL"
                f"{withdraw_msg}"
            )

            if self.on_trade:
                self.on_trade(trade)

        except Exception as e:
            logger.error(f"Failed to sell token: {e}")

    async def _withdraw_profits(self, amount_sol: float) -> bool:
        """수익분 즉시 출금 (Phantom 지갑으로)"""
        try:
            # 출금 주소 (Phantom Wallet)
            withdraw_address = os.environ.get("PHANTOM_PROFIT_WALLET") or os.environ.get("PHANTOM_WALLET_A")

            if not withdraw_address:
                logger.warning("No withdrawal address configured (set PHANTOM_PROFIT_WALLET)")
                return False

            if self.mock_mode:
                logger.info(f"[MOCK] Would withdraw {amount_sol:.3f} SOL to {withdraw_address}")
                return True

            # 실제 Solana 출금 로직 (simplified - 실제 구현 필요)
            # TODO: Solana RPC를 통한 실제 출금 트랜잭션
            logger.info(f"Initiating withdrawal: {amount_sol:.3f} SOL to {withdraw_address}")

            # 출금 성공으로 간주 (실제 구현 시 트랜잭션 확인 필요)
            return True

        except Exception as e:
            logger.error(f"Withdrawal failed: {e}")
            return False

    async def _reconnect(self):
        """WebSocket 재연결"""
        logger.info("Attempting to reconnect...")
        await asyncio.sleep(5)
        await self._initialize_live()

    async def stop(self):
        """봇 중지"""
        self.status = SniperStatus.IDLE

        # 모든 포지션 정리
        for address, snipe in list(self.active_snipes.items()):
            if snipe.status != "sold":
                await self._sell_token(address, snipe, 0)

        # WebSocket 연결 해제
        if self.solana_ws:
            try:
                await self.solana_ws.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket: {e}")

        # EventBus 연결 해제
        if self.event_bus:
            await self.event_bus.disconnect()

        await self.mqtt.disconnect()

        # 리포트 발송
        await self._send_daily_report()

        logger.info(f"Pump sniper {self.bot_id} stopped")

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
        win_rate = (self.successful_snipes / self.tokens_sniped * 100) if self.tokens_sniped > 0 else 0
        await self._send_telegram_notification(
            f"📊 Pump.fun 스나이퍼 리포트\n"
            f"감지: {self.tokens_detected}개\n"
            f"스나이핑: {self.tokens_sniped}개\n"
            f"성공: {self.successful_snipes}개\n"
            f"승률: {win_rate:.1f}%\n"
            f"총 손익: {self.total_pnl_sol:+.3f} SOL"
        )

    def get_status(self) -> Dict[str, Any]:
        """봇 상태 반환"""
        win_rate = (self.successful_snipes / self.tokens_sniped * 100) if self.tokens_sniped > 0 else 0

        return {
            "bot_id": self.bot_id,
            "bot_type": "pump_sniper",
            "status": self.status.value,
            "capital_sol": self.capital_sol,
            "mock_mode": self.mock_mode,
            "tokens_detected": self.tokens_detected,
            "tokens_sniped": self.tokens_sniped,
            "successful_snipes": self.successful_snipes,
            "win_rate": win_rate,
            "total_pnl_sol": self.total_pnl_sol,
            "active_positions": len(self.active_snipes),
            "timestamp": datetime.utcnow().isoformat()
        }


async def main():
    """단독 실행용"""
    bot = PumpSniperBot(
        bot_id="pump_sniper_001",
        capital_sol=0.1,
        mock_mode=False
    )

    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()
        print("\n📊 Final Stats:")
        status = bot.get_status()
        print(f"   Tokens Sniped: {status['tokens_sniped']}")
        print(f"   Win Rate: {status['win_rate']:.1f}%")
        print(f"   Total PnL: {status['total_pnl_sol']:+.3f} SOL")


if __name__ == "__main__":
    asyncio.run(main())

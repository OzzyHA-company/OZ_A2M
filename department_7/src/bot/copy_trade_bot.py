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

# RPC Manager for failover (Alchemy -> Chainstack -> Ankr)
try:
    from shared.rpc_manager import SolanaRPCManager, load_from_env, RPCError
    RPC_MANAGER_AVAILABLE = True
except ImportError:
    RPC_MANAGER_AVAILABLE = False

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
        self._last_telegram_time = None  # Telegram throttle

        # 상태
        self.status = CopyStatus.IDLE
        self.tracked_wallets: Dict[str, TrackedWallet] = {}
        self.active_positions: Dict[str, Dict] = {}
        self.trades: List[CopyTrade] = []
        self.wallet_address: Optional[str] = None

        # API
        # Ant-Colony Nest Integration
        from lib.pi_mono_bridge.ant_colony_adapter import AntColonyAdapter
        self.ant_colony = AntColonyAdapter(config={})
        self.use_ant_colony = True

        # RPC Manager for failover (Alchemy -> Chainstack -> Ankr)
        self.rpc_manager: Optional[Any] = None
        self.use_rpc_manager = RPC_MANAGER_AVAILABLE

        # 중복 거래 필터링
        self._seen_signatures: set = set()

        # MQTT
        mqtt_config = MQTTConfig(host=mqtt_host, port=mqtt_port, client_id=bot_id)
        self.mqtt = MQTTClient(config=mqtt_config)

        # EventBus
        self.event_bus: Optional[EventBus] = None

        # Telegram
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

        # RPC 제공자 설정 (우선순위: Alchemy → Infura → Helius)
        self.alchemy_http_url = os.environ.get("ALCHEMY_SOLANA_HTTP_URL")
        self.infura_http_url = os.environ.get("INFURA_SOLANA_HTTP_URL")
        # Helius URL 수정: api.helius-rpc.com → api.helius.xyz
        self.helius_http_url = os.environ.get("HELIUS_RPC_URL", "").replace("api.helius-rpc.com", "mainnet.helius-rpc.com")
        self.helius_api_key = os.environ.get("HELIUS_API_KEY")
        # Enhanced API는 api.helius.xyz 도메인 사용
        self.helius_parse_url = os.environ.get("HELIUS_PARSE_TX_URL", "https://api.helius.xyz/v0")

        # 통계
        self.total_copies: int = 0
        self.successful_copies: int = 0
        self.total_pnl_sol: float = 0.0

        # 시간 추적
        self.start_time: datetime = datetime.utcnow()
        self.last_trade_time: Optional[datetime] = None
        self.last_copy_time: Optional[datetime] = None
        self.trades_today: int = 0
        self.last_trade_date: Optional[str] = None

        # 콜백
        self.on_copy: Optional[Callable[[CopyTrade], None]] = None
        self.on_trade: Optional[Callable[[CopyTrade], None]] = None

        logger.info(f"GMGNCopyBot {bot_id} initialized (capital={capital_sol} SOL)")

    def _load_wallet(self) -> Optional[str]:
        """.env에서 Phantom 지갑 주소 로드"""
        return os.environ.get("PHANTOM_WALLET_C")

    async def _update_capital_from_wallet(self):
        """실제 Solana 지갑 잔액으로 자본 업데이트"""
        try:
            wallet_address = self._load_wallet()
            if not wallet_address:
                logger.warning("No wallet address configured, using default capital")
                return

            # Solana 주소 유효성 검사 (32-44자 base58)
            if len(wallet_address) < 32 or len(wallet_address) > 44:
                logger.warning(f"Invalid wallet address length: {len(wallet_address)}, using default capital")
                return

            rpc_url = self._get_best_rpc_url()
            if not rpc_url:
                logger.warning("No RPC URL available, using default capital")
                return

            from solana.rpc.async_api import AsyncClient
            from solders.pubkey import Pubkey
            async with AsyncClient(rpc_url) as client:
                # 문자열을 Pubkey 객체로 변환
                pubkey = Pubkey.from_string(wallet_address)
                response = await client.get_balance(pubkey)
                if response.value is not None:
                    balance_sol = response.value / 1e9  # lamports to SOL
                    # 자본을 실제 잔액의 90%로 설정 (수수료 여유)
                    self.capital_sol = min(balance_sol * 0.9, self.capital_sol)
                    logger.info(f"✅ Capital updated from wallet: {self.capital_sol:.3f} SOL (balance: {balance_sol:.3f} SOL)")
                else:
                    logger.warning("Failed to get wallet balance, using default capital")
        except Exception as e:
            logger.warning(f"Failed to update capital from wallet: {e}, using default capital")

    def _get_best_rpc_url(self) -> Optional[str]:
        """최선의 RPC URL 반환 (RPC Manager → Legacy fallback)"""
        # Use RPC Manager if available (auto-failover: Alchemy → Chainstack → Ankr)
        if self.use_rpc_manager and self.rpc_manager:
            primary = self.rpc_manager.get_primary()
            if primary:
                logger.debug(f"Using RPC endpoint: {primary.name}")
                return primary.http_url
            healthy = self.rpc_manager.get_healthy_endpoints()
            if healthy:
                logger.debug(f"Using fallback RPC: {healthy[0].name}")
                return healthy[0].http_url

        # Legacy fallback (환경변수에서 직접 조회)
        if self.alchemy_http_url:
            return self.alchemy_http_url
        if self.infura_http_url:
            return self.infura_http_url
        if self.helius_http_url:
            return self.helius_http_url
        return os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

    def _load_tracked_wallets(self) -> List[str]:
        """추적할 스마트머니 지갑 목록"""
        # 추적 지갑은 환경변수로만 설정 (TRACKED_WALLETS=addr1,addr2,...)
        default_wallets = []

        # 환경변수에서 추적 지갑 로드
        env_wallets = os.environ.get("TRACKED_WALLETS", "")
        if env_wallets:
            default_wallets.extend([w.strip() for w in env_wallets.split(",") if w.strip()])

        return default_wallets

    async def initialize(self):
        """봇 초기화"""
        self.wallet_address = self._load_wallet()

        # Initialize RPC Manager for failover (Alchemy -> Chainstack -> Ankr)
        if self.use_rpc_manager:
            try:
                endpoints = load_from_env()
                if endpoints:
                    self.rpc_manager = SolanaRPCManager(endpoints)
                    await self.rpc_manager.start()
                    logger.info(f"✅ RPC Manager started with {len(endpoints)} endpoints")
                else:
                    logger.warning("⚠️ No RPC endpoints found, using legacy mode")
            except Exception as e:
                logger.error(f"⚠️ RPC Manager init failed: {e}")
                self.use_rpc_manager = False

        # 실제 지갑 잔액으로 자본 업데이트
        await self._update_capital_from_wallet()

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

        if self.mock_mode or not self.helius_parse_url or not self.tracked_wallets:
            if not self.tracked_wallets:
                logger.warning("추적 지갑 없음 — TRACKED_WALLETS 환경변수를 설정하세요. Mock 모드로 전환")
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
        """지갑 거래 내역 조회 - Helius Enhanced Transaction API with RPC failover"""
        if self.mock_mode:
            # Mock 거래 데이터
            import random
            if random.random() < 0.1:  # 10% 확률로 거래 발생
                return [{
                    "signature": f"mock_tx_{random.randint(1000, 9999)}",
                    "token": f"MOCK{random.randint(1, 99)}",
                    "token_address": f"mock_token_{random.randint(1000, 9999)}",
                    "side": "buy" if random.random() > 0.5 else "sell",
                    "amount": random.uniform(0.01, 0.1),
                    "price": random.uniform(0.001, 0.01)
                }]
            return []

        # Try Helius Enhanced API first, then fallback to RPC methods
        import aiohttp

        api_key = self.helius_api_key or os.environ.get("ANT_COLONY_API_KEY")
        if not api_key:
            logger.warning("ANT_COLONY_API_KEY not set, trying RPC fallback")
            return await self._fetch_transactions_via_rpc(wallet_address)

        # Helius Enhanced API 시도 (api.helius.xyz 사용)
        helius_url = f"https://api.helius.xyz/v0/addresses/{wallet_address}/transactions"

        try:
            async with aiohttp.ClientSession() as session:
                params = {"api-key": api_key, "limit": 10}
                async with session.get(helius_url, params=params) as resp:
                    if resp.status == 429:
                        logger.warning("Helius API rate limit exceeded, trying RPC fallback")
                        return await self._fetch_transactions_via_rpc(wallet_address)
                    elif resp.status == 400:
                        body = await resp.text()
                        if "max usage" in body.lower():
                            logger.warning("Helius API quota exhausted, trying RPC fallback")
                            return await self._fetch_transactions_via_rpc(wallet_address)
                        else:
                            logger.warning(f"Helius API error 400: {body[:100]}, trying RPC fallback")
                            return await self._fetch_transactions_via_rpc(wallet_address)
                    elif resp.status != 200:
                        logger.warning(f"Helius API error: {resp.status}, trying RPC fallback")
                        return await self._fetch_transactions_via_rpc(wallet_address)

                    txs = await resp.json()
                    if not isinstance(txs, list):
                        logger.warning(f"Unexpected Helius response format, trying RPC fallback")
                        return await self._fetch_transactions_via_rpc(wallet_address)

                    return self._parse_helius_transactions(txs, wallet_address)

        except Exception as e:
            logger.error(f"Error fetching from Helius: {e}, trying RPC fallback")
            return await self._fetch_transactions_via_rpc(wallet_address)

    async def _fetch_transactions_via_rpc(self, wallet_address: str) -> List[Dict]:
        """RPC를 통한 거래 내역 조회 (Helius 실패 시 fallback)"""
        try:
            from solana.rpc.async_api import AsyncClient

            rpc_url = self._get_best_rpc_url()
            if not rpc_url:
                logger.error("No RPC URL available for fallback")
                return []

            async with AsyncClient(rpc_url) as client:
                # 최근 서명 조회
                response = await client.get_signatures_for_address(
                    wallet_address,
                    limit=10
                )

                if not response.value:
                    return []

                transactions = []
                for sig_info in response.value:
                    # 각 서명에 대한 거래 상세 정보 조회
                    tx_response = await client.get_transaction(
                        sig_info.signature,
                        encoding="jsonParsed"
                    )

                    if tx_response.value:
                        tx_data = tx_response.value
                        # 간단한 거래 정보 추출
                        transactions.append({
                            "signature": sig_info.signature,
                            "token": "UNKNOWN",
                            "token_address": "",
                            "side": "unknown",
                            "amount": 0,
                            "price": 0,
                            "timestamp": tx_data.block_time or 0,
                            "description": "RPC fetched transaction"
                        })

                return transactions

        except Exception as e:
            logger.error(f"RPC fallback also failed: {e}")
            return []

    def _parse_helius_transactions(self, txs: List[Dict], wallet_address: str) -> List[Dict]:
        """Helius 응답 파싱"""
        parsed_txs = []
        for tx in txs:
            # tokenTransfers에서 스왑 정보 추출
            token_transfers = tx.get("tokenTransfers", [])
            native_transfers = tx.get("nativeTransfers", [])

            if token_transfers:
                # 첫 번째 토큰 전송을 기준으로 side 결정
                first_transfer = token_transfers[0]
                from_addr = first_transfer.get("fromUserAccount", "")
                to_addr = first_transfer.get("toUserAccount", "")
                token_addr = first_transfer.get("mint", "")
                amount = first_transfer.get("tokenAmount", 0)

                # side 결정: 추적 지갑이 받으면 buy, 보내면 sell
                side = "buy" if to_addr.lower() == wallet_address.lower() else "sell"

                parsed_txs.append({
                    "signature": tx.get("signature", ""),
                    "token": token_addr[:8] + "..." if len(token_addr) > 8 else token_addr,
                    "token_address": token_addr,
                    "side": side,
                    "amount": float(amount) if amount else 0,
                    "price": 0,  # 가격은 별도 조회 필요
                    "timestamp": tx.get("timestamp", 0),
                    "description": tx.get("description", "")
                })

        return parsed_txs

    def _is_new_trade(self, transaction: Dict) -> bool:
        """새로운 거래 여부 확인 - 중복 필터링"""
        sig = transaction.get("signature", "")
        if not sig:
            return False

        # 이미 본 거래인지 확인
        if sig in self._seen_signatures:
            return False

        # 새로운 거래 기록
        self._seen_signatures.add(sig)

        # 최대 1000개 유지 (메모리 관리)
        if len(self._seen_signatures) > 1000:
            # 가장 오래된 항목 제거 (set이므로 pop)
            self._seen_signatures.pop()

        return True

    async def _copy_trade(self, wallet: TrackedWallet, transaction: Dict):
        """거래 복사 - Jupiter API로 실제 스왑 실행"""
        import aiohttp
        import base64
        from solders.keypair import Keypair
        from solders.transaction import VersionedTransaction
        from solana.rpc.async_api import AsyncClient

        try:
            token_address = transaction.get("token_address", "")
            token_symbol = transaction.get("token", "UNKNOWN")
            side = transaction.get("side", "buy")
            original_amount = transaction.get("amount", 0)

            # 복사 금액 계산
            copy_amount = original_amount * self.copy_percentage
            max_amount = self.capital_sol * self.max_position_pct
            final_amount = min(copy_amount, max_amount)

            if final_amount <= 0 or not token_address:
                return

            # Mock 모드: 거래 기록만
            if self.mock_mode:
                self.total_copies += 1
                copy_time = datetime.utcnow()
                trade = CopyTrade(
                    id=f"copy_{copy_time.timestamp()}",
                    original_wallet=wallet.address,
                    token_address=token_address,
                    token_symbol=token_symbol,
                    side=side,
                    amount=final_amount,
                    price=transaction.get("price", 0),
                    timestamp=copy_time
                )
                self.trades.append(trade)
                self.last_copy_time = copy_time
                self.last_trade_time = copy_time
                self._update_trades_today()
                logger.info(f"[MOCK] Copied trade: {token_symbol} {side} {final_amount} SOL")
                return

            # 실제 Jupiter 스왑 실행
            private_key = os.environ.get("SOLANA_PRIVATE_KEY")
            if not private_key:
                logger.error("SOLANA_PRIVATE_KEY not set")
                return

            keypair = Keypair.from_base58_string(private_key)
            wallet_pubkey = str(keypair.pubkey())

            # Jupiter 스왑 파라미터 설정
            sol_mint = "So11111111111111111111111111111111111111112"
            input_mint = sol_mint if side == "buy" else token_address
            output_mint = token_address if side == "buy" else sol_mint
            amount_lamports = int(final_amount * 1e9)

            async with aiohttp.ClientSession() as session:
                # 1. Quote
                quote_url = "https://lite-api.jup.ag/swap/v1/quote"
                params = {
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": amount_lamports,
                    "slippageBps": 1000,
                    "onlyDirectRoutes": "false"
                }

                async with session.get(quote_url, params=params) as resp:
                    if resp.status != 200:
                        logger.error(f"Jupiter quote failed: {resp.status}")
                        return
                    quote_resp = await resp.json()

                if not quote_resp.get("routePlan"):
                    logger.error("No routes found")
                    return

                # 가격 계산
                in_amt = int(quote_resp.get("inAmount", 1))
                out_amt = int(quote_resp.get("outAmount", 0))
                price = out_amt / in_amt if in_amt > 0 else 0

                # 2. Swap transaction
                swap_url = "https://lite-api.jup.ag/swap/v1/swap"
                swap_payload = {
                    "quoteResponse": quote_resp,
                    "userPublicKey": wallet_pubkey,
                    "wrapAndUnwrapSol": True,
                    "prioritizationFeeLamports": 10000
                }

                async with session.post(swap_url, json=swap_payload) as resp:
                    if resp.status != 200:
                        logger.error(f"Jupiter swap request failed: {resp.status}")
                        return
                    swap_resp = await resp.json()

                swap_tx_b64 = swap_resp.get("swapTransaction")
                if not swap_tx_b64:
                    logger.error("No swap transaction")
                    return

            # 3. Sign and send
            tx_bytes = base64.b64decode(swap_tx_b64)
            tx = VersionedTransaction.from_bytes(tx_bytes)
            signed_tx = VersionedTransaction(tx.message, [keypair])

            rpc_url = self._get_best_rpc_url()
            if not rpc_url:
                logger.error("SOLANA_RPC_URL / HELIUS_RPC_URL not set")
                return

            async with AsyncClient(rpc_url) as client:
                result = await client.send_raw_transaction(bytes(signed_tx))
                signature = result.value
                logger.info(f"Copy trade tx sent: {signature}")

            # 거래 기록
            self.total_copies += 1
            copy_time = datetime.utcnow()
            trade = CopyTrade(
                id=f"copy_{copy_time.timestamp()}",
                original_wallet=wallet.address,
                token_address=token_address,
                token_symbol=token_symbol,
                side=side,
                amount=final_amount,
                price=price,
                timestamp=copy_time
            )
            self.trades.append(trade)
            self.last_copy_time = copy_time
            self.last_trade_time = copy_time
            self._update_trades_today()

            # 포지션 업데이트
            if side == "buy":
                self.active_positions[token_address] = {
                    "token": token_symbol,
                    "amount": final_amount,
                    "entry_price": price,
                    "copied_from": wallet.address
                }
            elif side == "sell" and token_address in self.active_positions:
                position = self.active_positions[token_address]
                entry = position.get("entry_price", price)
                pnl = (price - entry) / entry * final_amount if entry > 0 else 0
                trade.pnl = pnl
                self.total_pnl_sol += pnl

                if pnl > 0:
                    self.successful_copies += 1
                    # 수익 출금
                    try:
                        withdraw_result = await self._withdraw_profits(pnl)
                        if withdraw_result:
                            logger.info(f"Profit withdrawn: {pnl:.3f} SOL")
                    except Exception as e:
                        logger.error(f"Withdrawal failed: {e}")

                del self.active_positions[token_address]

            logger.info(f"Copied trade: {token_symbol} {side} {final_amount} SOL")

            # Telegram 알림
            emoji = "📥" if side == "buy" else "📤"
            await self._send_telegram_notification(
                f"{emoji} 거래 복사\n"
                f"원본: {wallet.label}\n"
                f"토큰: {token_symbol}\n"
                f"방향: {side.upper()}\n"
                f"금액: {final_amount:.3f} SOL"
            )

            if self.on_copy:
                self.on_copy(trade)

        except Exception as e:
            logger.error(f"Failed to copy trade: {e}")

    async def _withdraw_profits(self, amount_sol: float) -> bool:
        """수익분 즉시 출금 (Phantom 지갑으로) - Solana SOL 전송"""
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey
        from solders.system_program import transfer, TransferParams
        from solders.message import MessageV0
        from solders.transaction import VersionedTransaction
        from solana.rpc.async_api import AsyncClient

        try:
            withdraw_address = os.environ.get("PHANTOM_PROFIT_WALLET") or os.environ.get("PHANTOM_WALLET_A")

            if not withdraw_address:
                logger.warning("No withdrawal address configured (set PHANTOM_PROFIT_WALLET)")
                return False

            if self.mock_mode:
                logger.info(f"[MOCK] Would withdraw {amount_sol:.3f} SOL to {withdraw_address}")
                return True

            # Private key 로드
            private_key = os.environ.get("SOLANA_PRIVATE_KEY")
            if not private_key:
                logger.error("SOLANA_PRIVATE_KEY not set")
                return False

            keypair = Keypair.from_base58_string(private_key)

            # Solana RPC 연결
            rpc_url = self._get_best_rpc_url()
            if not rpc_url:
                logger.error("SOLANA_RPC_URL / HELIUS_RPC_URL not set")
                return False

            async with AsyncClient(rpc_url) as client:
                # 최신 blockhash
                bh_resp = await client.get_latest_blockhash()
                blockhash = bh_resp.value.blockhash

                # 전송 instruction
                ix = transfer(
                    TransferParams(
                        from_pubkey=keypair.pubkey(),
                        to_pubkey=Pubkey.from_string(withdraw_address),
                        lamports=int(amount_sol * 1e9)
                    )
                )

                # 트랜잭션 생성 및 서명
                msg = MessageV0.try_compile(
                    keypair.pubkey(),
                    [ix],
                    [],
                    blockhash
                )
                tx = VersionedTransaction(msg, [keypair])

                # 전송
                result = await client.send_raw_transaction(bytes(tx))
                signature = result.value
                logger.info(f"Withdrawal tx sent: {signature}")

                return True

        except Exception as e:
            logger.error(f"Withdrawal failed: {e}")
            return False

    async def _manage_positions(self):
        """포지션 관리"""
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

        # RPC Manager 중지
        if self.rpc_manager:
            try:
                await self.rpc_manager.stop()
                logger.info("RPC Manager stopped")
            except Exception as e:
                logger.error(f"Error stopping RPC Manager: {e}")

        await self.mqtt.disconnect()

        # 리포트 발송
        await self._send_daily_report()

        logger.info(f"GMGN copy bot {self.bot_id} stopped")

    async def _send_telegram_notification(self, message: str):
        """Telegram 알림 발송 (5초 throttle)"""
        if not self.telegram_alerts or not self.telegram_bot_token or not self.telegram_chat_id:
            return

        from datetime import datetime
        now = datetime.utcnow()
        if self._last_telegram_time:
            if (now - self._last_telegram_time).total_seconds() < 5.0:
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
                    if resp.status == 200:
                        self._last_telegram_time = now
                    else:
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
            # 대시보드용 추가 필드
            "start_time": self.start_time.isoformat(),
            "last_trade_time": self.last_trade_time.isoformat() if self.last_trade_time else None,
            "last_copy_time": self.last_copy_time.isoformat() if self.last_copy_time else None,
            "next_trade_time": None,  # 카피봇은 원본 거래 감시 기반
            "trades_today": self.trades_today,
            "extra": {
                "copy_percentage": self.copy_percentage,
                "max_position_pct": self.max_position_pct,
                "tracked_wallet_count": len(self.tracked_wallets),
            },
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

#!/usr/bin/env python3
"""
Jito Shredstream Proxy for OZ_A2M
Data In: Jito Shredstream Docker (localhost gRPC) → Helius RPC WS fallback
QuickNode 완전 대체 — QUICKNODE_WSS_URL 미사용
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class MempoolTransaction:
    """Represents a Solana mempool transaction"""
    signature: str
    slot: int
    timestamp: datetime
    instructions: List[Dict[str, Any]]
    accounts: List[str]
    compute_units: Optional[int] = None
    priority_fee: Optional[int] = None
    source: str = "shredstream"

    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "timestamp": self.timestamp.isoformat(),
        }


class AntColonyScout:
    """
    Scout agent for mempool exploration
    Identifies high-value transactions and opportunities
    """

    def __init__(self, scout_id: str, filters: Optional[List[Callable]] = None):
        self.scout_id = scout_id
        self.filters = filters or []
        self.discovered_opportunities: List[Dict] = []
        self.pheromone_trail: Dict[str, float] = {}

    async def explore(self, tx: MempoolTransaction) -> Optional[Dict]:
        for filter_fn in self.filters:
            if not filter_fn(tx):
                return None

        score = self._score_opportunity(tx)

        if score > 0.7:
            opportunity = {
                "tx_signature": tx.signature,
                "slot": tx.slot,
                "score": score,
                "scout_id": self.scout_id,
                "timestamp": datetime.utcnow().isoformat(),
                "type": self._classify_opportunity(tx),
            }
            self.discovered_opportunities.append(opportunity)
            return opportunity

        return None

    def _score_opportunity(self, tx: MempoolTransaction) -> float:
        score = 0.0

        if tx.priority_fee:
            score += min(tx.priority_fee / 1_000_000, 0.3)

        if tx.compute_units:
            score += min(tx.compute_units / 1_000_000, 0.2)

        score += min(len(tx.instructions) * 0.05, 0.2)

        dex_programs = [
            "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",  # Jupiter
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium
            "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",  # Whirlpool
            "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBymNZFB",  # Pump.fun
        ]

        for ix in tx.instructions:
            if ix.get("program_id") in dex_programs:
                score += 0.3
                break

        return min(score, 1.0)

    def _classify_opportunity(self, tx: MempoolTransaction) -> str:
        for ix in tx.instructions:
            if "swap" in str(ix).lower():
                return "dex_swap"
            elif "liquidate" in str(ix).lower():
                return "liquidation"
            elif "mint" in str(ix).lower():
                return "new_token"
        return "unknown"


class AntColonyWorker:
    """Worker agent for transaction parsing and normalization"""

    def __init__(self, worker_id: str, queue: asyncio.Queue):
        self.worker_id = worker_id
        self.queue = queue
        self.processed_count = 0
        self.output_queue = asyncio.Queue()

    async def process(self):
        while True:
            try:
                tx_data = await self.queue.get()
                if tx_data is None:
                    break

                tx = self._parse_transaction(tx_data)
                await self.output_queue.put(tx)
                self.processed_count += 1

                if self.processed_count % 1000 == 0:
                    logger.info(f"Worker {self.worker_id}: processed {self.processed_count} txs")

            except Exception as e:
                logger.error(f"Worker {self.worker_id} error: {e}")

    def _parse_transaction(self, data: Dict) -> MempoolTransaction:
        return MempoolTransaction(
            signature=data.get("signature", ""),
            slot=data.get("slot", 0),
            timestamp=datetime.utcnow(),
            instructions=data.get("instructions", []),
            accounts=data.get("accounts", []),
            compute_units=data.get("compute_units"),
            priority_fee=data.get("priority_fee"),
            source=data.get("source", "shredstream"),
        )


class AntColonySoldier:
    """Soldier agent for validation and deduplication"""

    def __init__(self, soldier_id: str):
        self.soldier_id = soldier_id
        self.seen_signatures: set = set()
        self.max_cache_size = 10000

    async def validate(self, tx: MempoolTransaction) -> bool:
        if tx.signature in self.seen_signatures:
            return False

        if not tx.signature or not tx.instructions:
            return False

        self.seen_signatures.add(tx.signature)

        if len(self.seen_signatures) > self.max_cache_size:
            self.seen_signatures = set(list(self.seen_signatures)[-self.max_cache_size//2:])

        return True


class JitoShredstreamProxy:
    """
    Jito Shredstream Proxy with Ant-Colony architecture

    Data In 우선순위:
    1. Jito shredstream-proxy Docker (localhost gRPC) — JITO_AUTH_KEYPAIR 설정 시
    2. Helius RPC WebSocket — HELIUS_RPC_URL fallback (QuickNode 대체)
    """

    def __init__(
        self,
        endpoint: str = "localhost",   # 로컬 Jito shredstream-proxy Docker
        port: int = 10000,
        num_scouts: int = 3,
        num_workers: int = 5,
        num_soldiers: int = 2,
    ):
        self.endpoint = endpoint
        self.port = port
        self.num_scouts = num_scouts
        self.num_workers = num_workers
        self.num_soldiers = num_soldiers

        self.raw_tx_queue = asyncio.Queue(maxsize=10000)
        self.parsed_tx_queue = asyncio.Queue(maxsize=10000)
        self.validated_tx_queue = asyncio.Queue(maxsize=10000)
        self.opportunity_queue = asyncio.Queue()

        self.scouts: List[AntColonyScout] = []
        self.workers: List[AntColonyWorker] = []
        self.soldiers: List[AntColonySoldier] = []

        self.running = False
        self.stats = {
            "total_received": 0,
            "total_parsed": 0,
            "total_validated": 0,
            "opportunities_found": 0,
            "data_source": "initializing",
        }

    async def start(self):
        logger.info("Starting Jito Shredstream Proxy with Ant-Colony...")
        self.running = True

        for i in range(self.num_scouts):
            filters = [
                lambda tx: tx.priority_fee is not None and tx.priority_fee > 1000,
            ]
            self.scouts.append(AntColonyScout(f"scout-{i}", filters))

        for i in range(self.num_workers):
            worker = AntColonyWorker(f"worker-{i}", self.raw_tx_queue)
            self.workers.append(worker)
            asyncio.create_task(worker.process())

        for i in range(self.num_soldiers):
            self.soldiers.append(AntColonySoldier(f"soldier-{i}"))

        asyncio.create_task(self._connect_and_receive())
        asyncio.create_task(self._process_parsed_tx())
        asyncio.create_task(self._report_stats())

        logger.info(
            f"Ant-Colony started: {self.num_scouts} scouts, "
            f"{self.num_workers} workers, {self.num_soldiers} soldiers"
        )

    async def stop(self):
        self.running = False
        for _ in self.workers:
            await self.raw_tx_queue.put(None)
        logger.info("Proxy stopped")

    async def _connect_and_receive(self):
        """
        Data In: Jito Shredstream Docker (localhost gRPC) → Helius RPC WS fallback
        QuickNode 완전 미사용
        """
        jito_keypair = os.environ.get("JITO_AUTH_KEYPAIR")
        helius_url = os.environ.get("HELIUS_RPC_URL") or os.environ.get("SOLANA_RPC_URL")

        if jito_keypair:
            logger.info(f"Jito auth keypair detected — connecting to local shredstream-proxy ({self.endpoint}:{self.port})")
            self.stats["data_source"] = "jito_shredstream"
            await self._connect_jito_local_grpc()
        elif helius_url:
            ws_url = helius_url.replace("https://", "wss://").replace("http://", "ws://")
            logger.info(f"Jito Docker 미실행 — Helius RPC WebSocket 사용 (QuickNode 대체): {ws_url[:50]}...")
            self.stats["data_source"] = "helius_rpc_ws"
            await self._connect_helius_ws(ws_url)
        else:
            logger.warning("데이터 소스 없음: JITO_AUTH_KEYPAIR 또는 HELIUS_RPC_URL 설정 필요")
            while self.running:
                await asyncio.sleep(30)

    async def _connect_jito_local_grpc(self):
        """로컬 Jito shredstream-proxy Docker gRPC 연결 (localhost:10000)"""
        try:
            import grpc
            import grpc.aio
        except ImportError:
            logger.warning("grpcio 미설치 — pip3 install grpcio. Helius WS로 전환.")
            helius_url = os.environ.get("HELIUS_RPC_URL", "")
            if helius_url:
                ws_url = helius_url.replace("https://", "wss://")
                await self._connect_helius_ws(ws_url)
            return

        retry_delay = 5
        while self.running:
            try:
                channel = grpc.aio.insecure_channel(f"{self.endpoint}:{self.port}")
                # Docker 컨테이너 준비 대기 (최대 10초)
                await asyncio.wait_for(channel.channel_ready(), timeout=10.0)
                logger.info(f"✅ Jito shredstream-proxy gRPC 연결됨: {self.endpoint}:{self.port}")

                # shredstream.proto subscribe 구현
                # proto stubs: jito-labs/mev-protos/shredstream.proto
                # 현재: 연결 유지 + heartbeat (proto stubs 빌드 후 완성)
                while self.running:
                    await asyncio.sleep(5)

                await channel.close()

            except asyncio.TimeoutError:
                logger.warning(
                    f"Jito shredstream-proxy 미실행 (localhost:{self.port}) — "
                    f"docker compose up 필요. {retry_delay}초 후 재시도..."
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)
            except Exception as e:
                logger.error(f"Jito gRPC 오류: {e}, {retry_delay}초 후 재시도")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

    async def _connect_helius_ws(self, ws_url: str):
        """
        Helius RPC WebSocket → Ant Colony Scout 파이프라인
        Pump.fun / Raydium 프로그램 로그 구독 (QuickNode 완전 대체)
        """
        import websockets

        pump_fun_program = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBymNZFB"
        raydium_program = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

        subscribe_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [
                {"mentions": [pump_fun_program, raydium_program]},
                {"commitment": "processed"}
            ]
        }

        retry_delay = 5
        while self.running:
            try:
                async with websockets.connect(ws_url, ping_interval=30) as ws:
                    await ws.send(json.dumps(subscribe_msg))
                    logger.info("✅ Helius RPC WebSocket 연결됨 → Ant Colony 파이프라인 활성")
                    retry_delay = 5

                    async for raw_msg in ws:
                        if not self.running:
                            break
                        try:
                            data = json.loads(raw_msg)
                            value = data.get("params", {}).get("result", {}).get("value", {})
                            if value and value.get("logs"):
                                tx_data = {
                                    "signature": value.get("signature", ""),
                                    "slot": value.get("context", {}).get("slot", 0),
                                    "instructions": [{"log": l} for l in value.get("logs", [])],
                                    "accounts": value.get("accountKeys", []),
                                    "priority_fee": 10000,
                                    "source": "helius_ws",
                                }
                                await self.raw_tx_queue.put(tx_data)
                                self.stats["total_received"] += 1
                        except Exception as e:
                            logger.debug(f"Parse error: {e}")

            except Exception as e:
                logger.error(f"Helius WS 오류: {e}, {retry_delay}초 후 재시도")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

    async def _process_parsed_tx(self):
        """Process parsed transactions through scouts and soldiers"""
        while self.running:
            try:
                tx = await self.parsed_tx_queue.get()

                valid = True
                for soldier in self.soldiers:
                    if not await soldier.validate(tx):
                        valid = False
                        break

                if valid:
                    self.stats["total_validated"] += 1
                    await self.validated_tx_queue.put(tx)

                    for scout in self.scouts:
                        opportunity = await scout.explore(tx)
                        if opportunity:
                            self.stats["opportunities_found"] += 1
                            await self.opportunity_queue.put(opportunity)

            except Exception as e:
                logger.error(f"Processing error: {e}")

    async def _report_stats(self):
        while self.running:
            await asyncio.sleep(60)
            logger.info(f"Stats: {self.stats}")

    def get_validated_tx(self) -> Optional[MempoolTransaction]:
        try:
            return self.validated_tx_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def get_opportunity(self) -> Optional[Dict]:
        try:
            return self.opportunity_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None


async def main():
    """Test the proxy"""
    proxy = JitoShredstreamProxy()

    try:
        await proxy.start()
        await asyncio.sleep(60)
    except KeyboardInterrupt:
        logger.info("Stopping...")
    finally:
        await proxy.stop()


if __name__ == "__main__":
    asyncio.run(main())

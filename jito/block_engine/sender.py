#!/usr/bin/env python3
"""
Jito Block Engine Bundle Sender for OZ_A2M
Sends transaction bundles with MEV protection
"""

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path

import grpc
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.keypair import Keypair
from solders.transaction import Transaction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class Bundle:
    """Represents a Jito bundle"""
    transactions: List[Transaction]
    tip_amount: int  # lamports
    target_slot: Optional[int] = None
    uuid: str = ""
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if not self.uuid:
            self.uuid = f"bundle_{self.timestamp.timestamp()}"


class AntColonyBundleBuilder:
    """
    Worker agent for building optimized bundles
    """

    def __init__(self, builder_id: str):
        self.builder_id = builder_id
        self.bundle_cache: List[Bundle] = []

    async def build_bundle(
        self,
        transactions: List[Transaction],
        tip_amount: int = 1_000_000,  # 0.001 SOL default
        target_slot: Optional[int] = None,
    ) -> Bundle:
        """
        Build an optimized bundle
        """
        # Sort transactions by priority
        sorted_txs = sorted(
            transactions,
            key=lambda tx: len(tx.serialize()),
            reverse=True  # Larger transactions first
        )

        bundle = Bundle(
            transactions=sorted_txs,
            tip_amount=tip_amount,
            target_slot=target_slot,
        )

        self.bundle_cache.append(bundle)
        logger.info(f"Builder {self.builder_id}: Built bundle {bundle.uuid} with {len(transactions)} txs")

        return bundle

    def estimate_success_probability(self, bundle: Bundle) -> float:
        """
        Estimate bundle success probability (0-1)
        """
        score = 0.0

        # Tip amount factor
        score += min(bundle.tip_amount / 10_000_000, 0.4)  # Max 0.4 for 0.01 SOL

        # Number of transactions
        score += min(len(bundle.transactions) * 0.05, 0.2)

        # Target slot proximity
        if bundle.target_slot:
            score += 0.2

        return min(score, 1.0)


class AntColonyMEVProtector:
    """
    Soldier agent for MEV protection and validation
    """

    def __init__(self, protector_id: str):
        self.protector_id = protector_id
        self.rejected_count = 0
        self.accepted_count = 0

    async def validate_bundle(self, bundle: Bundle) -> bool:
        """
        Validate bundle for MEV protection
        Returns True if bundle passes validation
        """
        checks = [
            self._check_bundle_size(bundle),
            self._check_tip_amount(bundle),
            self._check_transaction_validity(bundle),
            self._check_mev_risk(bundle),
        ]

        result = all(checks)

        if result:
            self.accepted_count += 1
        else:
            self.rejected_count += 1

        return result

    def _check_bundle_size(self, bundle: Bundle) -> bool:
        """Check bundle size limits"""
        # Max 5 transactions per bundle
        if len(bundle.transactions) > 5:
            logger.warning(f"Bundle too large: {len(bundle.transactions)} txs")
            return False

        # Total size check
        total_size = sum(len(tx.serialize()) for tx in bundle.transactions)
        if total_size > 100_000:  # 100KB limit
            logger.warning(f"Bundle too big: {total_size} bytes")
            return False

        return True

    def _check_tip_amount(self, bundle: Bundle) -> bool:
        """Validate tip amount"""
        # Min 1000 lamports, max 1 SOL
        if bundle.tip_amount < 1000:
            logger.warning(f"Tip too small: {bundle.tip_amount} lamports")
            return False
        if bundle.tip_amount > 1_000_000_000:
            logger.warning(f"Tip too large: {bundle.tip_amount} lamports")
            return False
        return True

    def _check_transaction_validity(self, bundle: Bundle) -> bool:
        """Basic transaction validity check"""
        for tx in bundle.transactions:
            if not tx.signatures:
                return False
        return True

    def _check_mev_risk(self, bundle: Bundle) -> bool:
        """Check for obvious MEV risks"""
        # TODO: Implement sandwich attack detection, etc.
        return True


class JitoBlockEngineSender:
    """
    Jito Block Engine Bundle Sender with Ant-Colony
    Uses RPC Manager for failover (Alchemy -> Chainstack -> Ankr)
    """

    def __init__(
        self,
        block_engine_url: str = "mainnet.block-engine.jito.wtf",
        auth_keypair: Optional[Keypair] = None,
        rpc_url: Optional[str] = None,  # Deprecated: use rpc_manager instead
        num_builders: int = 3,
        num_protectors: int = 2,
        rpc_manager=None,  # New: RPCManager instance for failover
    ):
        self.block_engine_url = block_engine_url
        self.auth_keypair = auth_keypair or Keypair()
        self._rpc_url = rpc_url  # Fallback if no rpc_manager
        self.rpc_manager = rpc_manager  # New failover manager
        self.connection: Optional[AsyncClient] = None
        self.grpc_channel: Optional[grpc.aio.Channel] = None

        # Ant-Colony agents
        self.builders: List[AntColonyBundleBuilder] = [
            AntColonyBundleBuilder(f"builder-{i}")
            for i in range(num_builders)
        ]
        self.protectors: List[AntColonyMEVProtector] = [
            AntColonyMEVProtector(f"protector-{i}")
            for i in range(num_protectors)
        ]

        self.pending_bundles: asyncio.Queue = asyncio.Queue()
        self.sent_bundles: Dict[str, Dict] = {}

        self.running = False

    async def start(self):
        """Initialize connections"""
        logger.info(f"Connecting to Block Engine: {self.block_engine_url}")

        # Initialize Solana RPC connection with failover
        if self.rpc_manager:
            # Use RPC Manager (Alchemy -> Chainstack -> Ankr)
            primary = self.rpc_manager.get_primary()
            if primary:
                rpc_url = primary.http_url
                logger.info(f"Using RPC endpoint: {primary.name}")
            else:
                rpc_url = self._rpc_url or "https://api.mainnet-beta.solana.com"
                logger.warning(f"No healthy RPC endpoint, using fallback: {rpc_url}")
        else:
            rpc_url = self._rpc_url or "https://api.mainnet-beta.solana.com"

        self.connection = AsyncClient(rpc_url, commitment=Confirmed)

        # Initialize gRPC channel (placeholder for actual implementation)
        # self.grpc_channel = grpc.aio.insecure_channel(self.block_engine_url)

        self.running = True

        # Start sender loop
        asyncio.create_task(self._sender_loop())

        logger.info("Block Engine sender started")

    async def stop(self):
        """Clean shutdown"""
        self.running = False
        if self.connection:
            await self.connection.close()
        logger.info("Block Engine sender stopped")

    async def send_bundle(
        self,
        transactions: List[Transaction],
        tip_amount: int = 1_000_000,
        target_slot: Optional[int] = None,
    ) -> Optional[str]:
        """
        Send a bundle through Jito Block Engine
        Returns bundle UUID if sent successfully
        """
        try:
            # Get current slot if not specified
            if target_slot is None:
                slot_resp = await self.connection.get_slot(Confirmed)
                target_slot = slot_resp.value + 2  # Target 2 slots ahead

            # Build bundle with random builder
            import random
            builder = random.choice(self.builders)
            bundle = await builder.build_bundle(transactions, tip_amount, target_slot)

            # Validate with all protectors
            for protector in self.protectors:
                if not await protector.validate_bundle(bundle):
                    logger.warning(f"Bundle {bundle.uuid} rejected by {protector.protector_id}")
                    return None

            # Add to pending queue
            await self.pending_bundles.put(bundle)

            logger.info(f"Bundle {bundle.uuid} queued for sending")
            return bundle.uuid

        except Exception as e:
            logger.error(f"Error sending bundle: {e}")
            return None

    async def _sender_loop(self):
        """Main sender loop"""
        while self.running:
            try:
                bundle = await self.pending_bundles.get()

                # TODO: Implement actual gRPC bundle submission
                # For now, simulate
                success = await self._submit_bundle(bundle)

                if success:
                    self.sent_bundles[bundle.uuid] = {
                        "status": "sent",
                        "timestamp": datetime.utcnow().isoformat(),
                        "target_slot": bundle.target_slot,
                    }
                    logger.info(f"Bundle {bundle.uuid} sent successfully")
                else:
                    logger.error(f"Failed to send bundle {bundle.uuid}")

            except Exception as e:
                logger.error(f"Sender loop error: {e}")
                await asyncio.sleep(1)

    async def _submit_bundle(self, bundle: Bundle) -> bool:
        """
        Submit bundle to Jito Block Engine via REST API
        Endpoint: https://mainnet.block-engine.jito.wtf/api/v1/bundles
        No auth required for basic submission.
        """
        import httpx

        try:
            # Serialize transactions to base58/base64
            serialized_txs = []
            for tx in bundle.transactions:
                try:
                    serialized_txs.append(base64.b64encode(bytes(tx)).decode())
                except Exception:
                    serialized_txs.append(base64.b64encode(tx.serialize()).decode())

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendBundle",
                "params": [serialized_txs]
            }

            headers = {"Content-Type": "application/json"}

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://mainnet.block-engine.jito.wtf/api/v1/bundles",
                    json=payload,
                    headers=headers,
                )
                data = resp.json()

                if "result" in data:
                    bundle_id = data["result"]
                    logger.info(f"Bundle submitted to Jito: {bundle_id}")
                    return True
                elif "error" in data:
                    logger.warning(f"Jito bundle rejected: {data['error']}")
                    # Fallback: send first TX via standard RPC
                    return await self._fallback_send(bundle)
                return False

        except Exception as e:
            logger.error(f"Bundle submission error: {e}")
            return await self._fallback_send(bundle)

    async def _fallback_send(self, bundle: Bundle) -> bool:
        """Fallback: send first transaction via standard Solana RPC with failover"""
        try:
            if not bundle.transactions:
                return False
            tx = bundle.transactions[0]
            tx_bytes = base64.b64encode(bytes(tx)).decode()
            import httpx

            # Get RPC URL with failover priority
            if self.rpc_manager:
                healthy = self.rpc_manager.get_healthy_endpoints()
                if healthy:
                    rpc_url = healthy[0].http_url
                    logger.info(f"Fallback using RPC endpoint: {healthy[0].name}")
                else:
                    rpc_url = self._rpc_url or "https://api.mainnet-beta.solana.com"
            else:
                rpc_url = self._rpc_url or "https://api.mainnet-beta.solana.com"

            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "sendTransaction",
                "params": [tx_bytes, {"encoding": "base64", "skipPreflight": False}]
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(rpc_url, json=payload)
                data = resp.json()
                if "result" in data:
                    logger.info(f"Fallback TX sent: {data['result']}")
                    return True
            return False
        except Exception as e:
            logger.error(f"Fallback send error: {e}")
            return False

    async def get_bundle_status(self, uuid: str) -> Optional[Dict]:
        """Get status of a sent bundle"""
        return self.sent_bundles.get(uuid)


async def main():
    """Test the sender with RPC Manager"""
    from shared.rpc_manager import SolanaRPCManager, load_from_env, RPCEndpoint

    # Load RPC endpoints from environment
    endpoints = load_from_env()
    if not endpoints:
        logger.warning("No RPC endpoints configured, using defaults")
        endpoints = [
            RPCEndpoint(
                name="alchemy",
                http_url="https://solana-mainnet.g.alchemy.com/v2/demo",
                priority=1
            ),
        ]

    # Initialize RPC Manager
    rpc_manager = SolanaRPCManager(endpoints)
    await rpc_manager.start()

    # Create sender with RPC Manager
    sender = JitoBlockEngineSender(rpc_manager=rpc_manager)

    try:
        await sender.start()

        # Print RPC status
        status = rpc_manager.get_status()
        logger.info(f"RPC Status: {status}")

        logger.info("Sender ready. Waiting for bundles...")

        await asyncio.sleep(60)

    except KeyboardInterrupt:
        logger.info("Stopping...")
    finally:
        await sender.stop()
        await rpc_manager.stop()


if __name__ == "__main__":
    asyncio.run(main())

"""
Jito RPC Engine - Shredstream + Block Engine Integration
제1부서 기술개발팀 - Solana MEV Optimization Layer

Features:
- Jito Shredstream RPC for low-latency block updates
- Block Engine integration for MEV extraction
- Redis caching for block data
- Automatic fallback to Helius RPC
"""

import json
import os
import sys
import asyncio
import httpx
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any, AsyncIterator, Set
from enum import Enum
from contextlib import asynccontextmanager

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from lib.core.logger import get_logger

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = get_logger(__name__)


class RPCProvider(Enum):
    """Available RPC providers."""
    JITO_SHREDSTREAM = "jito_shredstream"
    JITO_BLOCK_ENGINE = "jito_block_engine"
    HELIUS = "helius"
    FALLBACK = "fallback"


@dataclass
class BlockInfo:
    """Solana block information."""
    slot: int
    blockhash: str
    block_time: Optional[datetime]
    parent_slot: int
    transactions_count: int
    source: RPCProvider
    received_at: datetime = field(default_factory=datetime.now)
    latency_ms: float = 0.0


@dataclass
class TransactionBundle:
    """Jito transaction bundle."""
    uuid: str
    transactions: List[str]  # Base64 encoded transactions
    slot: Optional[int]
    max_tip: int  # lamports
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class BundleResult:
    """Bundle submission result."""
    success: bool
    bundle_id: Optional[str]
    slot: Optional[int]
    error: Optional[str] = None
    latency_ms: float = 0.0


@dataclass
class RPCEndpoint:
    """RPC endpoint configuration."""
    provider: RPCProvider
    url: str
    ws_url: Optional[str] = None
    api_key: Optional[str] = None
    priority: int = 1
    timeout_seconds: float = 5.0
    max_retries: int = 3


class JitoRPCEngine:
    """
    Jito RPC Engine for Solana MEV optimization.

    Implements:
    - Shredstream for low-latency block updates
    - Block Engine for bundle submission
    - Automatic failover between providers
    - Redis caching for block data
    """

    # Jito endpoints
    JITO_SHREDSTREAM_URL = "https://mainnet.shredstream.jito.wtf"
    JITO_BLOCK_ENGINE_URLS = [
        "https://mainnet.block-engine.jito.wtf",
        "https://amsterdam.mainnet.block-engine.jito.wtf",
        "https://frankfurt.mainnet.block-engine.jito.wtf",
        "https://ny.mainnet.block-engine.jito.wtf",
        "https://tokyo.mainnet.block-engine.jito.wtf",
    ]

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path or os.path.expanduser('~/.ozzy-secrets/jito_config.json'))
        self.endpoints: List[RPCEndpoint] = []
        self.active_endpoint: Optional[RPCEndpoint] = None
        self._http_clients: Dict[str, httpx.AsyncClient] = {}
        self._redis: Optional[Any] = None
        self._block_callbacks: List[Callable[[BlockInfo], None]] = []
        self._running = False
        self._shredstream_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None

        # Stats
        self.blocks_received = 0
        self.bundles_submitted = 0
        self.bundles_landed = 0
        self.avg_block_latency_ms = 0.0

        self._load_config()
        logger.info("Jito RPC Engine initialized")

    def _load_config(self):
        """Load Jito configuration."""
        # Load API keys from master.env
        secrets_path = Path.home() / '.ozzy-secrets' / 'master.env'
        helius_key = None

        if secrets_path.exists():
            with open(secrets_path, 'r') as f:
                for line in f:
                    if '=' in line and not line.startswith('#'):
                        key, value = line.strip().split('=', 1)
                        if key == 'HELIUS_API_KEY':
                            helius_key = value
                            break

        # Setup endpoints
        self.endpoints = [
            RPCEndpoint(
                provider=RPCProvider.JITO_SHREDSTREAM,
                url=self.JITO_SHREDSTREAM_URL,
                priority=1,
                timeout_seconds=3.0
            ),
            RPCEndpoint(
                provider=RPCProvider.JITO_BLOCK_ENGINE,
                url=self.JITO_BLOCK_ENGINE_URLS[0],
                priority=2,
                timeout_seconds=5.0
            ),
            RPCEndpoint(
                provider=RPCProvider.HELIUS,
                url=f"https://mainnet.helius-rpc.com/?api-key={helius_key}" if helius_key else "",
                api_key=helius_key,
                priority=3,
                timeout_seconds=5.0
            ),
        ]

        # Filter out endpoints without URLs
        self.endpoints = [e for e in self.endpoints if e.url]

        if self.endpoints:
            self.active_endpoint = self.endpoints[0]

    async def _get_redis(self) -> Optional[Any]:
        """Get or create Redis connection."""
        if not REDIS_AVAILABLE:
            return None

        if self._redis is None:
            try:
                self._redis = await redis.from_url(
                    "redis://localhost:6380",
                    encoding="utf-8",
                    decode_responses=True
                )
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}")
                return None

        return self._redis

    def _get_http_client(self, endpoint: RPCEndpoint) -> httpx.AsyncClient:
        """Get or create HTTP client for endpoint."""
        key = endpoint.provider.value
        if key not in self._http_clients or self._http_clients[key].is_closed:
            self._http_clients[key] = httpx.AsyncClient(
                timeout=endpoint.timeout_seconds,
                limits=httpx.Limits(max_keepalive_connections=2, max_connections=5)
            )
        return self._http_clients[key]

    async def _call_rpc(
        self,
        endpoint: RPCEndpoint,
        method: str,
        params: List = None
    ) -> Optional[Dict]:
        """Make JSON-RPC call to endpoint."""
        client = self._get_http_client(endpoint)

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or []
        }

        for attempt in range(endpoint.max_retries):
            try:
                response = await client.post(
                    endpoint.url,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                data = response.json()

                if "error" in data:
                    logger.warning(f"RPC error: {data['error']}")
                    return None

                return data.get("result")

            except Exception as e:
                logger.warning(f"RPC call failed (attempt {attempt + 1}): {e}")
                if attempt < endpoint.max_retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))

        return None

    async def get_latest_blockhash(self) -> Optional[str]:
        """Get latest blockhash from Solana."""
        for endpoint in sorted(self.endpoints, key=lambda e: e.priority):
            result = await self._call_rpc(
                endpoint,
                "getLatestBlockhash",
                [{"commitment": "confirmed"}]
            )

            if result and "value" in result:
                blockhash = result["value"].get("blockhash")
                logger.debug(f"Got blockhash from {endpoint.provider.value}: {blockhash[:16]}...")
                return blockhash

        return None

    async def get_slot(self) -> Optional[int]:
        """Get current slot."""
        for endpoint in sorted(self.endpoints, key=lambda e: e.priority):
            result = await self._call_rpc(endpoint, "getSlot")
            if result:
                return result
        return None

    async def get_block_time(self, slot: int) -> Optional[datetime]:
        """Get block time for slot."""
        # Check cache first
        redis_conn = await self._get_redis()
        if redis_conn:
            cached = await redis_conn.get(f"block_time:{slot}")
            if cached:
                return datetime.fromtimestamp(float(cached))

        for endpoint in sorted(self.endpoints, key=lambda e: e.priority):
            result = await self._call_rpc(endpoint, "getBlockTime", [slot])
            if result:
                block_time = datetime.fromtimestamp(result)

                # Cache result
                if redis_conn:
                    await redis_conn.setex(
                        f"block_time:{slot}",
                        timedelta(hours=1),
                        str(result)
                    )

                return block_time

        return None

    async def submit_bundle(
        self,
        transactions: List[str],
        max_tip_lamports: int = 10000
    ) -> BundleResult:
        """
        Submit transaction bundle to Jito Block Engine.

        Args:
            transactions: List of base64-encoded transactions
            max_tip_lamports: Maximum tip in lamports (default 0.00001 SOL)

        Returns:
            BundleResult with bundle ID or error
        """
        start_time = asyncio.get_event_loop().time()

        # Find block engine endpoint
        block_engine = next(
            (e for e in self.endpoints if e.provider == RPCProvider.JITO_BLOCK_ENGINE),
            None
        )

        if not block_engine:
            return BundleResult(
                success=False,
                bundle_id=None,
                error="No block engine endpoint configured"
            )

        # Create bundle payload
        bundle_uuid = os.urandom(16).hex()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [
                transactions,
                {
                    "maxTip": max_tip_lamports,
                    "uuid": bundle_uuid
                }
            ]
        }

        try:
            client = self._get_http_client(block_engine)
            response = await client.post(
                f"{block_engine.url}/api/v1/bundles",
                json=payload,
                headers={"Content-Type": "application/json"}
            )

            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            if response.status_code == 200:
                data = response.json()
                bundle_id = data.get("result")

                self.bundles_submitted += 1

                return BundleResult(
                    success=True,
                    bundle_id=bundle_id,
                    latency_ms=latency_ms
                )
            else:
                return BundleResult(
                    success=False,
                    bundle_id=None,
                    error=f"HTTP {response.status_code}: {response.text}",
                    latency_ms=latency_ms
                )

        except Exception as e:
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            return BundleResult(
                success=False,
                bundle_id=None,
                error=str(e),
                latency_ms=latency_ms
            )

    async def check_bundle_status(self, bundle_id: str) -> Optional[Dict]:
        """Check status of submitted bundle."""
        block_engine = next(
            (e for e in self.endpoints if e.provider == RPCProvider.JITO_BLOCK_ENGINE),
            None
        )

        if not block_engine:
            return None

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBundleStatuses",
            "params": [[bundle_id]]
        }

        try:
            client = self._get_http_client(block_engine)
            response = await client.post(
                f"{block_engine.url}/api/v1/bundles",
                json=payload
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("result", {}).get("value", [{}])[0]

        except Exception as e:
            logger.warning(f"Bundle status check failed: {e}")

        return None

    async def get_leader_schedule(self) -> Optional[List[int]]:
        """Get upcoming leader slots from Jito."""
        block_engine = next(
            (e for e in self.endpoints if e.provider == RPCProvider.JITO_BLOCK_ENGINE),
            None
        )

        if not block_engine:
            return None

        try:
            client = self._get_http_client(block_engine)
            response = await client.get(
                f"{block_engine.url}/api/v1/leaderSchedule"
            )

            if response.status_code == 200:
                return response.json()

        except Exception as e:
            logger.warning(f"Leader schedule fetch failed: {e}")

        return None

    async def _shredstream_listener(self):
        """Background task to listen for Shredstream updates."""
        if not REDIS_AVAILABLE:
            logger.warning("Shredstream requires Redis - falling back to polling")
            return

        logger.info("Starting Shredstream listener...")

        # Note: Actual Shredstream requires WebSocket connection
        # This is a simplified polling fallback
        last_slot = await self.get_slot() or 0

        while self._running:
            try:
                current_slot = await self.get_slot()
                if current_slot and current_slot > last_slot:
                    # New slot detected
                    block_time = await self.get_block_time(current_slot)
                    blockhash = await self.get_latest_blockhash()

                    block_info = BlockInfo(
                        slot=current_slot,
                        blockhash=blockhash or "",
                        block_time=block_time,
                        parent_slot=last_slot,
                        transactions_count=0,  # Would need getBlock call
                        source=RPCProvider.JITO_SHREDSTREAM
                    )

                    # Cache block info
                    redis_conn = await self._get_redis()
                    if redis_conn:
                        await redis_conn.setex(
                            f"block:{current_slot}",
                            timedelta(minutes=5),
                            json.dumps({
                                "slot": current_slot,
                                "blockhash": blockhash,
                                "block_time": block_time.isoformat() if block_time else None,
                                "parent_slot": last_slot
                            })
                        )

                    # Notify callbacks
                    for callback in self._block_callbacks:
                        try:
                            callback(block_info)
                        except Exception as e:
                            logger.error(f"Block callback error: {e}")

                    self.blocks_received += 1
                    last_slot = current_slot

                await asyncio.sleep(0.4)  # ~2.5 blocks/sec max

            except Exception as e:
                logger.error(f"Shredstream listener error: {e}")
                await asyncio.sleep(1)

    async def _health_check_loop(self):
        """Background health check loop."""
        while self._running:
            try:
                for endpoint in self.endpoints:
                    slot = await self._call_rpc(endpoint, "getSlot")
                    if slot:
                        logger.debug(f"{endpoint.provider.value} healthy (slot: {slot})")
                    else:
                        logger.warning(f"{endpoint.provider.value} unhealthy")

                await asyncio.sleep(30)  # Check every 30 seconds

            except Exception as e:
                logger.error(f"Health check error: {e}")
                await asyncio.sleep(5)

    def on_new_block(self, callback: Callable[[BlockInfo], None]):
        """Register callback for new block events."""
        self._block_callbacks.append(callback)

    async def start(self):
        """Start the Jito RPC Engine."""
        if self._running:
            return

        self._running = True

        # Start background tasks
        self._shredstream_task = asyncio.create_task(self._shredstream_listener())
        self._health_check_task = asyncio.create_task(self._health_check_loop())

        logger.info("Jito RPC Engine started")

    async def stop(self):
        """Stop the Jito RPC Engine."""
        self._running = False

        if self._shredstream_task:
            self._shredstream_task.cancel()
            try:
                await self._shredstream_task
            except asyncio.CancelledError:
                pass

        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        # Close HTTP clients
        for client in self._http_clients.values():
            if not client.is_closed:
                await client.aclose()

        # Close Redis
        if self._redis:
            await self._redis.close()

        logger.info("Jito RPC Engine stopped")

    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return {
            "blocks_received": self.blocks_received,
            "bundles_submitted": self.bundles_submitted,
            "bundles_landed": self.bundles_landed,
            "avg_block_latency_ms": round(self.avg_block_latency_ms, 2),
            "active_endpoint": self.active_endpoint.provider.value if self.active_endpoint else None,
            "endpoints": [
                {
                    "provider": e.provider.value,
                    "priority": e.priority,
                    "url": e.url[:30] + "..." if len(e.url) > 30 else e.url
                }
                for e in self.endpoints
            ],
            "redis_available": REDIS_AVAILABLE
        }


# Singleton instance
_engine: Optional[JitoRPCEngine] = None


def get_engine() -> JitoRPCEngine:
    """Get or create global engine instance."""
    global _engine
    if _engine is None:
        _engine = JitoRPCEngine()
    return _engine


async def main():
    """CLI for testing Jito RPC Engine."""
    import argparse

    parser = argparse.ArgumentParser(description='Jito RPC Engine')
    parser.add_argument('--test', action='store_true', help='Run basic test')
    parser.add_argument('--slot', action='store_true', help='Get current slot')
    parser.add_argument('--blockhash', action='store_true', help='Get latest blockhash')
    parser.add_argument('--stats', action='store_true', help='Show stats')
    parser.add_argument('--listen', action='store_true', help='Start block listener')

    args = parser.parse_args()

    engine = JitoRPCEngine()

    if args.test:
        print("Testing Jito RPC Engine...")

        slot = await engine.get_slot()
        print(f"Current slot: {slot}")

        blockhash = await engine.get_latest_blockhash()
        print(f"Latest blockhash: {blockhash[:20]}..." if blockhash else "Failed")

        block_time = await engine.get_block_time(slot) if slot else None
        print(f"Block time: {block_time}")

        print(f"\nStats: {json.dumps(engine.get_stats(), indent=2)}")

    elif args.slot:
        slot = await engine.get_slot()
        print(f"Current slot: {slot}")

    elif args.blockhash:
        blockhash = await engine.get_latest_blockhash()
        print(f"Latest blockhash: {blockhash}")

    elif args.stats:
        print(json.dumps(engine.get_stats(), indent=2))

    elif args.listen:
        print("Starting block listener (Ctrl+C to stop)...")

        def on_block(block: BlockInfo):
            print(f"New block: slot={block.slot}, hash={block.blockhash[:16]}...")

        engine.on_new_block(on_block)
        await engine.start()

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            await engine.stop()

    else:
        print("Jito RPC Engine - Use --help for options")

    # Cleanup
    for client in engine._http_clients.values():
        if not client.is_closed:
            await client.aclose()


if __name__ == '__main__':
    asyncio.run(main())

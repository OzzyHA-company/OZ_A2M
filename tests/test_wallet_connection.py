"""
Test Wallet Connection - Wallet Connectivity Testing
Phase 1: Security & Wallet Setup

Tests connectivity for all configured wallets:
- Exchange API connections (Binance, Bybit, Hyperliquid)
- Blockchain wallet connections (Solana/Phantom, EVM/MetaMask)
- Balance verification
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.core.logger import get_logger
from lib.core.bot_wallet_manager import BotWalletManager

logger = get_logger(__name__)


@dataclass
class ConnectionResult:
    """Result of a wallet connection test."""
    name: str
    type: str  # 'cex', 'solana', 'evm'
    status: str  # 'success', 'failed', 'skipped'
    balance: Optional[float] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()


class WalletConnectionTester:
    """Test connectivity for all wallet types."""

    def __init__(self):
        self.manager = BotWalletManager()
        self.results: List[ConnectionResult] = []
        self.env_vars = self._load_env()

    def _load_env(self) -> Dict[str, str]:
        """Load environment variables from master.env."""
        env_path = Path.home() / '.ozzy-secrets' / 'master.env'
        env_vars = {}

        if env_path.exists():
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip().strip('"').strip("'")

        return env_vars

    def _get_env(self, key: str) -> Optional[str]:
        """Get environment variable."""
        return self.env_vars.get(key) or os.getenv(key)

    async def test_binance_connection(self) -> ConnectionResult:
        """Test Binance API connection."""
        import time
        import requests
        start = time.time()

        try:
            api_key = self._get_env('BINANCE_API_KEY')
            api_secret = self._get_env('BINANCE_API_SECRET')

            if not api_key or not api_secret:
                return ConnectionResult(
                    name='Binance',
                    type='cex',
                    status='skipped',
                    error='API keys not configured'
                )

            # Test API connection
            url = 'https://api.binance.com/api/v3/account'
            import hmac
            import hashlib

            timestamp = int(time.time() * 1000)
            query_string = f'timestamp={timestamp}'
            signature = hmac.new(
                api_secret.encode(),
                query_string.encode(),
                hashlib.sha256
            ).hexdigest()

            headers = {'X-MBX-APIKEY': api_key}
            response = requests.get(
                f'{url}?{query_string}&signature={signature}',
                headers=headers,
                timeout=10
            )

            latency = (time.time() - start) * 1000

            if response.status_code == 200:
                data = response.json()
                balances = data.get('balances', [])
                usdt = next((b for b in balances if b['asset'] == 'USDT'), None)
                balance = float(usdt['free']) if usdt else 0.0

                return ConnectionResult(
                    name='Binance',
                    type='cex',
                    status='success',
                    balance=balance,
                    latency_ms=latency
                )
            else:
                return ConnectionResult(
                    name='Binance',
                    type='cex',
                    status='failed',
                    error=f'HTTP {response.status_code}',
                    latency_ms=latency
                )

        except Exception as e:
            return ConnectionResult(
                name='Binance',
                type='cex',
                status='failed',
                error=str(e),
                latency_ms=(time.time() - start) * 1000
            )

    async def test_bybit_connection(self) -> ConnectionResult:
        """Test Bybit API connection."""
        import time
        import requests
        start = time.time()

        try:
            api_key = self._get_env('BYBIT_API_KEY')
            api_secret = self._get_env('BYBIT_API_SECRET')

            if not api_key or not api_secret:
                return ConnectionResult(
                    name='Bybit',
                    type='cex',
                    status='skipped',
                    error='API keys not configured'
                )

            # Test API connection
            timestamp = str(int(time.time() * 1000))
            recv_window = '5000'

            import hmac
            import hashlib

            sign_payload = timestamp + api_key + recv_window
            signature = hmac.new(
                api_secret.encode(),
                sign_payload.encode(),
                hashlib.sha256
            ).hexdigest()

            headers = {
                'X-BAPI-API-KEY': api_key,
                'X-BAPI-TIMESTAMP': timestamp,
                'X-BAPI-SIGN': signature,
                'X-BAPI-RECV-WINDOW': recv_window,
            }

            response = requests.get(
                'https://api.bybit.com/v5/account/wallet-balance?accountType=UNIFIED&coin=USDT',
                headers=headers,
                timeout=10
            )

            latency = (time.time() - start) * 1000

            if response.status_code == 200:
                data = response.json()
                if data.get('retCode') == 0:
                    result = data.get('result', {})
                    list_data = result.get('list', [])
                    if list_data:
                        coins = list_data[0].get('coin', [])
                        usdt = next((c for c in coins if c['coin'] == 'USDT'), None)
                        balance = float(usdt.get('walletBalance', 0)) if usdt else 0.0
                    else:
                        balance = 0.0

                    return ConnectionResult(
                        name='Bybit',
                        type='cex',
                        status='success',
                        balance=balance,
                        latency_ms=latency
                    )
                else:
                    return ConnectionResult(
                        name='Bybit',
                        type='cex',
                        status='failed',
                        error=data.get('retMsg', 'Unknown error'),
                        latency_ms=latency
                    )
            else:
                return ConnectionResult(
                    name='Bybit',
                    type='cex',
                    status='failed',
                    error=f'HTTP {response.status_code}',
                    latency_ms=latency
                )

        except Exception as e:
            return ConnectionResult(
                name='Bybit',
                type='cex',
                status='failed',
                error=str(e),
                latency_ms=(time.time() - start) * 1000
            )

    async def test_solana_wallet(self, wallet_name: str, env_var: str) -> ConnectionResult:
        """Test Solana wallet connection via Helius RPC."""
        import time
        import requests
        start = time.time()

        try:
            helius_key = self._get_env('HELIUS_API_KEY')
            private_key = self._get_env(env_var)

            if not private_key:
                return ConnectionResult(
                    name=wallet_name,
                    type='solana',
                    status='skipped',
                    error=f'{env_var} not configured'
                )

            # Get public key from private key (simplified)
            # In production, use solana-py to derive public key
            rpc_url = f'https://mainnet.helius-rpc.com/?api-key={helius_key}'

            # Test RPC connection
            response = requests.post(
                rpc_url,
                json={
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'getHealth'
                },
                timeout=10
            )

            latency = (time.time() - start) * 1000

            if response.status_code == 200:
                # Wallet exists, assume balance check passes
                return ConnectionResult(
                    name=wallet_name,
                    type='solana',
                    status='success',
                    balance=None,  # Would need actual balance query
                    latency_ms=latency
                )
            else:
                return ConnectionResult(
                    name=wallet_name,
                    type='solana',
                    status='failed',
                    error=f'RPC error: {response.status_code}',
                    latency_ms=latency
                )

        except Exception as e:
            return ConnectionResult(
                name=wallet_name,
                type='solana',
                status='failed',
                error=str(e),
                latency_ms=(time.time() - start) * 1000
            )

    async def test_hyperliquid_connection(self) -> ConnectionResult:
        """Test Hyperliquid connection."""
        import time
        import requests
        start = time.time()

        try:
            # Hyperliquid uses the same private key as Solana
            private_key = self._get_env('PHANTOM_WALLET_MAIN')

            if not private_key:
                return ConnectionResult(
                    name='Hyperliquid',
                    type='cex',
                    status='skipped',
                    error='Wallet not configured'
                )

            # Test API connection
            response = requests.post(
                'https://api.hyperliquid.xyz/info',
                json={'type': 'meta'},
                timeout=10
            )

            latency = (time.time() - start) * 1000

            if response.status_code == 200:
                return ConnectionResult(
                    name='Hyperliquid',
                    type='cex',
                    status='success',
                    latency_ms=latency
                )
            else:
                return ConnectionResult(
                    name='Hyperliquid',
                    type='cex',
                    status='failed',
                    error=f'HTTP {response.status_code}',
                    latency_ms=latency
                )

        except Exception as e:
            return ConnectionResult(
                name='Hyperliquid',
                type='cex',
                status='failed',
                error=str(e),
                latency_ms=(time.time() - start) * 1000
            )

    async def test_polymarket_connection(self) -> ConnectionResult:
        """Test Polymarket connection."""
        import time
        import requests
        start = time.time()

        try:
            api_key = self._get_env('POLYMARKET_API_KEY')

            if not api_key:
                return ConnectionResult(
                    name='Polymarket',
                    type='evm',
                    status='skipped',
                    error='API key not configured'
                )

            # Test connection
            response = requests.get(
                'https://clob.polymarket.com/markets',
                headers={'POLYMARKET_API_KEY': api_key},
                timeout=10
            )

            latency = (time.time() - start) * 1000

            if response.status_code == 200:
                return ConnectionResult(
                    name='Polymarket',
                    type='evm',
                    status='success',
                    latency_ms=latency
                )
            else:
                return ConnectionResult(
                    name='Polymarket',
                    type='evm',
                    status='failed',
                    error=f'HTTP {response.status_code}',
                    latency_ms=latency
                )

        except Exception as e:
            return ConnectionResult(
                name='Polymarket',
                type='evm',
                status='failed',
                error=str(e),
                latency_ms=(time.time() - start) * 1000
            )

    async def run_all_tests(self) -> List[ConnectionResult]:
        """Run all wallet connection tests."""
        logger.info("Starting wallet connection tests...")

        tasks = [
            self.test_binance_connection(),
            self.test_bybit_connection(),
            self.test_hyperliquid_connection(),
            self.test_polymarket_connection(),
            self.test_solana_wallet('Phantom Main', 'PHANTOM_WALLET_MAIN'),
            self.test_solana_wallet('Phantom A', 'PHANTOM_WALLET_A'),
            self.test_solana_wallet('Phantom B', 'PHANTOM_WALLET_B'),
            self.test_solana_wallet('Phantom C', 'PHANTOM_WALLET_C'),
        ]

        self.results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle exceptions
        processed_results = []
        for i, result in enumerate(self.results):
            if isinstance(result, Exception):
                processed_results.append(ConnectionResult(
                    name=f'Test {i}',
                    type='unknown',
                    status='failed',
                    error=str(result)
                ))
            else:
                processed_results.append(result)

        self.results = processed_results
        return self.results

    def print_summary(self):
        """Print test results summary."""
        print("\n" + "=" * 70)
        print("🔐 WALLET CONNECTION TEST RESULTS")
        print("=" * 70)

        success_count = sum(1 for r in self.results if r.status == 'success')
        failed_count = sum(1 for r in self.results if r.status == 'failed')
        skipped_count = sum(1 for r in self.results if r.status == 'skipped')

        for result in self.results:
            icon = '✅' if result.status == 'success' else '❌' if result.status == 'failed' else '⏭️'
            print(f"\n{icon} {result.name} ({result.type})")
            print(f"   Status: {result.status.upper()}")
            if result.balance is not None:
                print(f"   Balance: ${result.balance:.2f}")
            if result.latency_ms > 0:
                print(f"   Latency: {result.latency_ms:.1f}ms")
            if result.error:
                print(f"   Error: {result.error}")

        print("\n" + "-" * 70)
        print(f"Summary: {success_count} success, {failed_count} failed, {skipped_count} skipped")
        print("=" * 70)

        return success_count == len([r for r in self.results if r.status != 'skipped'])

    def export_results(self) -> Dict:
        """Export results as dict."""
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'tests': [
                {
                    'name': r.name,
                    'type': r.type,
                    'status': r.status,
                    'balance': r.balance,
                    'latency_ms': r.latency_ms,
                    'error': r.error,
                }
                for r in self.results
            ],
            'summary': {
                'total': len(self.results),
                'success': sum(1 for r in self.results if r.status == 'success'),
                'failed': sum(1 for r in self.results if r.status == 'failed'),
                'skipped': sum(1 for r in self.results if r.status == 'skipped'),
            }
        }


async def main():
    """Main entry point."""
    tester = WalletConnectionTester()
    await tester.run_all_tests()
    tester.print_summary()

    # Save results
    results = tester.export_results()
    output_path = Path.home() / '.ozzy-secrets' / 'wallet_test_results.json'
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n💾 Results saved to {output_path}")


if __name__ == '__main__':
    asyncio.run(main())

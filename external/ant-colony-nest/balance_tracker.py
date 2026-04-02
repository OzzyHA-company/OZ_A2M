#!/usr/bin/env python3
"""
통합 잔액 추적 시스템
- 거래소 (Binance, Bybit)
- Phantom 지갑 (A, B, C)
- MetaMask (Polygon)
- Hyperliquid

CTO가 까먹지 않도록 모든 잔액을 한눈에 표시
"""

import json
import asyncio
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import ccxt
import os
import requests
from pathlib import Path


@dataclass
class BalanceSnapshot:
    """잔액 스냅샷"""
    timestamp: str
    location: str  # binance, bybit, phantom_a, etc.
    asset: str     # USDT, SOL, USDC, etc.
    amount: float
    usd_value: float


class BalanceTracker:
    """통합 잔액 추적기"""

    # CTO 요구: 까먹지 않도록 모든 위치를 코드에 명시
    LOCATIONS = {
        # 거래소
        "binance_spot": {"type": "exchange", "name": "Binance 현물"},
        "bybit_unified": {"type": "exchange", "name": "Bybit 통합거래"},

        # Phantom 지갑
        "phantom_a_hyperliquid": {"type": "wallet", "name": "Phantom A - Hyperliquid"},
        "phantom_b_pumpfun": {"type": "wallet", "name": "Phantom B - Pump.fun"},
        "phantom_c_gmgn": {"type": "wallet", "name": "Phantom C - GMGN"},

        # MetaMask
        "metamask_polygon": {"type": "wallet", "name": "MetaMask - Polygon"},
    }

    def __init__(self, db_path: str = "data/balance_tracking.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        # API 클라이언트 캐시
        self._binance = None
        self._bybit = None

    def _init_db(self):
        """데이터베이스 초기화"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS balance_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                location TEXT NOT NULL,
                asset TEXT NOT NULL,
                amount REAL NOT NULL,
                usd_value REAL NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp ON balance_snapshots(timestamp)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_location ON balance_snapshots(location)
        """)

        conn.commit()
        conn.close()

    def _get_binance(self):
        """Binance 클라이언트"""
        if not self._binance:
            self._binance = ccxt.binance({
                'apiKey': os.environ.get('BINANCE_API_KEY'),
                'secret': os.environ.get('BINANCE_API_SECRET'),
                'enableRateLimit': True,
            })
        return self._binance

    def _get_bybit(self):
        """Bybit 클라이언트"""
        if not self._bybit:
            self._bybit = ccxt.bybit({
                'apiKey': os.environ.get('BYBIT_API_KEY'),
                'secret': os.environ.get('BYBIT_API_SECRET'),
                'enableRateLimit': True,
            })
        return self._bybit

    async def fetch_binance_balance(self) -> List[BalanceSnapshot]:
        """Binance 잔액 조회"""
        snapshots = []
        try:
            balance = self._get_binance().fetch_balance()

            for coin, data in balance.get('total', {}).items():
                if data and data > 0:
                    # USDT 가치 계산 (간단화)
                    usd_value = data if coin == 'USDT' else data * 0  # 가격 조회 필요시 추가

                    snapshots.append(BalanceSnapshot(
                        timestamp=datetime.utcnow().isoformat(),
                        location="binance_spot",
                        asset=coin,
                        amount=float(data),
                        usd_value=float(usdt_value) if coin == 'USDT' else 0
                    ))
        except Exception as e:
            print(f"❌ Binance 조회 실패: {e}")

        return snapshots

    async def fetch_bybit_balance(self) -> List[BalanceSnapshot]:
        """Bybit 잔액 조회"""
        snapshots = []
        try:
            balance = self._get_bybit().fetch_balance()

            for coin, data in balance.get('total', {}).items():
                if data and data > 0:
                    usd_value = data if coin == 'USDT' else 0

                    snapshots.append(BalanceSnapshot(
                        timestamp=datetime.utcnow().isoformat(),
                        location="bybit_unified",
                        asset=coin,
                        amount=float(data),
                        usd_value=float(usd_value)
                    ))
        except Exception as e:
            print(f"❌ Bybit 조회 실패: {e}")

        return snapshots

    async def fetch_phantom_balance(self, wallet_name: str, address: str) -> Optional[BalanceSnapshot]:
        """Phantom 지갑 잔액 조회"""
        try:
            response = requests.post(
                'https://mainnet.helius-rpc.com/?api-key=6f4400fb-870c-4a67-8d40-856be23b0305',
                json={
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'getBalance',
                    'params': [address]
                },
                timeout=10
            )
            data = response.json()
            lamports = data.get('result', {}).get('value', 0)
            sol = lamports / 1e9

            return BalanceSnapshot(
                timestamp=datetime.utcnow().isoformat(),
                location=wallet_name,
                asset='SOL',
                amount=sol,
                usd_value=sol * 80  # $80/SOL
            )
        except Exception as e:
            print(f"❌ Phantom {wallet_name} 조회 실패: {e}")
            return None

    async def fetch_metamask_balance(self) -> Optional[BalanceSnapshot]:
        """MetaMask 잔액 조회"""
        try:
            address = os.environ.get('METAMASK_ADDRESS', '')
            if not address:
                return None

            response = requests.post(
                'https://polygon-rpc.com',
                json={
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'eth_getBalance',
                    'params': [address, 'latest']
                },
                timeout=10
            )
            data = response.json()
            wei = int(data.get('result', '0x0'), 16)
            matic = wei / 1e18

            return BalanceSnapshot(
                timestamp=datetime.utcnow().isoformat(),
                location="metamask_polygon",
                asset='MATIC',
                amount=matic,
                usd_value=0  # MATIC 가격 필요시 추가
            )
        except Exception as e:
            print(f"❌ MetaMask 조회 실패: {e}")
            return None

    async def fetch_all_balances(self) -> Dict[str, List[BalanceSnapshot]]:
        """모든 잔액 조회"""
        results = {
            "binance": await self.fetch_binance_balance(),
            "bybit": await self.fetch_bybit_balance(),
            "phantom_a": [],
            "phantom_b": [],
            "phantom_c": [],
            "metamask": [],
        }

        # Phantom 지갑
        wallets = {
            "phantom_a_hyperliquid": os.environ.get('PHANTOM_WALLET_A', ''),
            "phantom_b_pumpfun": os.environ.get('PHANTOM_WALLET_B', ''),
            "phantom_c_gmgn": os.environ.get('PHANTOM_WALLET_C', ''),
        }

        for name, address in wallets.items():
            if address:
                snapshot = await self.fetch_phantom_balance(name, address)
                if snapshot:
                    key = name.split('_')[0] + '_' + name.split('_')[1]
                    results[key].append(snapshot)

        # MetaMask
        metamask = await self.fetch_metamask_balance()
        if metamask:
            results["metamask"].append(metamask)

        return results

    async def save_balances(self, balances: Dict[str, List[BalanceSnapshot]]):
        """잔액 저장"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for location, snapshots in balances.items():
            for snapshot in snapshots:
                cursor.execute("""
                    INSERT INTO balance_snapshots
                    (timestamp, location, asset, amount, usd_value)
                    VALUES (?, ?, ?, ?, ?)
                """, (snapshot.timestamp, snapshot.location, snapshot.asset,
                      snapshot.amount, snapshot.usd_value))

        conn.commit()
        conn.close()
        print(f"✅ 잔액 저장 완료: {sum(len(v) for v in balances.values())} 개 항목")

    def get_latest_summary(self) -> Dict:
        """최신 잔액 요약"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT location, asset, amount, usd_value
            FROM balance_snapshots
            WHERE timestamp = (SELECT MAX(timestamp) FROM balance_snapshots)
        """)

        results = cursor.fetchall()
        conn.close()

        summary = {}
        total_usd = 0

        for location, asset, amount, usd_value in results:
            if location not in summary:
                summary[location] = []
            summary[location].append({
                "asset": asset,
                "amount": round(amount, 6),
                "usd_value": round(usd_value, 2)
            })
            total_usd += usd_value

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_usd": round(total_usd, 2),
            "by_location": summary
        }

    def print_balance_report(self):
        """잔액 리포트 출력 (CTO용)"""
        summary = self.get_latest_summary()

        print("\n" + "="*60)
        print("📊 OZ_A2M 전체 자산 현황")
        print("="*60)
        print(f"🕐 조회 시간: {summary['timestamp']}")
        print(f"💰 총 USD 가치: ${summary['total_usd']}")
        print("-"*60)

        for location, assets in summary['by_location'].items():
            loc_name = self.LOCATIONS.get(location, {}).get('name', location)
            print(f"\n📍 {loc_name}")
            for asset in assets:
                print(f"   {asset['asset']}: {asset['amount']} (${asset['usd_value']})")

        print("\n" + "="*60)


async def main():
    """테스트 실행"""
    tracker = BalanceTracker()

    print("🔍 전체 잔액 조회 중...")
    balances = await tracker.fetch_all_balances()
    await tracker.save_balances(balances)

    tracker.print_balance_report()


if __name__ == "__main__":
    asyncio.run(main())

"""
OZ_A2M Profit Vault Manager
수익 금고 통합 관리 시스템

원칙:
- 수익은 자동으로 마스터 금고로 집중
- 재투자는 사용자 명시적 승인 필요
- 원금은 봇에 유지, 수익만 인출
"""

import os
import sys
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
import json

logger = logging.getLogger(__name__)

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


class VaultType(Enum):
    """금고 유형"""
    BINANCE_PROFIT = "binance_profit"      # Binance 서브계정 수익 금고
    BYBIT_PROFIT = "bybit_profit"          # Bybit 수익 금고
    PHANTOM_MASTER = "phantom_master"      # Phantom 메인 마스터
    METAMASK_PROFIT = "metamask_profit"    # MetaMask Polygon 수익


@dataclass
class ProfitRecord:
    """수익 기록"""
    bot_id: str
    timestamp: datetime
    starting_capital: float
    ending_capital: float
    realized_profit: float
    withdrawn_amount: float
    vault_type: VaultType
    tx_hash: Optional[str] = None
    status: str = "pending"  # pending, completed, failed


@dataclass
class VaultStatus:
    """금고 현황"""
    vault_type: VaultType
    total_deposited: float
    total_withdrawn: float
    current_balance: float
    last_updated: datetime
    deposit_history: List[Dict] = field(default_factory=list)


class MasterVaultManager:
    """
    마스터 금고 통합 관리자

    모든 봇의 수익을 관리하고 추적
    """

    def __init__(self):
        self.vaults: Dict[VaultType, VaultStatus] = {}
        self.profit_history: List[ProfitRecord] = []
        self.storage_path = "data/vault_records.json"

        # 마스터 지갑 주소
        self.binance_profit_subaccount = os.getenv("BINANCE_PROFIT_SUBACCOUNT_EMAIL")
        self.phantom_master_address = os.getenv("PHANTOM_PROFIT_WALLET")
        self.metamask_profit_address = os.getenv("METAMASK_PROFIT_WALLET")

        self._load_records()

    def _load_records(self):
        """기록 로드"""
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                    # 복원 로직
                    logger.info(f"Loaded {len(data.get('history', []))} vault records")
        except Exception as e:
            logger.error(f"Failed to load vault records: {e}")

    async def calculate_bot_profit(self, bot_id: str, current_balance: float) -> Dict:
        """
        봇 수익 계산

        Returns:
            {
                'bot_id': str,
                'starting_capital': float,
                'current_balance': float,
                'realized_profit': float,
                'profit_pct': float,
                'should_withdraw': bool
            }
        """
        # 봇 설정에서 원금 조회
        starting_capital = await self._get_bot_base_capital(bot_id)

        realized_profit = current_balance - starting_capital
        profit_pct = (realized_profit / starting_capital * 100) if starting_capital > 0 else 0

        # 수익이 $1 이상일 때만 인출
        should_withdraw = realized_profit >= 1.0

        return {
            'bot_id': bot_id,
            'starting_capital': starting_capital,
            'current_balance': current_balance,
            'realized_profit': realized_profit,
            'profit_pct': profit_pct,
            'should_withdraw': should_withdraw
        }

    async def withdraw_profit_to_vault(self, bot_id: str, profit_amount: float) -> ProfitRecord:
        """
        수익을 마스터 금고로 인출

        Args:
            bot_id: 봇 ID
            profit_amount: 인출할 수익액

        Returns:
            ProfitRecord: 인출 기록
        """
        vault_type = self._get_vault_type_for_bot(bot_id)

        record = ProfitRecord(
            bot_id=bot_id,
            timestamp=datetime.utcnow(),
            starting_capital=await self._get_bot_base_capital(bot_id),
            ending_capital=await self._get_bot_base_capital(bot_id),  # 원금 유지
            realized_profit=profit_amount,
            withdrawn_amount=profit_amount,
            vault_type=vault_type,
            status="pending"
        )

        try:
            # 실제 인출 실행
            tx_hash = await self._execute_withdrawal(bot_id, profit_amount, vault_type)
            record.tx_hash = tx_hash
            record.status = "completed"

            logger.info(f"✅ {bot_id}: ${profit_amount:.2f} → {vault_type.value}")

        except Exception as e:
            record.status = "failed"
            logger.error(f"❌ {bot_id} withdrawal failed: {e}")

        self.profit_history.append(record)
        self._save_records()

        return record

    async def _execute_withdrawal(self, bot_id: str, amount: float, vault_type: VaultType) -> str:
        """실제 인출 실행"""
        from lib.core.profit.exchange_api_connector import (
            get_binance_connector, get_bybit_connector,
            PhantomConnector, MetaMaskConnector
        )

        if amount < 0.01:  # 최소 인출액
            logger.warning(f"Amount ${amount:.2f} too small for withdrawal")
            return f"skipped_small_amount_{datetime.utcnow().timestamp()}"

        try:
            if vault_type == VaultType.BINANCE_PROFIT:
                connector = get_binance_connector()
                result = await connector.withdraw_to_subaccount(
                    asset="USDT",
                    amount=amount,
                    subaccount_email=self.binance_profit_subaccount
                )
                if result.get('success'):
                    logger.info(f"✅ Binance profit withdrawn: ${amount:.2f} → {self.binance_profit_subaccount}")
                    return result.get('tx_id', f"binance_{datetime.utcnow().timestamp()}")
                else:
                    raise Exception(result.get('error', 'Unknown error'))

            elif vault_type == VaultType.BYBIT_PROFIT:
                connector = get_bybit_connector()
                # Bybit는 출금 주소로 직접 전송
                result = await connector.withdraw_to_profit_wallet(
                    coin="USDT",
                    amount=amount,
                    address=self.phantom_master_address,  # 또는 별도 Bybit 수익 지갑
                    chain="SOL"
                )
                if result.get('success'):
                    logger.info(f"✅ Bybit profit withdrawn: ${amount:.2f}")
                    return result.get('tx_id', f"bybit_{datetime.utcnow().timestamp()}")
                else:
                    raise Exception(result.get('error', 'Unknown error'))

            elif vault_type == VaultType.PHANTOM_MASTER:
                connector = PhantomConnector()
                # Solana 전송은 개인키 필요하므로 일단 기록만
                result = await connector.transfer_to_master(
                    from_wallet="bot_wallet",
                    amount_sol=amount / 80  # SOL 가격 대략 $80 가정
                )
                logger.info(f"📝 Phantom transfer logged: ${amount:.2f} (manual signing required)")
                return result.get('tx_hash', f"phantom_pending_{datetime.utcnow().timestamp()}")

            elif vault_type == VaultType.METAMASK_PROFIT:
                connector = MetaMaskConnector()
                # Polygon 전송은 개인키 필요하므로 일단 기록만
                result = await connector.transfer_profit(
                    from_wallet="bot_wallet",
                    amount_usdc=amount
                )
                logger.info(f"📝 MetaMask transfer logged: ${amount:.2f} (manual signing required)")
                return result.get('tx_hash', f"metamask_pending_{datetime.utcnow().timestamp()}")

            else:
                raise ValueError(f"Unknown vault type: {vault_type}")

        except Exception as e:
            logger.error(f"❌ Withdrawal failed for {bot_id}: {e}")
            raise

    async def _get_bot_base_capital(self, bot_id: str) -> float:
        """봇 원금 조회"""
        try:
            import importlib.util, os
            run_all_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "..",
                "department_7", "src", "bot", "run_all_bots.py"
            )
            spec = importlib.util.spec_from_file_location("run_all_bots", run_all_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for config in mod.BOT_CONFIGS:
                if config['id'] == bot_id:
                    return config['kwargs'].get('capital', config['kwargs'].get('capital_sol', 0))
        except Exception as e:
            logger.warning(f"Failed to load BOT_CONFIGS: {e}")
        return 0.0

    async def _get_bot_current_balance_from_exchange(self, bot_id: str) -> Optional[Dict]:
        """거래소에서 실제 잔액 조회"""
        try:
            # Bybit 봇
            if 'bybit' in bot_id.lower():
                from lib.core.profit.exchange_api_connector import get_bybit_connector
                connector = get_bybit_connector()
                return await connector.get_wallet_balance("USDT")

            # Binance 봇
            elif 'binance' in bot_id.lower() or 'grid' in bot_id.lower() or 'dca' in bot_id.lower():
                from lib.core.profit.exchange_api_connector import get_binance_connector
                connector = get_binance_connector()
                return await connector.get_account_balance("USDT")

            return None

        except Exception as e:
            logger.error(f"Failed to get balance for {bot_id}: {e}")
            return None

    def _get_vault_type_for_bot(self, bot_id: str) -> VaultType:
        """봇별 금고 타입 결정"""
        if 'binance' in bot_id.lower():
            return VaultType.BINANCE_PROFIT
        elif 'bybit' in bot_id.lower():
            return VaultType.BYBIT_PROFIT
        elif any(x in bot_id.lower() for x in ['pump', 'gmgn', 'hyperliquid']):
            return VaultType.PHANTOM_MASTER
        elif 'polymarket' in bot_id.lower():
            return VaultType.METAMASK_PROFIT
        else:
            return VaultType.BINANCE_PROFIT

    async def get_vault_summary(self) -> Dict:
        """전체 금고 요약"""
        summary = {
            'timestamp': datetime.utcnow().isoformat(),
            'vaults': {},
            'total_profit_usd': 0.0,
            'today_profit_usd': 0.0
        }

        for vault_type in VaultType:
            vault_data = await self._get_vault_balance(vault_type)
            summary['vaults'][vault_type.value] = vault_data
            summary['total_profit_usd'] += vault_data.get('balance_usd', 0)

        # 오늘 수익 계산
        today = datetime.utcnow().date()
        today_records = [
            r for r in self.profit_history
            if r.timestamp.date() == today and r.status == "completed"
        ]
        summary['today_profit_usd'] = sum(r.withdrawn_amount for r in today_records)

        return summary

    async def _get_vault_balance(self, vault_type: VaultType) -> Dict:
        """개별 금고 잔액 조회 - 실제 API 연동"""
        try:
            if vault_type == VaultType.BYBIT_PROFIT:
                from lib.core.profit.exchange_api_connector import get_bybit_connector
                connector = get_bybit_connector()
                balance = await connector.get_wallet_balance("USDT")
                if balance.get('success'):
                    return {
                        'type': vault_type.value,
                        'balance_usd': balance.get('wallet_balance', 0.0),
                        'available_usd': balance.get('available_balance', 0.0),
                        'unrealized_pnl': balance.get('unrealised_pnl', 0.0),
                        'last_update': balance.get('timestamp', datetime.utcnow().isoformat())
                    }

            elif vault_type == VaultType.BINANCE_PROFIT:
                from lib.core.profit.exchange_api_connector import get_binance_connector
                connector = get_binance_connector()
                # 전체 자산 USD 가치 조회
                total_balance = await connector.get_total_balance_usd()
                if total_balance.get('success'):
                    assets_summary = {
                        asset: f"{data['amount']:.4f} (${data['usd_value']:.2f})"
                        for asset, data in total_balance.get('assets', {}).items()
                        if data['usd_value'] > 0.01
                    }
                    return {
                        'type': vault_type.value,
                        'balance_usd': total_balance.get('total_usd', 0.0),
                        'available_usd': total_balance.get('total_usd', 0.0),  # Spot에서는 전체가 출금 가능
                        'unrealized_pnl': 0.0,  # Spot은 실시간 PnL 없음
                        'assets': assets_summary,
                        'last_update': total_balance.get('timestamp', datetime.utcnow().isoformat())
                    }

            # 기본값 (실패 시)
            return {
                'type': vault_type.value,
                'balance_usd': 0.0,
                'available_usd': 0.0,
                'unrealized_pnl': 0.0,
                'last_update': datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to get vault balance for {vault_type.value}: {e}")
            return {
                'type': vault_type.value,
                'balance_usd': 0.0,
                'available_usd': 0.0,
                'unrealized_pnl': 0.0,
                'last_update': datetime.utcnow().isoformat()
            }

    def _save_records(self):
        """기록 저장"""
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            data = {
                'timestamp': datetime.utcnow().isoformat(),
                'history': [
                    {
                        'bot_id': r.bot_id,
                        'timestamp': r.timestamp.isoformat(),
                        'profit': r.realized_profit,
                        'withdrawn': r.withdrawn_amount,
                        'vault': r.vault_type.value,
                        'status': r.status
                    }
                    for r in self.profit_history[-1000:]  # 최근 1000개만
                ]
            }
            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save vault records: {e}")

    async def reinvest_to_bot(self, bot_id: str, amount: float) -> bool:
        """재투자 — CEO 명시적 명령 없이는 절대 실행 안 됨"""
        raise PermissionError("수익 재투자는 CEO 직접 명령 필요. 자동 실행 금지.")


# 싱글톤 인스턴스
_vault_manager = None

def get_vault_manager() -> MasterVaultManager:
    """Vault Manager 싱글톤"""
    global _vault_manager
    if _vault_manager is None:
        _vault_manager = MasterVaultManager()
    return _vault_manager

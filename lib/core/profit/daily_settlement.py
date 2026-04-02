"""
OZ_A2M Daily Settlement System
일일 수익 정산 시스템

매일 00:00 UTC 실행:
1. 모든 봇 잔액 확인
2. 원금 대비 수익 계산
3. 수익 인출 (원금 유지)
4. 마스터 금고로 전송
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

from .vault_manager import get_vault_manager, VaultType
from ...department_7.src.bot.run_all_bots import BOT_CONFIGS

logger = logging.getLogger(__name__)


class DailySettlementSystem:
    """
    일일 정산 관리자

    00:00 UTC에 모든 봇의 수익을 정산하여 마스터 금고로 인출
    """

    def __init__(self):
        self.vault_manager = get_vault_manager()
        self.settlement_time = "00:00"  # UTC
        self.is_running = False

    async def run_daily_settlement(self):
        """일일 정산 실행"""
        if self.is_running:
            logger.warning("Settlement already running")
            return

        self.is_running = True
        logger.info("=" * 60)
        logger.info("🌙 Daily Settlement Started")
        logger.info(f"Time: {datetime.utcnow().isoformat()}")
        logger.info("=" * 60)

        results = {
            'timestamp': datetime.utcnow().isoformat(),
            'bots_processed': 0,
            'total_profit': 0.0,
            'successful_withdrawals': 0,
            'failed_withdrawals': 0,
            'details': []
        }

        for config in BOT_CONFIGS:
            bot_id = config['id']
            try:
                result = await self._settle_bot(bot_id)
                results['bots_processed'] += 1
                results['details'].append(result)

                if result['status'] == 'success':
                    results['total_profit'] += result['profit']
                    results['successful_withdrawals'] += 1
                elif result['status'] == 'failed':
                    results['failed_withdrawals'] += 1

            except Exception as e:
                logger.error(f"Settlement error for {bot_id}: {e}")
                results['details'].append({
                    'bot_id': bot_id,
                    'status': 'error',
                    'error': str(e)
                })

        # 요약 출력
        logger.info("\n" + "=" * 60)
        logger.info("📊 Settlement Summary")
        logger.info("=" * 60)
        logger.info(f"Bots Processed: {results['bots_processed']}")
        logger.info(f"Total Profit: ${results['total_profit']:.2f}")
        logger.info(f"Successful: {results['successful_withdrawals']}")
        logger.info(f"Failed: {results['failed_withdrawals']}")
        logger.info("=" * 60)

        self.is_running = False
        return results

    async def _settle_bot(self, bot_id: str) -> Dict:
        """개별 봇 정산"""
        logger.info(f"\n📈 Processing {bot_id}...")

        # 1. 현재 잔액 조회 (실제 거래소 API)
        current_balance = await self._get_bot_current_balance(bot_id)

        # 2. 수익 계산
        profit_data = await self.vault_manager.calculate_bot_profit(
            bot_id, current_balance
        )

        logger.info(f"  Starting Capital: ${profit_data['starting_capital']:.2f}")
        logger.info(f"  Current Balance:  ${current_balance:.2f}")
        logger.info(f"  Realized Profit:  ${profit_data['realized_profit']:.2f} ({profit_data['profit_pct']:.2f}%)")

        # 3. 수익 인출
        if profit_data['should_withdraw']:
            record = await self.vault_manager.withdraw_profit_to_vault(
                bot_id, profit_data['realized_profit']
            )

            if record.status == "completed":
                logger.info(f"  ✅ Withdrawn: ${record.withdrawn_amount:.2f}")

                # 4. 원금 리셋 (봇 잔액 = 원금으로)
                await self._reset_bot_to_base_capital(bot_id)

                return {
                    'bot_id': bot_id,
                    'status': 'success',
                    'profit': profit_data['realized_profit'],
                    'profit_pct': profit_data['profit_pct'],
                    'vault': record.vault_type.value,
                    'tx_hash': record.tx_hash
                }
            else:
                logger.error(f"  ❌ Withdrawal failed")
                return {
                    'bot_id': bot_id,
                    'status': 'failed',
                    'profit': profit_data['realized_profit'],
                    'error': 'Withdrawal failed'
                }
        else:
            logger.info(f"  ⏭️  No profit to withdraw (threshold not met)")
            return {
                'bot_id': bot_id,
                'status': 'skipped',
                'profit': profit_data['realized_profit'],
                'reason': 'Below threshold ($1)'
            }

    async def _get_bot_current_balance(self, bot_id: str) -> float:
        """봇 현재 잔액 조회"""
        # TODO: 실제 거래소 API 연동
        # 지금은 시뮬레이션 (원금 기준)

        for config in BOT_CONFIGS:
            if config['id'] == bot_id:
                base_capital = config['kwargs'].get('capital', 0)
                # 시뮬레이션: 원금 + 소량 수익
                # 실제 구현 시 거래소 API 호출
                return base_capital * 1.05  # 임시: 5% 수익 가정

        return 0.0

    async def _reset_bot_to_base_capital(self, bot_id: str):
        """봇 잔액을 원금으로 리셋"""
        # TODO: 실제 거래소 API로 원금만 남기고 수익 인출
        logger.info(f"  🔄 Reset {bot_id} to base capital")

    async def schedule_daily(self):
        """매일 정해진 시간에 실행"""
        while True:
            now = datetime.utcnow()
            target = now.replace(hour=0, minute=0, second=0, microsecond=0)

            if now >= target:
                target += timedelta(days=1)

            wait_seconds = (target - now).total_seconds()
            logger.info(f"Next settlement in {wait_seconds/3600:.1f} hours")

            await asyncio.sleep(wait_seconds)
            await self.run_daily_settlement()

    async def get_settlement_history(self, days: int = 7) -> List[Dict]:
        """정산 이력 조회"""
        # TODO: 데이터베이스에서 조회
        return []

    async def manual_settlement(self, bot_id: Optional[str] = None) -> Dict:
        """수동 정산 (즉시 실행)"""
        if bot_id:
            # 특정 봇만
            return await self._settle_bot(bot_id)
        else:
            # 전체 정산
            return await self.run_daily_settlement()


# 싱글톤
_settlement_system = None

def get_settlement_system() -> DailySettlementSystem:
    """Settlement System 싱글톤"""
    global _settlement_system
    if _settlement_system is None:
        _settlement_system = DailySettlementSystem()
    return _settlement_system

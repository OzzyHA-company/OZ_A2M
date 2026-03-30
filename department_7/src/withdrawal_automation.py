"""
OZ_A2M 출금 자동화 모듈 - STEP D
수익 분배 및 출금 알림 자동화
"""

import asyncio
import json
import os
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

import sys
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger
from lib.messaging.event_bus import get_event_bus, EventBus

logger = get_logger(__name__)

# 설정 상수
DAILY_PROFIT_REINVEST_PCT = 0.5  # 50% 재투자
DAILY_PROFIT_WITHDRAW_PCT = 0.5  # 50% 출금 대기
WITHDRAWAL_THRESHOLD = 50.0  # $50 이상 시 알림
WITHDRAWAL_CHECK_INTERVAL = 300  # 5분마다 체크


@dataclass
class ProfitAllocation:
    """수익 분배 기록"""
    date: str
    total_profit: float
    reinvest_amount: float
    withdraw_amount: float
    timestamp: str


@dataclass
class WithdrawalRequest:
    """출금 요청"""
    id: str
    exchange: str
    asset: str
    amount: float
    status: str  # pending, processing, completed, failed
    created_at: str
    completed_at: Optional[str] = None


class WithdrawalAutomation:
    """
    출금 자동화 시스템

    기능:
    1. 일일 수익 50% 재투자 / 50% 출금 대기 분배
    2. 출금 대기 잔액 $50 초과 시 Telegram 알림
    3. 사용자 확인 시 자동 출금 실행
    4. 출금 히스토리 관리
    """

    def __init__(
        self,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        data_dir: str = None
    ):
        self.data_dir = Path(data_dir) if data_dir else Path(__file__).parent / "data"
        self.data_dir.mkdir(exist_ok=True)

        # 데이터 파일
        self.allocation_file = self.data_dir / "profit_allocations.json"
        self.withdrawal_file = self.data_dir / "withdrawals.json"
        self.pending_file = self.data_dir / "pending_withdrawals.json"

        # 상태
        self.pending_withdrawals: Dict[str, float] = {}  # 거래소별 출금 대기액
        self.total_pending: float = 0.0
        self.allocation_history: List[ProfitAllocation] = []
        self.withdrawal_history: List[WithdrawalRequest] = []

        # EventBus
        self.event_bus: Optional[EventBus] = None

        # Telegram 설정
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        self.telegram_enabled = bool(self.telegram_bot_token and self.telegram_chat_id)

        # 실행 중 플래그
        self.running = False

        logger.info("WithdrawalAutomation initialized")

    async def initialize(self):
        """초기화"""
        # 기존 데이터 로드
        self._load_data()

        # EventBus 연결
        try:
            self.event_bus = get_event_bus()
            await self.event_bus.connect()
            await self.event_bus.subscribe("profit/earned", self._on_profit_earned)
            await self.event_bus.subscribe("withdrawal/confirm", self._on_withdrawal_confirm)
            logger.info("EventBus connected")
        except Exception as e:
            logger.warning(f"EventBus connection failed: {e}")

        self.running = True
        logger.info("WithdrawalAutomation started")

    def _load_data(self):
        """저장된 데이터 로드"""
        try:
            if self.allocation_file.exists():
                with open(self.allocation_file, 'r') as f:
                    data = json.load(f)
                    self.allocation_history = [ProfitAllocation(**d) for d in data]

            if self.withdrawal_file.exists():
                with open(self.withdrawal_file, 'r') as f:
                    data = json.load(f)
                    self.withdrawal_history = [WithdrawalRequest(**d) for d in data]

            if self.pending_file.exists():
                with open(self.pending_file, 'r') as f:
                    self.pending_withdrawals = json.load(f)
                    self.total_pending = sum(self.pending_withdrawals.values())

            logger.info(f"Loaded {len(self.allocation_history)} allocations, "
                       f"{len(self.withdrawal_history)} withdrawals, "
                       f"${self.total_pending:.2f} pending")

        except Exception as e:
            logger.error(f"Failed to load data: {e}")

    def _save_data(self):
        """데이터 저장"""
        try:
            with open(self.allocation_file, 'w') as f:
                json.dump([asdict(a) for a in self.allocation_history], f, indent=2)

            with open(self.withdrawal_file, 'w') as f:
                json.dump([asdict(w) for w in self.withdrawal_history], f, indent=2)

            with open(self.pending_file, 'w') as f:
                json.dump(self.pending_withdrawals, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to save data: {e}")

    async def _on_profit_earned(self, message):
        """수익 발생 이벤트 처리"""
        try:
            data = json.loads(message.payload.decode())
            bot_id = data.get('bot_id')
            profit = data.get('profit', 0.0)
            exchange = data.get('exchange', 'unknown')

            if profit > 0:
                await self.allocate_profit(exchange, profit)

        except Exception as e:
            logger.error(f"Error processing profit earned: {e}")

    async def allocate_profit(self, exchange: str, profit: float):
        """
        수익 분배
        - 50% 재투자 (자본에 추가)
        - 50% 출금 대기
        """
        reinvest = profit * DAILY_PROFIT_REINVEST_PCT
        withdraw = profit * DAILY_PROFIT_WITHDRAW_PCT

        # 출금 대기액 누적
        if exchange not in self.pending_withdrawals:
            self.pending_withdrawals[exchange] = 0.0
        self.pending_withdrawals[exchange] += withdraw
        self.total_pending += withdraw

        # 기록 저장
        allocation = ProfitAllocation(
            date=date.today().isoformat(),
            total_profit=profit,
            reinvest_amount=reinvest,
            withdraw_amount=withdraw,
            timestamp=datetime.utcnow().isoformat()
        )
        self.allocation_history.append(allocation)
        self._save_data()

        logger.info(f"Profit allocated: ${profit:.4f} "
                   f"(Reinvest: ${reinvest:.4f}, Withdraw: ${withdraw:.4f})")

        # 출금 임계값 체크
        if self.total_pending >= WITHDRAWAL_THRESHOLD:
            await self._notify_withdrawal_available()

    async def _notify_withdrawal_available(self):
        """출금 가능 알림"""
        message = (
            f"💰 출금 가능 금액: ${self.total_pending:.2f}\n\n"
            f"거래소별 대기액:\n"
        )
        for exchange, amount in self.pending_withdrawals.items():
            message += f"  • {exchange}: ${amount:.2f}\n"

        message += "\n출금하시겠습니까?\n"
        message += "[예] 출금 실행\n"
        message += "[아니오] 계속 적립"

        await self._send_telegram_notification(message)
        logger.info(f"Withdrawal notification sent: ${self.total_pending:.2f}")

    async def _on_withdrawal_confirm(self, message):
        """출금 확인 이벤트 처리 (Telegram 응답)"""
        try:
            data = json.loads(message.payload.decode())
            response = data.get('response', '').lower()

            if response in ['예', 'yes', 'y', '1']:
                # Binance로 자동 집결
                await self.execute_consolidation()
            else:
                logger.info("Withdrawal postponed by user")

        except Exception as e:
            logger.error(f"Error processing withdrawal confirm: {e}")

    async def execute_consolidation(self):
        """
        출금 집결 실행
        모든 거래소 잔액을 Binance로 집결
        """
        logger.info(f"Executing consolidation: ${self.total_pending:.2f}")

        # 출금 요청 생성
        for exchange, amount in list(self.pending_withdrawals.items()):
            if amount > 0:
                request = WithdrawalRequest(
                    id=f"wd_{datetime.utcnow().timestamp()}_{exchange}",
                    exchange=exchange,
                    asset='USDT' if exchange != 'hyperliquid' else 'USDC',
                    amount=amount,
                    status='processing',
                    created_at=datetime.utcnow().isoformat()
                )
                self.withdrawal_history.append(request)

                # TODO: 실제 출금 API 호출
                success = await self._execute_withdrawal(request)

                if success:
                    request.status = 'completed'
                    request.completed_at = datetime.utcnow().isoformat()
                    logger.info(f"Withdrawal completed: {exchange} ${amount:.2f}")
                else:
                    request.status = 'failed'
                    logger.error(f"Withdrawal failed: {exchange} ${amount:.2f}")

        # 출금 대기액 초기화
        self.pending_withdrawals.clear()
        self.total_pending = 0.0
        self._save_data()

        # 완료 알림
        await self._send_telegram_notification(
            f"✅ 출금 집결 완료\n"
            f"총 출금액: ${self.total_pending:.2f}\n"
            f"목적지: Binance\n"
            f"출금 준비가 완료되었습니다."
        )

    async def _execute_withdrawal(self, request: WithdrawalRequest) -> bool:
        """
        실제 출금 실행
        TODO: 각 거래소 API 연동
        """
        logger.info(f"Executing withdrawal: {request.exchange} ${request.amount:.2f}")

        # Mock 구현 - 실제 구현 시 각 거래소 API 호출
        await asyncio.sleep(1)

        # 출금 성공으로 가정
        return True

    async def manual_withdrawal_request(self, exchange: str, asset: str, amount: float) -> bool:
        """수동 출금 요청"""
        try:
            request = WithdrawalRequest(
                id=f"wd_manual_{datetime.utcnow().timestamp()}",
                exchange=exchange,
                asset=asset,
                amount=amount,
                status='processing',
                created_at=datetime.utcnow().isoformat()
            )
            self.withdrawal_history.append(request)

            success = await self._execute_withdrawal(request)

            if success:
                request.status = 'completed'
                request.completed_at = datetime.utcnow().isoformat()
                self._save_data()

                await self._send_telegram_notification(
                    f"✅ 수동 출금 완료\n"
                    f"거래소: {exchange}\n"
                    f"자산: {asset}\n"
                    f"금액: ${amount:.2f}"
                )
                return True
            else:
                request.status = 'failed'
                self._save_data()
                return False

        except Exception as e:
            logger.error(f"Manual withdrawal failed: {e}")
            return False

    async def _send_telegram_notification(self, message: str):
        """Telegram 알림 발송"""
        if not self.telegram_enabled:
            logger.info(f"[Telegram would send]: {message}")
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
                        logger.info("Telegram notification sent")
                    else:
                        logger.warning(f"Telegram notification failed: {resp.status}")

        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")

    async def check_withdrawal_threshold(self):
        """주기적 출금 임계값 체크"""
        while self.running:
            try:
                if self.total_pending >= WITHDRAWAL_THRESHOLD:
                    await self._notify_withdrawal_available()

                # 5분마다 체크
                await asyncio.sleep(WITHDRAWAL_CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"Error in threshold check: {e}")
                await asyncio.sleep(60)

    async def get_status(self) -> Dict:
        """현재 상태 반환"""
        return {
            "total_pending": self.total_pending,
            "pending_by_exchange": self.pending_withdrawals,
            "allocation_count": len(self.allocation_history),
            "withdrawal_count": len(self.withdrawal_history),
            "threshold": WITHDRAWAL_THRESHOLD,
            "telegram_enabled": self.telegram_enabled
        }

    async def run(self):
        """메인 실행 루프"""
        await self.initialize()

        # 출금 임계값 체크 태스크
        threshold_task = asyncio.create_task(self.check_withdrawal_threshold())

        try:
            while self.running:
                await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("WithdrawalAutomation cancelled")
        finally:
            self.running = False
            threshold_task.cancel()
            try:
                await threshold_task
            except asyncio.CancelledError:
                pass

    async def stop(self):
        """중지"""
        self.running = False
        if self.event_bus:
            await self.event_bus.disconnect()
        logger.info("WithdrawalAutomation stopped")


# 편의 함수
async def main():
    """단독 실행용"""
    withdrawal = WithdrawalAutomation()

    # 테스트: 가상 수익 분배
    await withdrawal.initialize()
    await withdrawal.allocate_profit("binance", 100.0)
    await withdrawal.allocate_profit("bybit", 30.0)

    print(f"Total pending: ${withdrawal.total_pending:.2f}")

    await withdrawal.run()


if __name__ == "__main__":
    asyncio.run(main())

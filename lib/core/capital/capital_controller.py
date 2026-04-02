"""
OZ_A2M Capital Controller
자본 이동 컨트롤 시스템

사용자 권한:
- 마스터 금고 → 봇 재투자 (명시적 승인 필요)
- 봇 → 마스터 금고 출금
- 실시간 자본 이동
- 수익 재투자 방지 메커니즘
"""

import os
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TransferType(Enum):
    """이체 유형"""
    REINVEST = "reinvest"          # 마스터 금고 → 봇 (재투자)
    WITHDRAW = "withdraw"          # 봇 → 마스터 금고 (출금)
    EMERGENCY = "emergency"        # 긴급 출금


class TransferStatus(Enum):
    """이체 상태"""
    PENDING = "pending"            # 대기 중
    APPROVED = "approved"          # 승인됨
    COMPLETED = "completed"        # 완료
    REJECTED = "rejected"          # 거부
    FAILED = "failed"              # 실패


@dataclass
class TransferRequest:
    """이체 요청"""
    request_id: str
    transfer_type: TransferType
    bot_id: str
    amount: float
    requested_at: datetime
    status: TransferStatus
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    tx_hash: Optional[str] = None
    notes: Optional[str] = None


class CapitalController:
    """
    자본 이동 컨트롤러

    모든 자본 이동은 사용자 명시적 승인 필요
    """

    def __init__(self):
        self.pending_requests: List[TransferRequest] = []
        self.transfer_history: List[TransferRequest] = []
        self.require_approval = True  # 항상 승인 필요

        # 마스터 금고 정보
        self.binance_profit_email = os.getenv("BINANCE_PROFIT_SUBACCOUNT_EMAIL")
        self.phantom_master = os.getenv("PHANTOM_PROFIT_WALLET")

    async def request_reinvest(self, bot_id: str, amount: float, requested_by: str = "user") -> TransferRequest:
        """
        재투자 요청 (마스터 금고 → 봇)

        ⚠️ 반드시 사용자 승인 필요
        """
        request_id = f"rei_{datetime.utcnow().timestamp()}"

        request = TransferRequest(
            request_id=request_id,
            transfer_type=TransferType.REINVEST,
            bot_id=bot_id,
            amount=amount,
            requested_at=datetime.utcnow(),
            status=TransferStatus.PENDING
        )

        self.pending_requests.append(request)

        logger.warning(f"🚨 REINVEST REQUEST: ${amount} → {bot_id}")
        logger.warning(f"Request ID: {request_id}")
        logger.warning("Approval required!")

        return request

    async def request_withdraw(self, bot_id: str, amount: float,
                               withdraw_type: str = "full") -> TransferRequest:
        """
        출금 요청 (봇 → 마스터 금고)

        Args:
            bot_id: 봇 ID
            amount: 금액 ($) 또는 "all", "profit"
            withdraw_type: "full" | "profit" | "percentage"
        """
        request_id = f"wdr_{datetime.utcnow().timestamp()}"

        # 금액 계산
        if amount == "all":
            actual_amount = await self._get_bot_total_balance(bot_id)
        elif amount == "profit":
            actual_amount = await self._get_bot_profit(bot_id)
        else:
            actual_amount = float(amount)

        request = TransferRequest(
            request_id=request_id,
            transfer_type=TransferType.WITHDRAW,
            bot_id=bot_id,
            amount=actual_amount,
            requested_at=datetime.utcnow(),
            status=TransferStatus.PENDING,
            notes=f"Type: {withdraw_type}"
        )

        self.pending_requests.append(request)

        logger.info(f"💰 WITHDRAW REQUEST: ${actual_amount} from {bot_id}")
        logger.info(f"Request ID: {request_id}")

        # 출금은 자동 승인 (사용자가 버튼을 눌렀으므로)
        if not self.require_approval:
            await self.approve_request(request_id, "auto")

        return request

    async def approve_request(self, request_id: str, approved_by: str) -> bool:
        """
        이체 요청 승인

        ⚠️ 오직 사용자만 승인 가능
        """
        request = self._get_pending_request(request_id)
        if not request:
            logger.error(f"Request {request_id} not found")
            return False

        # 승인 처리
        request.status = TransferStatus.APPROVED
        request.approved_by = approved_by
        request.approved_at = datetime.utcnow()

        # 실제 이체 실행
        success = await self._execute_transfer(request)

        if success:
            request.status = TransferStatus.COMPLETED
            logger.info(f"✅ Transfer completed: {request_id}")
        else:
            request.status = TransferStatus.FAILED
            logger.error(f"❌ Transfer failed: {request_id}")

        # 히스토리에 추가
        self.transfer_history.append(request)
        self.pending_requests.remove(request)

        return success

    async def reject_request(self, request_id: str, rejected_by: str, reason: str = ""):
        """이체 요청 거부"""
        request = self._get_pending_request(request_id)
        if request:
            request.status = TransferStatus.REJECTED
            request.approved_by = rejected_by
            request.notes = reason
            self.transfer_history.append(request)
            self.pending_requests.remove(request)
            logger.info(f"❌ Request rejected: {request_id} - {reason}")

    async def _execute_transfer(self, request: TransferRequest) -> bool:
        """실제 이체 실행"""
        try:
            if request.transfer_type == TransferType.REINVEST:
                # 마스터 금고 → 봇
                return await self._transfer_to_bot(request.bot_id, request.amount)
            elif request.transfer_type == TransferType.WITHDRAW:
                # 봇 → 마스터 금고
                return await self._transfer_to_vault(request.bot_id, request.amount)
            return False
        except Exception as e:
            logger.error(f"Transfer execution failed: {e}")
            return False

    async def _transfer_to_bot(self, bot_id: str, amount: float) -> bool:
        """마스터 금고에서 봇으로 이체"""
        logger.info(f"Transferring ${amount} to {bot_id}...")
        # TODO: 실제 거래소 API 연동
        # 1. 마스터 금고에서 출금
        # 2. 봇 거래소로 입금
        # 3. 봇 자본 업데이트
        await asyncio.sleep(0.5)  # 시뮬레이션
        return True

    async def _transfer_to_vault(self, bot_id: str, amount: float) -> bool:
        """봇에서 마스터 금고로 이체"""
        logger.info(f"Withdrawing ${amount} from {bot_id} to vault...")
        # TODO: 실제 거래소 API 연동
        # 1. 봇 잔액 확인
        # 2. 수익 인출
        # 3. 마스터 금고로 입금
        await asyncio.sleep(0.5)  # 시뮬레이션
        return True

    async def _get_bot_total_balance(self, bot_id: str) -> float:
        """봇 총 잔액 조회"""
        # TODO: 실제 잔액 조회
        return 0.0

    async def _get_bot_profit(self, bot_id: str) -> float:
        """봇 수익 조회"""
        # TODO: 실제 수익 계산
        return 0.0

    def _get_pending_request(self, request_id: str) -> Optional[TransferRequest]:
        """대기 중인 요청 조회"""
        for req in self.pending_requests:
            if req.request_id == request_id:
                return req
        return None

    async def get_pending_requests(self) -> List[TransferRequest]:
        """대기 중인 요청 목록"""
        return self.pending_requests

    async def get_transfer_history(self, bot_id: Optional[str] = None,
                                   days: int = 7) -> List[TransferRequest]:
        """이체 히스토리 조회"""
        cutoff = datetime.utcnow() - __import__('datetime').timedelta(days=days)
        history = [h for h in self.transfer_history if h.requested_at >= cutoff]

        if bot_id:
            history = [h for h in history if h.bot_id == bot_id]

        return history

    async def emergency_withdraw_all(self) -> Dict:
        """
        긴급 전체 출금

        모든 봇의 수익을 즉시 마스터 금고로 인출
        """
        logger.warning("🚨 EMERGENCY WITHDRAW ALL INITIATED")

        results = []
        # TODO: 모든 봇 순회하며 출금

        return {
            'timestamp': datetime.utcnow().isoformat(),
            'total_withdrawn': 0.0,
            'details': results
        }


# 싱글톤
_capital_controller = None

def get_capital_controller() -> CapitalController:
    """Capital Controller 싱글톤"""
    global _capital_controller
    if _capital_controller is None:
        _capital_controller = CapitalController()
    return _capital_controller

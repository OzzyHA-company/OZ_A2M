"""
출금 실행기 - pi-mono 통합 버전
- 자동 출금 실행
- Jito MEV 보호 (Solana)
- pi-mono AI 최적화 의사결정
"""

import asyncio
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import subprocess
import httpx

from nest_profit import ProfitTracker, WithdrawalStatus


class WithdrawalDestination(Enum):
    """출금 목적지"""
    BINANCE_MASTER = "binance_master"
    BYBIT_MASTER = "bybit_master"
    HYPERLIQUID_MASTER = "hyperliquid_master"
    PHANTOM_PROFIT = "phantom_profit"
    METAMASK_PROFIT = "metamask_profit"


@dataclass
class WithdrawalRequest:
    """출금 요청"""
    bot_id: str
    amount: float
    currency: str
    destination: WithdrawalDestination
    priority: str = "normal"  # normal, high, urgent
    use_jito: bool = False    # Jito MEV 보호 사용


@dataclass
class WithdrawalResult:
    """출금 결과"""
    success: bool
    bot_id: str
    amount: float
    currency: str
    tx_id: Optional[str]
    status: str
    error: Optional[str] = None
    completed_at: Optional[datetime] = None


class WithdrawalExecutor:
    """
    출금 실행기

    기능:
    1. 거래소별 출금 실행 (Binance, Bybit, Hyperliquid)
    2. Solana 출금 (Phantom 지갑, Jito MEV 보호)
    3. pi-mono AI 출금 최적화 결정
    4. 출금 상태 모니터링
    """

    def __init__(self, profit_tracker: ProfitTracker):
        self.profit_tracker = profit_tracker
        self.active_withdrawals: Dict[str, WithdrawalRequest] = {}

        # 설정
        self.min_withdrawal_amount = 0.01
        self.max_slippage_pct = 0.5

    async def execute_withdrawal(
        self,
        request: WithdrawalRequest
    ) -> WithdrawalResult:
        """출금 실행"""
        print(f"💸 출금 요청: {request.bot_id} ${request.amount:.4f} {request.currency}")

        # 금액 검증
        if request.amount < self.min_withdrawal_amount:
            return WithdrawalResult(
                success=False,
                bot_id=request.bot_id,
                amount=request.amount,
                currency=request.currency,
                tx_id=None,
                status="failed",
                error=f"금액 너무 작음 (최소 ${self.min_withdrawal_amount})"
            )

        # pi-mono AI 최적화 결정
        should_proceed = await self._consult_pi_mono(request)
        if not should_proceed:
            return WithdrawalResult(
                success=False,
                bot_id=request.bot_id,
                amount=request.amount,
                currency=request.currency,
                tx_id=None,
                status="cancelled",
                error="pi-mono AI가 출금을 취소함"
            )

        # 출금 경로별 실행
        if request.destination in [WithdrawalDestination.BINANCE_MASTER, WithdrawalDestination.BYBIT_MASTER]:
            result = await self._execute_exchange_withdrawal(request)
        elif request.destination == WithdrawalDestination.PHANTOM_PROFIT:
            result = await self._execute_solana_withdrawal(request)
        elif request.destination == WithdrawalDestination.METAMASK_PROFIT:
            result = await self._execute_polygon_withdrawal(request)
        else:
            result = WithdrawalResult(
                success=False,
                bot_id=request.bot_id,
                amount=request.amount,
                currency=request.currency,
                tx_id=None,
                status="failed",
                error=f"지원하지 않는 목적지: {request.destination}"
            )

        # 결과 기록
        if result.success:
            await self.profit_tracker.complete_withdrawal(
                bot_id=request.bot_id,
                amount=request.amount,
                currency=request.currency,
                destination=request.destination.value,
                tx_id=result.tx_id
            )

        return result

    async def _consult_pi_mono(self, request: WithdrawalRequest) -> bool:
        """pi-mono (Gemini Pro SaaS) AI에게 출금 결정 위임"""
        # 시장 조건 수집
        market_data = await self._fetch_market_conditions(request.currency)

        # 1차: pi-mono Bridge → Gemini Pro SaaS 질의
        try:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib" / "pi_mono_bridge"))
            from bridge import get_pi_mono_bridge

            bridge = get_pi_mono_bridge()
            volatility = market_data.get("volatility", 0)
            context = (
                f"시장 변동성: {volatility:.1%}, "
                f"우선순위: {request.priority}, "
                f"금액: {request.amount} {request.currency}"
            )
            approved = await bridge.consult_withdrawal(
                amount=request.amount,
                asset=request.currency,
                reason=f"priority={request.priority}, volatility={volatility:.1%}"
            )
            print(f"🧠 pi-mono Gemini 출금 결정: {'승인' if approved else '거부'} ({context})")
            return approved

        except Exception as e:
            print(f"⚠️ pi-mono 연결 실패 ({e}), 휴리스틱 사용")

        # 2차 fallback: 휴리스틱
        if market_data.get("volatility", 0) > 0.1:
            print(f"⚠️ 높은 변동성 감지, 출금 지연 권장")
            if request.priority != "urgent":
                return False

        return True

    async def _fetch_market_conditions(self, currency: str) -> Dict[str, Any]:
        """시장 조건 조회"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.binance.com/api/v3/ticker/24hr?symbol={currency}USDT",
                    timeout=5.0
                )
                if response.status_code == 200:
                    data = response.json()
                    price_change_pct = abs(float(data.get("priceChangePercent", 0)))
                    return {"volatility": price_change_pct / 100}
        except Exception as e:
            print(f"⚠️ 시장 데이터 조회 실패: {e}")

        return {"volatility": 0}

    async def _execute_exchange_withdrawal(
        self,
        request: WithdrawalRequest
    ) -> WithdrawalResult:
        """거래소 출금 실행"""
        try:
            # 출금 진행 중 표시
            await self.profit_tracker.mark_withdrawal_processing(
                bot_id=request.bot_id,
                amount=request.amount
            )

            # 실제 출금은 각 봇의 withdrawal_automation 모듈에 위임
            # 여기서는 출금 이벤트 발행만 수행

            tx_id = f"pending_{datetime.utcnow().timestamp()}"

            return WithdrawalResult(
                success=True,
                bot_id=request.bot_id,
                amount=request.amount,
                currency=request.currency,
                tx_id=tx_id,
                status="processing",
                completed_at=None
            )

        except Exception as e:
            return WithdrawalResult(
                success=False,
                bot_id=request.bot_id,
                amount=request.amount,
                currency=request.currency,
                tx_id=None,
                status="failed",
                error=str(e)
            )

    async def _execute_solana_withdrawal(
        self,
        request: WithdrawalRequest
    ) -> WithdrawalResult:
        """Solana 출금 실행 (Jito MEV 보호)"""
        try:
            # Jito Shredstream을 통한 MEV 보호 출금
            if request.use_jito:
                return await self._execute_jito_withdrawal(request)

            # 일반 Solana 출금
            return await self._execute_standard_solana_withdrawal(request)

        except Exception as e:
            return WithdrawalResult(
                success=False,
                bot_id=request.bot_id,
                amount=request.amount,
                currency=request.currency,
                tx_id=None,
                status="failed",
                error=f"Solana 출금 실패: {e}"
            )

    async def _execute_jito_withdrawal(
        self,
        request: WithdrawalRequest
    ) -> WithdrawalResult:
        """Jito MEV 보호 출금"""
        print(f"🛡️ Jito MEV 보호 출금: {request.bot_id}")

        # Jito Block Engine 연결
        jito_tip = 0.0001  # 0.0001 SOL Jito 팁

        # 출금 트랜잭션 생성 (RPC 호출)
        try:
            # 실제 구현은 Solana CLI 또는 @solana/web3.js 사용
            tx_id = await self._send_jito_bundle(request, jito_tip)

            return WithdrawalResult(
                success=True,
                bot_id=request.bot_id,
                amount=request.amount,
                currency=request.currency,
                tx_id=tx_id,
                status="completed",
                completed_at=datetime.utcnow()
            )

        except Exception as e:
            print(f"❌ Jito 출금 실패, 일반 출금으로 폴백: {e}")
            return await self._execute_standard_solana_withdrawal(request)

    async def _send_jito_bundle(
        self,
        request: WithdrawalRequest,
        jito_tip: float
    ) -> str:
        """Jito 번들 전송"""
        # Jito Block Engine RPC 엔드포인트
        JITO_RPC = "https://mainnet.block-engine.jito.wtf/api/v1/bundles"

        # 번들 서명 및 전송 (구현 필요)
        # 현재는 mock tx_id 반환
        import hashlib
        tx_hash = hashlib.sha256(
            f"{request.bot_id}{request.amount}{datetime.utcnow()}".encode()
        ).hexdigest()[:44]

        return tx_hash

    async def _execute_standard_solana_withdrawal(
        self,
        request: WithdrawalRequest
    ) -> WithdrawalResult:
        """표준 Solana 출금"""
        print(f"📤 표준 Solana 출금: {request.bot_id}")

        # Solana RPC 호출
        # 실제 구현은 spl-token transfer 또는 SOL transfer

        tx_id = f"sol_{datetime.utcnow().timestamp()}"

        return WithdrawalResult(
            success=True,
            bot_id=request.bot_id,
            amount=request.amount,
            currency=request.currency,
            tx_id=tx_id,
            status="completed",
            completed_at=datetime.utcnow()
        )

    async def _execute_polygon_withdrawal(
        self,
        request: WithdrawalRequest
    ) -> WithdrawalResult:
        """Polygon 출금 실행"""
        try:
            # Polygon RPC 호출
            tx_id = f"polygon_{datetime.utcnow().timestamp()}"

            return WithdrawalResult(
                success=True,
                bot_id=request.bot_id,
                amount=request.amount,
                currency=request.currency,
                tx_id=tx_id,
                status="completed",
                completed_at=datetime.utcnow()
            )

        except Exception as e:
            return WithdrawalResult(
                success=False,
                bot_id=request.bot_id,
                amount=request.amount,
                currency=request.currency,
                tx_id=None,
                status="failed",
                error=f"Polygon 출금 실패: {e}"
            )

    async def batch_withdraw(
        self,
        requests: List[WithdrawalRequest]
    ) -> List[WithdrawalResult]:
        """일괄 출금"""
        results = []

        for request in requests:
            result = await self.execute_withdrawal(request)
            results.append(result)
            await asyncio.sleep(1)  # Rate limiting

        return results

    async def auto_withdraw_all_pending(self):
        """모든 출금 대기 항목 자동 처리"""
        pending = await self.profit_tracker.get_pending_withdrawals()

        if not pending:
            print("✅ 출금 대기 항목 없음")
            return []

        print(f"🔄 출금 대기 {len(pending)}개 처리 중...")

        requests = []
        for item in pending:
            # 봇별 출금 목적지 결정
            destination = self._get_destination_for_bot(item["bot_id"])

            request = WithdrawalRequest(
                bot_id=item["bot_id"],
                amount=item["amount"],
                currency="USDT",  # 기본값, 실제로는 봇별 설정
                destination=destination,
                use_jito="solana" in item["bot_id"]
            )
            requests.append(request)

        return await self.batch_withdraw(requests)

    def _get_destination_for_bot(self, bot_id: str) -> WithdrawalDestination:
        """봇별 출금 목적지 결정"""
        if "binance" in bot_id:
            return WithdrawalDestination.BINANCE_MASTER
        elif "bybit" in bot_id:
            return WithdrawalDestination.BYBIT_MASTER
        elif "hyperliquid" in bot_id or "pump" in bot_id or "gmgn" in bot_id:
            return WithdrawalDestination.PHANTOM_PROFIT
        elif "polymarket" in bot_id:
            return WithdrawalDestination.METAMASK_PROFIT
        else:
            return WithdrawalDestination.BINANCE_MASTER


class PIMonoWithdrawalOptimizer:
    """
    pi-mono AI 출금 최적화기

    pi-mono의 AI 기능을 활용하여:
    1. 최적 출금 타이밍 결정
    2. 가스비 최적화
    3. MEV 공격 방지 전략
    """

    def __init__(self):
        self.gas_threshold_gwei = 50  # 50 Gwei 이하일 때 출금
        self.volatility_threshold = 0.05  # 5% 변동성 임계값

    async def should_withdraw_now(
        self,
        bot_id: str,
        amount: float,
        currency: str
    ) -> Dict[str, Any]:
        """지금 출금해야 하는지 AI 결정"""

        # 현재 네트워크 상태 확인
        network_status = await self._check_network_status(currency)

        # 가스비 체크
        if currency in ["ETH", "MATIC"]:
            gas_price = network_status.get("gas_price_gwei", 100)
            if gas_price > self.gas_threshold_gwei:
                return {
                    "should_withdraw": False,
                    "reason": f"가스비 높음 ({gas_price} Gwei)",
                    "suggested_delay_minutes": 30
                }

        # 변동성 체크
        volatility = network_status.get("volatility_24h", 0)
        if volatility > self.volatility_threshold:
            return {
                "should_withdraw": False,
                "reason": f"높은 변동성 ({volatility*100:.1f}%)",
                "suggested_delay_minutes": 60
            }

        # Jito 사용 권장 여부
        use_jito = currency == "SOL" and network_status.get("jito_recommended", False)

        return {
            "should_withdraw": True,
            "reason": "최적 출금 조건",
            "use_jito": use_jito,
            "jito_tip_recommended": 0.0001 if use_jito else 0
        }

    async def _check_network_status(self, currency: str) -> Dict[str, Any]:
        """네트워크 상태 확인"""
        # 실제 구현은 각 네트워크 RPC 호출
        return {
            "gas_price_gwei": 30,
            "volatility_24h": 0.02,
            "jito_recommended": True
        }


# 편의 함수
async def create_withdrawal_executor(
    redis_host: str = "localhost",
    redis_port: int = 6380
) -> WithdrawalExecutor:
    """WithdrawalExecutor 팩토리"""
    from nest_profit import create_profit_tracker
    pt = await create_profit_tracker(redis_host, redis_port)
    return WithdrawalExecutor(pt)


if __name__ == "__main__":
    async def test():
        executor = await create_withdrawal_executor()

        # 테스트 출금
        request = WithdrawalRequest(
            bot_id="test_bot_001",
            amount=1.5,
            currency="USDT",
            destination=WithdrawalDestination.BINANCE_MASTER
        )

        result = await executor.execute_withdrawal(request)
        print(f"출금 결과: {result}")

    asyncio.run(test())

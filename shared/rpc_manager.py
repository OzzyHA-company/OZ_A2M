"""
RPC Failover & Load Balancing Manager
다중 RPC 엔드포인트 관리 및 자동 failover 시스템
"""

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Callable, Any
from enum import Enum
import aiohttp
import logging

logger = logging.getLogger(__name__)


class RPCStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass
class RPCEndpoint:
    """RPC 엔드포인트 설정"""
    name: str
    http_url: str
    ws_url: Optional[str] = None
    priority: int = 1  # 낮을수록 높은 우선순위
    auth: Optional[Dict] = None  # {username, password} for Chainstack
    timeout: float = 5.0

    # 상태 추적
    status: RPCStatus = RPCStatus.UNKNOWN
    last_check: float = 0.0
    latency_ms: float = 0.0
    failure_count: int = 0
    success_count: int = 0
    last_error: Optional[str] = None


class RPCManager:
    """
    다중 RPC 엔드포인트 관리자
    - 우선순위 기반 primary selection
    - 자동 failover
    - 헬스체크 및 상태 모니터링
    - 회복 시 자동 primary 복귀
    """

    def __init__(
        self,
        endpoints: List[RPCEndpoint],
        health_check_interval: float = 30.0,
        max_failures: int = 3,
        recovery_threshold: int = 2
    ):
        self.endpoints = {e.name: e for e in endpoints}
        self.sorted_endpoints = sorted(endpoints, key=lambda e: e.priority)
        self.health_check_interval = health_check_interval
        self.max_failures = max_failures
        self.recovery_threshold = recovery_threshold

        self._current_primary: Optional[str] = None
        self._health_check_task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        """RPC 매니저 시작 및 헬스체크 루프 실행"""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )

        # 초기 헬스체크
        await self._check_all_endpoints()

        # 백그라운드 헬스체크 시작
        self._health_check_task = asyncio.create_task(
            self._health_check_loop()
        )

        logger.info(f"RPC Manager started. Primary: {self._current_primary}")

    async def stop(self):
        """RPC 매니저 종료"""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        if self._session:
            await self._session.close()

        logger.info("RPC Manager stopped")

    def get_primary(self) -> Optional[RPCEndpoint]:
        """현재 primary 엔드포인트 반환"""
        if self._current_primary:
            return self.endpoints.get(self._current_primary)
        return None

    def get_healthy_endpoints(self) -> List[RPCEndpoint]:
        """healthy 상태의 엔드포인트 목록 반환 (우선순위 순)"""
        healthy = [
            e for e in self.sorted_endpoints
            if e.status in (RPCStatus.HEALTHY, RPCStatus.DEGRADED)
        ]
        return healthy

    async def call(
        self,
        method: str,
        params: Optional[List] = None,
        retry_count: int = 3,
        fallback_to_any: bool = True
    ) -> Dict[str, Any]:
        """
        JSON-RPC 호출 with automatic failover

        Args:
            method: RPC 메서드명
            params: RPC 파라미터
            retry_count: 재시도 횟수
            fallback_to_any: primary 실패 시 다른 엔드포인트 시도
        """
        endpoints_to_try = self._get_endpoints_to_try(fallback_to_any)

        last_error = None

        for endpoint in endpoints_to_try[:retry_count]:
            try:
                result = await self._call_single(endpoint, method, params)

                # 성공 시 endpoint 상태 업데이트
                endpoint.success_count += 1
                endpoint.failure_count = max(0, endpoint.failure_count - 1)

                # 원래 primary가 아닌데 성공했으면 체크
                if endpoint.name != self._current_primary:
                    await self._evaluate_primary_switch()

                return result

            except Exception as e:
                last_error = e
                endpoint.failure_count += 1
                endpoint.last_error = str(e)

                # 실패 임계값 초과 시 상태 변경
                if endpoint.failure_count >= self.max_failures:
                    endpoint.status = RPCStatus.DOWN
                    logger.warning(
                        f"RPC endpoint {endpoint.name} marked as DOWN"
                    )

                logger.warning(
                    f"RPC call failed on {endpoint.name}: {e}"
                )

        # 모든 시도 실패
        raise RPCError(
            f"All RPC endpoints failed. Last error: {last_error}"
        )

    def _get_endpoints_to_try(self, fallback: bool) -> List[RPCEndpoint]:
        """시도할 엔드포인트 목록 생성"""
        healthy = self.get_healthy_endpoints()

        if not healthy:
            # healthy가 없으면 모든 것을 시도 (마지막 수단)
            return list(self.sorted_endpoints)

        if not fallback:
            # primary만
            primary = self.get_primary()
            return [primary] if primary else healthy[:1]

        # 우선순위 순으로 정렬된 healthy 엔드포인트
        return healthy

    async def _call_single(
        self,
        endpoint: RPCEndpoint,
        method: str,
        params: Optional[List]
    ) -> Dict[str, Any]:
        """단일 엔드포인트에 RPC 호출"""
        if not self._session:
            raise RPCError("RPC Manager not started")

        payload = {
            "jsonrpc": "2.0",
            "id": random.randint(1, 1000000),
            "method": method,
            "params": params or []
        }

        headers = {"Content-Type": "application/json"}

        # Chainstack 인증 처리
        if endpoint.auth:
            import aiohttp_basicauth
            auth = aiohttp_basicauth.BasicAuth(
                endpoint.auth["username"],
                endpoint.auth["password"]
            )
        else:
            auth = None

        start_time = time.time()

        async with self._session.post(
            endpoint.http_url,
            json=payload,
            headers=headers,
            auth=auth,
            timeout=aiohttp.ClientTimeout(total=endpoint.timeout)
        ) as response:
            response.raise_for_status()
            result = await response.json()

            latency = (time.time() - start_time) * 1000
            endpoint.latency_ms = latency

            if "error" in result:
                raise RPCError(f"RPC error: {result['error']}")

            return result

    async def _check_all_endpoints(self):
        """모든 엔드포인트 헬스체크"""
        check_tasks = [
            self._check_endpoint(endpoint)
            for endpoint in self.endpoints.values()
        ]
        await asyncio.gather(*check_tasks, return_exceptions=True)

    async def _check_endpoint(self, endpoint: RPCEndpoint):
        """단일 엔드포인트 헬스체크"""
        try:
            # Solana: getHealth, Ethereum: eth_blockNumber 등
            # 여기서는 간단한 연결 테스트
            start_time = time.time()

            async with self._session.post(
                endpoint.http_url,
                json={"jsonrpc": "2.0", "id": 1, "method": "getHealth"},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                await response.json()

            latency = (time.time() - start_time) * 1000
            endpoint.latency_ms = latency
            endpoint.last_check = time.time()

            # 지연시간에 따른 상태 결정
            if latency < 100:
                new_status = RPCStatus.HEALTHY
            elif latency < 500:
                new_status = RPCStatus.DEGRADED
            else:
                new_status = RPCStatus.DOWN

            # 회복 로직
            if (endpoint.status == RPCStatus.DOWN and
                new_status in (RPCStatus.HEALTHY, RPCStatus.DEGRADED)):
                endpoint.failure_count = max(
                    0, endpoint.failure_count - self.recovery_threshold
                )

            endpoint.status = new_status
            endpoint.last_error = None

        except Exception as e:
            endpoint.status = RPCStatus.DOWN
            endpoint.last_error = str(e)
            endpoint.failure_count += 1
            logger.debug(f"Health check failed for {endpoint.name}: {e}")

    async def _health_check_loop(self):
        """백그라운드 헬스체크 루프"""
        while True:
            try:
                await asyncio.sleep(self.health_check_interval)
                await self._check_all_endpoints()
                await self._evaluate_primary_switch()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check loop error: {e}")

    async def _evaluate_primary_switch(self):
        """Primary 엔드포인트 전환 평가"""
        healthy = self.get_healthy_endpoints()

        if not healthy:
            self._current_primary = None
            return

        # 현재 primary가 healthy면 유지
        current = self.get_primary()
        if current and current.status in (RPCStatus.HEALTHY, RPCStatus.DEGRADED):
            # 더 높은 우선순위가 healthy면 전환
            for ep in healthy:
                if ep.priority < current.priority:
                    logger.info(
                        f"Switching primary from {current.name} to {ep.name} "
                        f"(higher priority)"
                    )
                    self._current_primary = ep.name
                    return
            return

        # 현재 primary가 unhealthy면 가장 우선순위 높은 healthy로 전환
        new_primary = healthy[0]
        if self._current_primary != new_primary.name:
            logger.info(
                f"Failover: {self._current_primary} -> {new_primary.name}"
            )
            self._current_primary = new_primary.name

    def get_status(self) -> Dict[str, Any]:
        """현재 상태 보고서"""
        return {
            "primary": self._current_primary,
            "endpoints": [
                {
                    "name": e.name,
                    "status": e.status.value,
                    "latency_ms": round(e.latency_ms, 2),
                    "failures": e.failure_count,
                    "successes": e.success_count,
                    "priority": e.priority
                }
                for e in self.sorted_endpoints
            ]
        }


class RPCError(Exception):
    """RPC 관련 예외"""
    pass


# =============================================================================
# Solana 특화 RPC 매니저
# =============================================================================

class SolanaRPCManager(RPCManager):
    """Solana 특화 RPC 매니저"""

    async def get_slot(self) -> int:
        """현재 슬롯 번호 조회"""
        result = await self.call("getSlot")
        return result.get("result", 0)

    async def get_block_height(self) -> int:
        """현재 블록 높이 조회"""
        result = await self.call("getBlockHeight")
        return result.get("result", 0)

    async def get_balance(self, pubkey: str) -> int:
        """계정 잔액 조회 (lamports)"""
        result = await self.call("getBalance", [pubkey])
        return result.get("result", {}).get("value", 0)

    async def send_transaction(self, signed_tx: str) -> str:
        """트랜잭션 전송"""
        result = await self.call(
            "sendTransaction",
            [signed_tx, {"encoding": "base64"}]
        )
        return result.get("result", "")


# =============================================================================
# 설정 로드 헬퍼
# =============================================================================

def load_from_env() -> List[RPCEndpoint]:
    """환경변수에서 RPC 설정 로드"""
    import os

    endpoints = []

    # Alchemy
    if os.getenv("ALCHEMY_SOLANA_HTTP"):
        endpoints.append(RPCEndpoint(
            name="alchemy_solana",
            http_url=os.getenv("ALCHEMY_SOLANA_HTTP"),
            priority=1
        ))

    # Chainstack
    if os.getenv("CHAINSTACK_SOLANA_HTTP"):
        endpoints.append(RPCEndpoint(
            name="chainstack_solana",
            http_url=os.getenv("CHAINSTACK_SOLANA_HTTP"),
            ws_url=os.getenv("CHAINSTACK_SOLANA_WSS"),
            priority=2,
            auth={
                "username": os.getenv("CHAINSTACK_USERNAME", ""),
                "password": os.getenv("CHAINSTACK_PASSWORD", "")
            }
        ))

    # Ankr
    if os.getenv("ANKR_SOLANA_HTTP"):
        endpoints.append(RPCEndpoint(
            name="ankr_solana",
            http_url=os.getenv("ANKR_SOLANA_HTTP"),
            priority=3
        ))

    return endpoints


# =============================================================================
# 사용 예시
# =============================================================================

async def main():
    """테스트/예시 코드"""
    logging.basicConfig(level=logging.INFO)

    # 방법 1: 직접 설정
    endpoints = [
        RPCEndpoint(
            name="alchemy",
            http_url="https://solana-mainnet.g.alchemy.com/v2/KEY",
            priority=1
        ),
        RPCEndpoint(
            name="chainstack",
            http_url="https://solana-mainnet.core.chainstack.com/ID",
            ws_url="wss://solana-mainnet.core.chainstack.com/ID",
            priority=2,
            auth={"username": "user", "password": "pass"}
        ),
        RPCEndpoint(
            name="ankr",
            http_url="https://rpc.ankr.com/solana/KEY",
            priority=3
        )
    ]

    # 방법 2: 환경변수에서 로드
    # endpoints = load_from_env()

    # 매니저 생성 및 시작
    manager = SolanaRPCManager(endpoints)
    await manager.start()

    try:
        # 사용 예시
        slot = await manager.get_slot()
        print(f"Current slot: {slot}")

        # 상태 확인
        status = manager.get_status()
        print(f"Status: {status}")

        # 일반 RPC 호출
        result = await manager.call("getHealth")
        print(f"Health: {result}")

    finally:
        await manager.stop()


if __name__ == "__main__":
    asyncio.run(main())

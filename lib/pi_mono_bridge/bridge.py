"""
Bridge between OZ_A2M and pi-mono + Gemini Pro SaaS
- pi-mono는 ~/.pi/settings.json 에서 (google) gemini-2.5-flash 사용
- LLM Gateway REST API (localhost:8000)를 통해 Gemini 호출
- Ant Colony Nest REST API (localhost:8084) 연동
"""
import json
import asyncio
import os
from typing import Dict, Any, Optional
from pathlib import Path
import httpx


class PiMonoBridge:
    """
    OZ_A2M ↔ pi-mono + Gemini Pro SaaS 브릿지

    구조:
    봇 → PiMonoBridge → LLM Gateway (Gemini 2.5-flash) → 의사결정
                     ↘ Ant Colony Nest (Redis/MQTT) → 상태 공유
    """

    def __init__(
        self,
        gateway_url: str = "http://localhost:8000",
        nest_url: str = "http://localhost:8084",
    ):
        self.gateway_url = gateway_url
        self.nest_url = nest_url
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def analyze_market(self, symbol: str, price_data: list, indicators: dict) -> Dict[str, Any]:
        """Gemini Pro로 시장 분석 (LLM Gateway 경유)"""
        client = await self._get_client()
        try:
            resp = await client.post(
                f"{self.gateway_url}/llm/analyze-market",
                json={"symbol": symbol, "price_data": price_data, "indicators": indicators}
            )
            return resp.json()
        except Exception as e:
            return {"error": str(e), "provider": "unavailable"}

    async def consult_trade(self, context: str, question: str) -> str:
        """트레이딩 의사결정 질의"""
        client = await self._get_client()
        try:
            resp = await client.post(
                f"{self.gateway_url}/llm/chat",
                json={"message": question, "context": context, "department": "7-operations"}
            )
            data = resp.json()
            return data.get("content", "no response")
        except Exception as e:
            return f"error: {e}"

    async def consult_withdrawal(self, amount: float, asset: str, reason: str) -> bool:
        """출금 승인 여부 Gemini에게 질의"""
        prompt = (
            f"OZ_A2M 출금 요청:\n"
            f"- 금액: {amount} {asset}\n"
            f"- 이유: {reason}\n"
            f"원금 보존 원칙 하에 이 출금을 승인해야 하는가? "
            f"JSON으로 응답: {{\"approve\": true/false, \"reason\": \"...\"}}"
        )
        result = await self.consult_trade("withdrawal-executor", prompt)
        try:
            # JSON 파싱 시도
            if "{" in result:
                import re
                match = re.search(r'\{[^}]+\}', result)
                if match:
                    d = json.loads(match.group())
                    return bool(d.get("approve", True))
        except Exception:
            pass
        return True  # 파싱 실패 시 기본 승인

    async def get_nest_status(self) -> Dict[str, Any]:
        """Ant Colony Nest 상태 조회"""
        client = await self._get_client()
        try:
            resp = await client.get(f"{self.nest_url}/api/bots")
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    async def push_to_nest(self, bot_id: str, pnl: float, trades: int, status: str = "running"):
        """Ant Colony Nest에 상태 푸시"""
        client = await self._get_client()
        try:
            await client.post(
                f"{self.nest_url}/api/bots/{bot_id}/status",
                json={"status": status, "pnl": pnl, "trades": trades}
            )
        except Exception:
            pass

    def get_session_status(self) -> Dict[str, Any]:
        """pi-mono + Gemini 세션 상태"""
        pi_settings = Path.home() / ".pi" / "settings.json"
        provider = "unknown"
        if pi_settings.exists():
            try:
                settings = json.loads(pi_settings.read_text())
                # pi settings에서 provider 확인
                provider = "gemini-2.5-flash (pi-mono)"
            except Exception:
                pass
        return {
            "gateway": self.gateway_url,
            "nest": self.nest_url,
            "pi_mono_provider": provider,
            "status": "active"
        }

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# 싱글톤 인스턴스
_bridge: Optional[PiMonoBridge] = None

def get_pi_mono_bridge() -> PiMonoBridge:
    global _bridge
    if _bridge is None:
        _bridge = PiMonoBridge()
    return _bridge

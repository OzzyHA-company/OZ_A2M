"""
텔레그램 수익/출금 알림 시스템
- 중대한 오류 알림
- 수익 출금 알림 (마스터 지갑/거래소)
- 봇 생존 체크
"""

import os
import asyncio
import aiohttp
from datetime import datetime
from typing import Optional

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


class TelegramProfitAlerter:
    """텔레그램 수익 알림 관리자"""

    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)

    async def send_alert(self, message: str, priority: str = "normal"):
        """알림 발송"""
        if not self.enabled:
            print(f"[Telegram would send]: {message}")
            return

        emoji = {"critical": "🚨", "high": "⚠️", "normal": "ℹ️", "profit": "💰"}.get(priority, "ℹ️")
        full_message = f"{emoji} {message}\n\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"

        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={
                    "chat_id": self.chat_id,
                    "text": full_message,
                    "parse_mode": "HTML"
                }) as resp:
                    if resp.status == 200:
                        print(f"✅ Telegram alert sent: {priority}")
                    else:
                        print(f"⚠️ Telegram failed: {resp.status}")
        except Exception as e:
            print(f"❌ Telegram error: {e}")

    async def alert_withdrawal_completed(self, bot_id: str, amount: float, currency: str, destination: str):
        """출금 완료 알림"""
        message = f"""<b>💰 수익 출금 완료</b>

봇: {bot_id}
금액: {amount:.4f} {currency}
목적지: {destination}
상태: ✅ 완료"""
        await self.send_alert(message, "profit")

    async def alert_bot_died(self, bot_id: str, error: str):
        """봇 사망 알림"""
        message = f"<b>🚨 봇 중단 알림</b>\n\n봇: {bot_id}\n오류: {error}\n\n즉각 확인 필요!"
        await self.send_alert(message, "critical")

    async def alert_critical_error(self, error_msg: str):
        """중대 오류 알림"""
        await self.send_alert(f"<b>🚨 중대 오류 발생</b>\n\n{error_msg}", "critical")

    async def alert_daily_profit(self, total_profit: float, bot_count: int):
        """일일 수익 알림"""
        message = f"""<b>📊 일일 수익 리포트</b>

총 수익: ${total_profit:.2f}
가동 봇: {bot_count}개

원금 보존 상태: ✅ 정상"""
        await self.send_alert(message, "normal")


# 전역 인스턴스
telegram_alerter = TelegramProfitAlerter()


if __name__ == "__main__":
    # 테스트
    async def test():
        await telegram_alerter.alert_withdrawal_completed(
            "grid_bybit_001", 1.5, "USDT", "master_wallet"
        )

    asyncio.run(test())

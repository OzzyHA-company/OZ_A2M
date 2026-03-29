"""
OZ_A2M 제6부서: 운영관리팀 - Telegram 알림 봇

실거래 신호, 손익 알림, 시스템 상태 알림을 Telegram으로 전송
긴급 킬스위치 명령 수신 및 처리
"""

import os
import asyncio
import logging
from typing import Optional, Dict, Any, Callable
from datetime import datetime
from decimal import Decimal

from lib.core import get_logger
from occore.security.acl import AccessControl, PermissionLevel, AccessDenied

logger = get_logger(__name__)


class TelegramNotifier:
    """Telegram 알림 발송기"""

    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        acl: Optional[AccessControl] = None
    ):
        self.token = token or os.getenv("OC_TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("OC_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
        self.acl = acl or AccessControl()
        self._bot: Optional[Any] = None
        self._command_handlers: Dict[str, Callable] = {}

    async def initialize(self) -> bool:
        """봇 초기화"""
        if not self.token or not self.chat_id:
            logger.error("Telegram token or chat ID not configured")
            return False

        try:
            from aiogram import Bot, Dispatcher
            from aiogram.types import BotCommand

            self._bot = Bot(token=self.token)
            self._dp = Dispatcher()

            # 명령어 핸들러 등록
            self._setup_handlers()

            # 봇 명령어 설정
            await self._bot.set_my_commands([
                BotCommand(command="status", description="시스템 상태 조회"),
                BotCommand(command="profit", description="손익 현황"),
                BotCommand(command="bots", description="봇 상태 조회"),
                BotCommand(command="start_bot", description="봇 시작"),
                BotCommand(command="stop_bot", description="봇 중지"),
                BotCommand(command="killswitch", description="긴급 정지 (모든 봇)"),
                BotCommand(command="help", description="도움말"),
            ])

            logger.info("Telegram bot initialized")
            return True

        except ImportError:
            logger.error("aiogram not installed. Run: pip install aiogram")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}")
            return False

    def _setup_handlers(self):
        """명령어 핸들러 설정"""
        from aiogram import types

        @self._dp.message_handler(commands=["start", "help"])
        async def cmd_help(message: types.Message):
            """도움말 명령"""
            if not self._check_permission(message.from_user.id, "help"):
                await message.reply("⛔ 권한이 없습니다.")
                return

            help_text = """
🤖 <b>OZ_A2M Trading Bot</b>

📊 <b>조회 명령</b>
/status - 시스템 상태
/profit - 손익 현황
/bots - 봇 상태 조회

⚙️ <b>제어 명령</b>
/start_bot &lt;bot_id&gt; - 봇 시작
/stop_bot &lt;bot_id&gt; - 봇 중지

🚨 <b>긴급 명령</b>
/killswitch - 모든 봇 긴급 정지

💡 ID 확인: /myid
            """
            await message.reply(help_text, parse_mode="HTML")

        @self._dp.message_handler(commands=["myid"])
        async def cmd_myid(message: types.Message):
            """사용자 ID 확인"""
            await message.reply(f"🆔 Your ID: <code>{message.from_user.id}</code>", parse_mode="HTML")

        @self._dp.message_handler(commands=["status"])
        async def cmd_status(message: types.Message):
            """시스템 상태 조회"""
            if not self._check_permission(message.from_user.id, "status"):
                await message.reply("⛔ 권한이 없습니다.")
                return

            status = await self._get_system_status()
            await message.reply(status, parse_mode="HTML")

        @self._dp.message_handler(commands=["profit"])
        async def cmd_profit(message: types.Message):
            """손익 조회"""
            if not self._check_permission(message.from_user.id, "profit"):
                await message.reply("⛔ 권한이 없습니다.")
                return

            profit = await self._get_profit_status()
            await message.reply(profit, parse_mode="HTML")

        @self._dp.message_handler(commands=["bots"])
        async def cmd_bots(message: types.Message):
            """봇 상태 조회"""
            if not self._check_permission(message.from_user.id, "bot_status"):
                await message.reply("⛔ 권한이 없습니다.")
                return

            status = await self._get_bot_status()
            await message.reply(status, parse_mode="HTML")

        @self._dp.message_handler(commands=["start_bot"])
        async def cmd_start_bot(message: types.Message):
            """봇 시작"""
            if not self._check_permission(message.from_user.id, "bot_start"):
                await message.reply("⛔ 권한이 없습니다.")
                return

            args = message.get_args()
            if not args:
                await message.reply("사용법: /start_bot &lt;bot_id&gt;")
                return

            result = await self._start_bot(args)
            await message.reply(result)

        @self._dp.message_handler(commands=["stop_bot"])
        async def cmd_stop_bot(message: types.Message):
            """봇 중지"""
            if not self._check_permission(message.from_user.id, "bot_stop"):
                await message.reply("⛔ 권한이 없습니다.")
                return

            args = message.get_args()
            if not args:
                await message.reply("사용법: /stop_bot &lt;bot_id&gt;")
                return

            result = await self._stop_bot(args)
            await message.reply(result)

        @self._dp.message_handler(commands=["killswitch"])
        async def cmd_killswitch(message: types.Message):
            """긴급 정지"""
            if not self._check_permission(message.from_user.id, "killswitch"):
                await message.reply("⛔ 권한이 없습니다.")
                return

            # 확인 메시지
            await message.reply(
                "🚨 <b>긴급 정지</b>\n\n"
                "모든 봇을 즉시 중지하시겠습니까?\n"
                "확인하려면 <code>/confirm_killswitch</code>를 입력하세요.",
                parse_mode="HTML"
            )

        @self._dp.message_handler(commands=["confirm_killswitch"])
        async def cmd_confirm_killswitch(message: types.Message):
            """긴급 정지 확인"""
            if not self._check_permission(message.from_user.id, "killswitch"):
                await message.reply("⛔ 권한이 없습니다.")
                return

            result = await self._emergency_stop()
            await message.reply(f"🚨 {result}")

    def _check_permission(self, user_id: int, command: str) -> bool:
        """사용자 권한 확인"""
        try:
            user_id_str = str(user_id)
            # 환경변수에서 허용된 사용자 로드
            allowed_ids = os.getenv("ALLOWED_TELEGRAM_IDS", self.chat_id)

            if user_id_str not in allowed_ids.split(","):
                logger.warning(f"Unauthorized access attempt: {user_id}")
                return False

            return True
        except Exception as e:
            logger.error(f"Permission check error: {e}")
            return False

    async def _get_system_status(self) -> str:
        """시스템 상태 조회"""
        # TODO: 실제 시스템 상태 연동
        return """
✅ <b>System Status</b>

🖥️ CPU: 45%
💾 Memory: 32%
💽 Disk: 12%

📡 MQTT: Connected
🗄️ Redis: Connected
📊 Database: Connected
        """

    async def _get_profit_status(self) -> str:
        """손익 상태 조회"""
        # TODO: 실제 손익 데이터 연동
        return """
💰 <b>Profit Status</b>

Today's PnL: +$125.50
Total PnL: +$1,250.30
Win Rate: 62.5%

📈 Open Positions: 3
📉 Closed Today: 8
        """

    async def _get_bot_status(self) -> str:
        """봇 상태 조회"""
        # TODO: 실제 봇 상태 연동
        return """
🤖 <b>Bot Status</b>

✅ Scalper-01: Running
✅ TrendFollower-01: Running
⏸️ MarketMaker-01: Paused
✅ Arbitrage-01: Running
        """

    async def _start_bot(self, bot_id: str) -> str:
        """봇 시작"""
        # TODO: 실제 봇 제어 연동
        logger.info(f"Starting bot: {bot_id}")
        return f"✅ Bot '{bot_id}' started"

    async def _stop_bot(self, bot_id: str) -> str:
        """봇 중지"""
        # TODO: 실제 봇 제어 연동
        logger.info(f"Stopping bot: {bot_id}")
        return f"⏸️ Bot '{bot_id}' stopped"

    async def _emergency_stop(self) -> str:
        """긴급 정지"""
        # TODO: 실제 긴급 정지 연동
        logger.critical("EMERGENCY STOP triggered via Telegram")
        return "🚨 Emergency stop executed. All bots halted."

    # === 알림 발송 메서드 ===

    async def send_signal_alert(
        self,
        symbol: str,
        signal_type: str,
        price: float,
        confidence: float,
        verification_status: str = "pending"
    ):
        """트레이딩 신호 알림"""
        if not self._bot:
            return

        emoji = "🟢" if signal_type == "buy" else "🔴" if signal_type == "sell" else "⚪"

        message = f"""
{emoji} <b>Trading Signal</b>

📊 Symbol: <code>{symbol}</code>
💡 Type: {signal_type.upper()}
💰 Price: ${price:,.2f}
📈 Confidence: {confidence*100:.1f}%
✅ Status: {verification_status}
⏰ {datetime.now().strftime('%H:%M:%S')}
        """

        try:
            await self._bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send signal alert: {e}")

    async def send_trade_executed(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        order_id: str
    ):
        """거래 체결 알림"""
        if not self._bot:
            return

        emoji = "🟢" if side == "buy" else "🔴"

        message = f"""
{emoji} <b>Trade Executed</b>

📊 Symbol: <code>{symbol}</code>
🔀 Side: {side.upper()}
📦 Amount: {amount:.6f}
💰 Price: ${price:,.2f}
💵 Total: ${amount * price:,.2f}
🆔 Order: <code>{order_id[:8]}...</code>
⏰ {datetime.now().strftime('%H:%M:%S')}
        """

        try:
            await self._bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send trade alert: {e}")

    async def send_pnl_report(
        self,
        daily_pnl: Decimal,
        total_pnl: Decimal,
        win_rate: float,
        open_positions: int
    ):
        """손익 리포트 알림"""
        if not self._bot:
            return

        pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"

        message = f"""
{pnl_emoji} <b>Daily PnL Report</b>

📅 Date: {datetime.now().strftime('%Y-%m-%d')}
💰 Daily PnL: ${daily_pnl:,.2f}
💵 Total PnL: ${total_pnl:,.2f}
📊 Win Rate: {win_rate*100:.1f}%
📈 Open Positions: {open_positions}
        """

        try:
            await self._bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send PnL report: {e}")

    async def send_system_alert(self, level: str, message: str):
        """시스템 알림"""
        if not self._bot:
            return

        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "🚨",
            "critical": "🔥"
        }
        emoji = emoji_map.get(level, "ℹ️")

        text = f"""
{emoji} <b>System Alert [{level.upper()}]</b>

{message}

⏰ {datetime.now().strftime('%H:%M:%S')}
        """

        try:
            await self._bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send system alert: {e}")

    async def start_polling(self):
        """봇 폴링 시작"""
        if not self._bot:
            logger.error("Bot not initialized")
            return

        logger.info("Starting Telegram bot polling...")
        await self._dp.start_polling(self._bot)

    async def stop(self):
        """봇 중지"""
        if self._bot:
            await self._bot.session.close()
            logger.info("Telegram bot stopped")


# 전역 인스턴스
_notifier_instance: Optional[TelegramNotifier] = None


def get_telegram_notifier(
    token: Optional[str] = None,
    chat_id: Optional[str] = None
) -> TelegramNotifier:
    """전역 TelegramNotifier 인스턴스 가져오기"""
    global _notifier_instance
    if _notifier_instance is None:
        _notifier_instance = TelegramNotifier(token=token, chat_id=chat_id)
    return _notifier_instance


async def main():
    """메인 실행"""
    logging.basicConfig(level=logging.INFO)

    notifier = get_telegram_notifier()

    if not await notifier.initialize():
        logger.error("Failed to initialize notifier")
        return

    # 테스트 알림 발송
    await notifier.send_system_alert("info", "🚀 OZ_A2M Telegram Bot started!")

    # 폴링 시작
    await notifier.start_polling()


if __name__ == "__main__":
    asyncio.run(main())

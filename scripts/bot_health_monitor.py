#!/usr/bin/env python3
"""
봇 생존 체크 자동화 시스템
- 5분마다 모든 봇 프로세스 확인
- 죽은 봇 자동 재시작
- 텔레그램 알림 발송
"""

import asyncio
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.core.telegram_profit_alerts import telegram_alerter

# 봇 설정
BOTS = {
    "scalper_bybit_001": "department_7/src/bot/scalper.py",
    "dca_binance_001": "department_7/src/bot/dca_bot.py",
    "grid_binance_001": "department_7/src/bot/grid_bot.py",
    "grid_bybit_001": "department_7/src/bot/grid_bot_bybit.py",
    "funding_binance_bybit_001": "department_7/src/bot/funding_rate_bot.py",
    "triarb_binance_001": "department_7/src/bot/triangular_arb_bot.py",
    "hyperliquid_mm_001": "department_7/src/bot/hyperliquid_mm_bot.py",
    "polymarket_ai_001": "department_7/src/bot/polymarket_bot.py",
    "pump_sniper_001": "department_7/src/bot/pump_sniper_bot.py",
    "gmgn_copy_001": "department_7/src/bot/copy_trade_bot.py",
}

LOG_DIR = Path("logs")


async def check_bot_process(bot_id: str, script_path: str) -> bool:
    """봇 프로세스 확인"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"python3.*{script_path}"],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False


async def restart_bot(bot_id: str, script_path: str):
    """봇 재시작"""
    log_file = LOG_DIR / f"{bot_id}_live.log"
    cmd = f"nohup python3 {script_path} > {log_file} 2>&1 &"

    try:
        subprocess.Popen(cmd, shell=True)
        await asyncio.sleep(2)

        # 재시작 확인
        if await check_bot_process(bot_id, script_path):
            msg = f"✅ {bot_id} 재시작 성공"
            print(msg)
            await telegram_alerter.send_alert(msg, "high")
            return True
        else:
            msg = f"❌ {bot_id} 재시작 실패"
            print(msg)
            await telegram_alerter.alert_bot_died(bot_id, "재시작 실패")
            return False
    except Exception as e:
        await telegram_alerter.alert_bot_died(bot_id, str(e))
        return False


async def health_check_cycle():
    """건강 체크 사이클"""
    print(f"\n{'='*60}")
    print(f"🩺 봇 건강 체크 - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
    print('='*60)

    dead_bots = []
    alive_count = 0

    for bot_id, script_path in BOTS.items():
        is_alive = await check_bot_process(bot_id, script_path)

        if is_alive:
            print(f"  🟢 {bot_id}: 정상")
            alive_count += 1
        else:
            print(f"  🔴 {bot_id}: 중단됨 → 재시작 시도")
            dead_bots.append((bot_id, script_path))

    # 죽은 봇 재시작
    for bot_id, script_path in dead_bots:
        await restart_bot(bot_id, script_path)

    print(f"\n📊 결과: {alive_count}/{len(BOTS)} 정상, {len(dead_bots)} 재시작")

    # 전체 죽은 경우 긴급 알림
    if alive_count == 0 and len(dead_bots) > 0:
        await telegram_alerter.alert_critical_error(
            f"모든 봇({len(dead_bots)}개)이 중단되었습니다! 즉각 확인 필요!"
        )


async def main():
    """메인 모니터링 루프"""
    print("🤖 봇 생존 모니터링 시작 (5분 간격)")
    print("="*60)

    while True:
        try:
            await health_check_cycle()
        except Exception as e:
            print(f"❌ 모니터링 오류: {e}")
            await telegram_alerter.alert_critical_error(f"모니터링 시스템 오류: {e}")

        # 5분 대기
        await asyncio.sleep(300)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 모니터링 종료")

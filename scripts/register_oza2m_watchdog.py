#!/usr/bin/env python3
"""
OZ_A2M 봇 OpenClaw 워치독 등록 스크립트

사용법:
    python3 register_oza2m_watchdog.py

기능:
    - OZ_A2M의 11개 봇을 OpenClaw 워치독에 등록
    - 봇 상태 모니터링 (PID 파일, 하트비트 체크)
    - 자동 재시작 설정
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

# OpenClaw 경로
OPENCLAW_DIR = Path("/home/ozzy-claw/.openclaw")
WATCHDOG_STATE_FILE = OPENCLAW_DIR / "watchdog_oza2m_state.json"
PID_DIR = OPENCLAW_DIR / "pids"
PID_DIR.mkdir(parents=True, exist_ok=True)

# OZ_A2M 봇 설정
OZ_A2M_BOTS = [
    {
        "name": "grid_binance_001",
        "display_name": "Binance Grid Bot",
        "type": "stable",
        "pid_file": PID_DIR / "grid_binance_001.pid",
        "heartbeat_file": PID_DIR / "grid_binance_001.heartbeat",
        "log_file": "/home/ozzy-claw/OZ_A2M/logs/grid_binance_001.log",
        "restart_cmd": "cd /home/ozzy-claw/OZ_A2M && python3 -m department_7.src.bot.grid_bot &",
        "auto_restart": True,
    },
    {
        "name": "dca_binance_001",
        "display_name": "Binance DCA Bot",
        "type": "stable",
        "pid_file": PID_DIR / "dca_binance_001.pid",
        "heartbeat_file": PID_DIR / "dca_binance_001.heartbeat",
        "log_file": "/home/ozzy-claw/OZ_A2M/logs/dca_binance_001.log",
        "restart_cmd": "cd /home/ozzy-claw/OZ_A2M && python3 -m department_7.src.bot.dca_bot &",
        "auto_restart": True,
    },
    {
        "name": "triarb_binance_001",
        "display_name": "Triangular Arb Bot",
        "type": "stable",
        "pid_file": PID_DIR / "triarb_binance_001.pid",
        "heartbeat_file": PID_DIR / "triarb_binance_001.heartbeat",
        "log_file": "/home/ozzy-claw/OZ_A2M/logs/triarb_binance_001.log",
        "restart_cmd": "cd /home/ozzy-claw/OZ_A2M && python3 -m department_7.src.bot.triangular_arb_bot &",
        "auto_restart": True,
    },
    {
        "name": "funding_binance_bybit_001",
        "display_name": "Funding Rate Bot",
        "type": "stable",
        "pid_file": PID_DIR / "funding_binance_bybit_001.pid",
        "heartbeat_file": PID_DIR / "funding_binance_bybit_001.heartbeat",
        "log_file": "/home/ozzy-claw/OZ_A2M/logs/funding_binance_bybit_001.log",
        "restart_cmd": "cd /home/ozzy-claw/OZ_A2M && python3 -m department_7.src.bot.funding_rate_bot &",
        "auto_restart": True,
    },
    {
        "name": "grid_bybit_001",
        "display_name": "Bybit Grid Bot",
        "type": "stable",
        "pid_file": PID_DIR / "grid_bybit_001.pid",
        "heartbeat_file": PID_DIR / "grid_bybit_001.heartbeat",
        "log_file": "/home/ozzy-claw/OZ_A2M/logs/grid_bybit_001.log",
        "restart_cmd": "cd /home/ozzy-claw/OZ_A2M && python3 -c 'from department_7.src.bot.grid_bot import BinanceGridBot; import asyncio; b=BinanceGridBot(bot_id=\"grid_bybit_001\", exchange_id=\"bybit\"); asyncio.run(b.run())' &",
        "auto_restart": True,
    },
    {
        "name": "scalper_bybit_001",
        "display_name": "Bybit Scalping Bot",
        "type": "stable",
        "pid_file": PID_DIR / "scalper_bybit_001.pid",
        "heartbeat_file": PID_DIR / "scalper_bybit_001.heartbeat",
        "log_file": "/home/ozzy-claw/OZ_A2M/logs/scalper_bybit_001.log",
        "restart_cmd": "cd /home/ozzy-claw/OZ_A2M && python3 -m department_7.src.bot.scalper &",
        "auto_restart": True,
    },
    {
        "name": "hyperliquid_mm_001",
        "display_name": "Hyperliquid MM Bot",
        "type": "dopamine",
        "pid_file": PID_DIR / "hyperliquid_mm_001.pid",
        "heartbeat_file": PID_DIR / "hyperliquid_mm_001.heartbeat",
        "log_file": "/home/ozzy-claw/OZ_A2M/logs/hyperliquid_mm_001.log",
        "restart_cmd": "cd /home/ozzy-claw/OZ_A2M && python3 -m department_7.src.bot.hyperliquid_bot &",
        "auto_restart": True,
    },
    {
        "name": "ibkr_forecast_001",
        "display_name": "IBKR Forecast Bot",
        "type": "stable",
        "pid_file": PID_DIR / "ibkr_forecast_001.pid",
        "heartbeat_file": PID_DIR / "ibkr_forecast_001.heartbeat",
        "log_file": "/home/ozzy-claw/OZ_A2M/logs/ibkr_forecast_001.log",
        "restart_cmd": "cd /home/ozzy-claw/OZ_A2M && python3 -m department_7.src.bot.ibkr_forecast_bot &",
        "auto_restart": True,
    },
    {
        "name": "polymarket_ai_001",
        "display_name": "Polymarket AI Bot",
        "type": "stable",
        "pid_file": PID_DIR / "polymarket_ai_001.pid",
        "heartbeat_file": PID_DIR / "polymarket_ai_001.heartbeat",
        "log_file": "/home/ozzy-claw/OZ_A2M/logs/polymarket_ai_001.log",
        "restart_cmd": "cd /home/ozzy-claw/OZ_A2M && python3 -m department_7.src.bot.polymarket_bot &",
        "auto_restart": True,
    },
    {
        "name": "pump_sniper_001",
        "display_name": "Pump.fun Sniper",
        "type": "dopamine",
        "pid_file": PID_DIR / "pump_sniper_001.pid",
        "heartbeat_file": PID_DIR / "pump_sniper_001.heartbeat",
        "log_file": "/home/ozzy-claw/OZ_A2M/logs/pump_sniper_001.log",
        "restart_cmd": "cd /home/ozzy-claw/OZ_A2M && python3 -m department_7.src.bot.pump_sniper_bot &",
        "auto_restart": True,
    },
    {
        "name": "gmgn_copy_001",
        "display_name": "GMGN Copy Bot",
        "type": "dopamine",
        "pid_file": PID_DIR / "gmgn_copy_001.pid",
        "heartbeat_file": PID_DIR / "gmgn_copy_001.heartbeat",
        "log_file": "/home/ozzy-claw/OZ_A2M/logs/gmgn_copy_001.log",
        "restart_cmd": "cd /home/ozzy-claw/OZ_A2M && python3 -m department_7.src.bot.copy_trade_bot &",
        "auto_restart": True,
    },
    {
        "name": "run_all_bots",
        "display_name": "OZ_A2M Main Runner",
        "type": "master",
        "pid_file": PID_DIR / "run_all_bots.pid",
        "heartbeat_file": PID_DIR / "run_all_bots.heartbeat",
        "log_file": "/home/ozzy-claw/OZ_A2M/logs/run_all_bots.log",
        "restart_cmd": "cd /home/ozzy-claw/OZ_A2M/department_7/src/bot && python3 run_all_bots.py &",
        "auto_restart": True,
    },
]


def register_bots():
    """모든 OZ_A2M 봇을 OpenClaw 워치독에 등록"""
    print("=" * 60)
    print("🛡️ OZ_A2M 봇 OpenClaw 워치독 등록")
    print("=" * 60)

    # 상태 파일 로드/생성
    state = {}
    if WATCHDOG_STATE_FILE.exists():
        with open(WATCHDOG_STATE_FILE, 'r') as f:
            state = json.load(f)

    registered = []
    for bot in OZ_A2M_BOTS:
        bot_name = bot["name"]

        # PID 파일이 존재하면 읽기
        pid = None
        if bot["pid_file"].exists():
            try:
                pid = int(bot["pid_file"].read_text().strip())
                # 프로세스가 실제로 실행 중인지 확인
                try:
                    os.kill(pid, 0)
                except (ProcessLookupError, PermissionError):
                    pid = None
                    bot["pid_file"].unlink(missing_ok=True)
            except (ValueError, FileNotFoundError):
                pid = None

        # 상태 저장
        state[bot_name] = {
            "name": bot_name,
            "display_name": bot["display_name"],
            "type": bot["type"],
            "pid": pid,
            "pid_file": str(bot["pid_file"]),
            "heartbeat_file": str(bot["heartbeat_file"]),
            "log_file": bot["log_file"],
            "restart_cmd": bot["restart_cmd"],
            "auto_restart": bot["auto_restart"],
            "registered_at": datetime.now().isoformat(),
            "status": "running" if pid else "stopped",
        }

        registered.append(bot_name)
        status_icon = "🟢" if pid else "🔴"
        print(f"{status_icon} {bot['display_name']} ({bot_name})")

    # 상태 파일 저장
    with open(WATCHDOG_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

    print("=" * 60)
    print(f"✅ {len(registered)}개 봇 등록 완료")
    print(f"📁 상태 파일: {WATCHDOG_STATE_FILE}")
    print("=" * 60)

    return registered


def check_bots_health():
    """모든 봇 헬스 체크"""
    print("\n" + "=" * 60)
    print("🔍 봇 헬스 체크")
    print("=" * 60)

    if not WATCHDOG_STATE_FILE.exists():
        print("❌ 등록된 봇이 없습니다. 먼저 register_bots()를 실행하세요.")
        return

    with open(WATCHDOG_STATE_FILE, 'r') as f:
        state = json.load(f)

    healthy_count = 0
    unhealthy_count = 0

    for bot_name, bot_state in state.items():
        pid = bot_state.get("pid")
        is_alive = False

        if pid:
            try:
                os.kill(pid, 0)
                is_alive = True
            except (ProcessLookupError, PermissionError):
                is_alive = False

        # 하트비트 파일 체크
        heartbeat_file = Path(bot_state.get("heartbeat_file", ""))
        if heartbeat_file.exists() and not is_alive:
            # PID는 없지만 하트비트 파일이 있으면 확인
            last_modified = datetime.fromtimestamp(heartbeat_file.stat().st_mtime)
            elapsed = (datetime.now() - last_modified).total_seconds()
            if elapsed < 60:  # 60초 이내 하트비트
                is_alive = True

        status_icon = "🟢" if is_alive else "🔴"
        status_text = "healthy" if is_alive else "unhealthy"

        print(f"{status_icon} {bot_state['display_name']}: {status_text}")

        if is_alive:
            healthy_count += 1
        else:
            unhealthy_count += 1

            # 자동 재시작 시도
            if bot_state.get("auto_restart"):
                print(f"   ⚠️ 자동 재시작 시도: {bot_name}")
                restart_cmd = bot_state.get("restart_cmd")
                if restart_cmd:
                    try:
                        subprocess.Popen(restart_cmd, shell=True)
                        print(f"   ✅ 재시작 명령 실행됨")
                    except Exception as e:
                        print(f"   ❌ 재시작 실패: {e}")

    print("=" * 60)
    print(f"상태 요약: 🟢 {healthy_count} healthy, 🔴 {unhealthy_count} unhealthy")
    print("=" * 60)


def generate_watchdog_config():
    """OpenClaw 워치독 설정 생성"""
    config_file = OPENCLAW_DIR / "watchdog_oza2m_config.json"

    # Convert PosixPath objects to strings for JSON serialization
    bots_config = []
    for bot in OZ_A2M_BOTS:
        bot_config = dict(bot)
        bot_config["pid_file"] = str(bot["pid_file"])
        bot_config["heartbeat_file"] = str(bot["heartbeat_file"])
        bots_config.append(bot_config)

    config = {
        "name": "OZ_A2M Watchdog",
        "version": "1.0",
        "bots": bots_config,
        "settings": {
            "check_interval_seconds": 30,
            "heartbeat_timeout_seconds": 60,
            "auto_restart_enabled": True,
            "max_auto_restarts": 3,
            "restart_cooldown_seconds": 300,
            "circuit_breaker_enabled": True,
            "circuit_breaker_failure_threshold": 5,
            "circuit_breaker_cooldown_seconds": 600,
            "telegram_alerts": True,
        },
        "monitoring": {
            "redis_enabled": True,
            "redis_host": "localhost",
            "redis_port": 6379,
            "mqtt_enabled": True,
            "mqtt_host": "localhost",
            "mqtt_port": 1883,
        }
    }

    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"\n✅ 워치독 설정 생성: {config_file}")
    return config_file


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OZ_A2M 봇 OpenClaw 워치독 관리")
    parser.add_argument("command", choices=["register", "check", "config", "all"],
                        default="all", nargs="?",
                        help="실행할 명령 (register: 등록, check: 헬스체크, config: 설정생성, all: 전체)")

    args = parser.parse_args()

    if args.command == "register":
        register_bots()
    elif args.command == "check":
        check_bots_health()
    elif args.command == "config":
        generate_watchdog_config()
    elif args.command == "all":
        registered = register_bots()
        generate_watchdog_config()
        check_bots_health()

        print("\n" + "=" * 60)
        print("🎉 OZ_A2M 워치독 등록 완료!")
        print("=" * 60)
        print(f"등록된 봇: {len(registered)}개")
        print("\n다음 단계:")
        print("  1. 봇 실행: cd /home/ozzy-claw/OZ_A2M/department_7/src/bot && python3 run_all_bots.py")
        print("  2. 상태 확인: python3 register_oza2m_watchdog.py check")
        print("  3. 대시보드: http://100.77.207.113:8083")
        print("=" * 60)

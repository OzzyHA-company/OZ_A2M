#!/usr/bin/env python3
"""
OZ_A2M 봇 Reward System 활성화 스크립트

기존 봇들을 Reward System에 통합
실전 거래 모드에서 RPG/보상/자본 재배분 활성화
"""

import sys
import os
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from lib.core.reward_system import (
    RPGSystem,
    CapitalAllocator,
    BotClassifier,
    RewardAwareBot,
    TradingAgentsBridge,
)
from lib.core.reward_system.bot_classifier import DEFAULT_BOT_CONFIGS

def initialize_reward_system():
    """Reward System 초기화"""
    print("=" * 50)
    print("  OZ_A2M Reward System Initialization")
    print("=" * 50)

    # 컴포넌트 초기화
    rpg = RPGSystem()
    capital = CapitalAllocator()
    classifier = BotClassifier()

    # 상태 로드
    rpg.load()
    capital.load()

    print("\n[1/3] Initializing 11 Trading Bots...")
    print("-" * 50)

    # 11봇 등록
    for config in DEFAULT_BOT_CONFIGS:
        bot_id = config['bot_id']
        bot_name = config['name']
        capital_usd = config['capital_usd']

        # 자본 배분 등록
        if bot_id not in capital.allocations:
            capital.register_bot(bot_id, capital_usd)

        # 봇 유형 분류
        profile = classifier.create_profile(
            bot_id=bot_id,
            bot_name=bot_name,
            exchange=config['exchange'],
            symbols=config['symbols'],
            capital_usd=capital_usd,
        )

        # RPG 상태 생성
        state = rpg.get_or_create_state(bot_id, bot_name)

        print(f"  ✓ {bot_name:20} | "
              f"Type: {profile.bot_type.value:12} | "
              f"Lv: {state.level.current:3} | "
              f"Grade: {state.grade.kr_name:8} | "
              f"HP: {state.hp.current:5.1f} | "
              f"${capital_usd:6.2f}")

    print("-" * 50)
    print(f"Total bots: {len(DEFAULT_BOT_CONFIGS)}")
    print(f"Total capital: ${sum(c['capital_usd'] for c in DEFAULT_BOT_CONFIGS):.2f}")

    # 저장
    print("\n[2/3] Saving states...")
    rpg.save()
    capital.save()
    print("  ✓ RPG states saved")
    print("  ✓ Capital allocations saved")

    # 통계 출력
    print("\n[3/3] System Statistics...")
    print("-" * 50)

    # 등급별 분포
    grade_counts = {}
    for bot_id in rpg.states:
        grade = rpg.states[bot_id].grade.kr_name
        grade_counts[grade] = grade_counts.get(grade, 0) + 1

    print("Grade Distribution:")
    for grade, count in sorted(grade_counts.items()):
        bar = "█" * count + "░" * (11 - count)
        print(f"  {grade:10} [{bar}] {count}")

    print("\n" + "=" * 50)
    print("  Reward System Ready for Live Trading!")
    print("=" * 50)
    print("\nNext Steps:")
    print("  1. Start R&D Reward Service:")
    print("     python3 department_6/src/rnd_with_reward.py")
    print("  2. Start trading bots (they'll auto-report to Reward System)")
    print("  3. Monitor dashboard: http://localhost:8086")
    print("\nFeatures Active:")
    print("  ✓ RPG System (Level/Grade/HP)")
    print("  ✓ Reward Calculation (Sharpe/Sortino/Calmar)")
    print("  ✓ Capital Reallocation (Daily 01:00 UTC)")
    print("  ✓ Episode Memory (Weekly Learning)")
    print("  ✓ TradingAgents Integration")

def show_bot_status():
    """봇 상태 표시"""
    rpg = RPGSystem()
    capital = CapitalAllocator()

    rpg.load()
    capital.load()

    print("\n" + "=" * 70)
    print("  OZ_A2M Bot Status - Reward System")
    print("=" * 70)
    print(f"{'Bot':<20} {'Lv':>3} {'Grade':>10} {'HP':>6} {'Capital':>10} {'Status':>10}")
    print("-" * 70)

    for config in DEFAULT_BOT_CONFIGS:
        bot_id = config['bot_id']
        state = rpg.get_or_create_state(bot_id)
        alloc = capital.allocations.get(bot_id)

        cap_str = f"${alloc.current_capital:.2f}" if alloc else "N/A"
        status = alloc.status.value if alloc else "unknown"

        print(f"{config['name']:<20} "
              f"{state.level.current:>3} "
              f"{state.grade.kr_name:>10} "
              f"{state.hp.current:>6.1f} "
              f"{cap_str:>10} "
              f"{status:>10}")

    print("=" * 70)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OZ_A2M Reward System")
    parser.add_argument("command", choices=["init", "status", "reset"],
                       help="Command to execute")

    args = parser.parse_args()

    if args.command == "init":
        initialize_reward_system()
    elif args.command == "status":
        show_bot_status()
    elif args.command == "reset":
        confirm = input("Reset all RPG states? This will delete all progress. (yes/no): ")
        if confirm.lower() == "yes":
            rpg = RPGSystem()
            capital = CapitalAllocator()
            rpg.states = {}
            capital.allocations = {}
            rpg.save()
            capital.save()
            print("All states reset.")
        else:
            print("Cancelled.")

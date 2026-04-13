#!/usr/bin/env python3
"""
OZ_A2M Master Control Script
Production Implementation - All 6 Phases + Smart AI Router

Usage:
    python3 oz_a2m_control.py status      # Show full system status
    python3 oz_a2m_control.py wallets     # Verify wallet connections
    python3 oz_a2m_control.py rewards     # Calculate rewards
    python3 oz_a2m_control.py settle      # Run settlement
    python3 oz_a2m_control.py emergency   # Emergency stop all bots
    python3 oz_a2m_control.py ai          # Smart AI Router status
    python3 oz_a2m_control.py jito        # Jito RPC Engine status
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.core.bot_wallet_manager import BotWalletManager
from lib.core.reward_aggregator import RewardAggregator, BotPerformance
from lib.core.daily_settlement import DailySettlement
from lib.core.central_controller import CentralController
from lib.core.ai_orchestrator import AIOrchestrator
from lib.core.smart_ai_router import SmartAIRouter, RouterMode
from lib.core.logger import get_logger

logger = get_logger(__name__)


def show_banner():
    """Display system banner."""
    print("\n" + "=" * 70)
    print("  OZ_A2M - Multi-Agent Trading System")
    print("  Production Implementation v1.0")
    print("=" * 70)


def cmd_status():
    """Show complete system status."""
    show_banner()

    # Wallet Status
    print("\n📊 WALLET ALLOCATION")
    print("-" * 70)
    manager = BotWalletManager()
    allocation = manager.get_total_allocation()
    print(f"Total Capital:     ${allocation.total_capital:.2f}")
    active_count = sum(1 for a in allocation.allocations if a.is_active)
    print(f"Active Bots:       {active_count}")
    print(f"Reserved (10%):    ${allocation.reserved_capital:.2f}")

    # Controller Status
    print("\n🎛️  CENTRAL CONTROL")
    print("-" * 70)
    controller = CentralController()
    status = controller.get_system_status()
    print(f"Emergency Mode:    {status['emergency_mode']}")
    print(f"Active Bots:       {len(status['active_bots'])}")
    print(f"Total Users:       {status['total_users']}")

    # AI Status
    print("\n🤖 AI ORCHESTRATION")
    print("-" * 70)
    ai = AIOrchestrator()
    ai_status = ai.get_status()
    print(f"Active Models:     {len(ai_status['active_models'])}")
    for model in ai_status['active_models']:
        print(f"  • {model['name']}: {model['model']}")
    print(f"Total Requests:    {ai_status['total_requests']}")

    # Settlement Summary
    print("\n💰 SETTLEMENT STATUS")
    print("-" * 70)
    settlement = DailySettlement()
    summary = settlement.get_settlement_summary(7)
    print(f"7-Day Profit:      ${summary.get('total_profit', 0):.2f}")
    print(f"To Master Vault:   ${summary.get('total_to_master', 0):.2f}")
    print(f"Reinvested:        ${summary.get('total_reinvested', 0):.2f}")

    print("\n" + "=" * 70)
    print(f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70 + "\n")


def cmd_wallets():
    """Verify wallet connections."""
    show_banner()
    print("\n🔐 Testing Wallet Connections...\n")

    import subprocess
    result = subprocess.run(
        ['python3', 'tests/test_wallet_connection.py'],
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr)


def cmd_rewards():
    """Calculate and display rewards."""
    show_banner()
    print("\n💰 REWARD CALCULATION")
    print("=" * 70)

    aggregator = RewardAggregator()

    # Simulate with sample performances
    performances = [
        BotPerformance(
            bot_id='bot_01_grid', total_profit=12.50, total_trades=45,
            win_rate=0.62, sharpe_ratio=1.8, max_drawdown=0.08,
            profit_factor=1.5, trading_days=7
        ),
        BotPerformance(
            bot_id='bot_02_dca', total_profit=8.30, total_trades=12,
            win_rate=0.75, sharpe_ratio=2.1, max_drawdown=0.05,
            profit_factor=2.0, trading_days=7
        ),
        BotPerformance(
            bot_id='bot_07_hyperliquid', total_profit=25.00, total_trades=89,
            win_rate=0.68, sharpe_ratio=2.3, max_drawdown=0.06,
            profit_factor=2.5, trading_days=14
        ),
    ]

    distribution = aggregator.process_rewards(performances)

    print(f"\nTotal Bots:      {distribution['total_bots']}")
    print(f"Qualified:       {distribution['qualified_bots']}")
    print(f"Total Profit:    ${distribution['total_profit']:.2f}")
    print(f"Total Rewards:   ${distribution['total_rewards']:.2f}")
    print(f"Reward Ratio:    {distribution['reward_ratio']:.2%}")

    print("\nBreakdown:")
    for calc in distribution['calculations']:
        icon = '✅' if calc['qualified'] else '❌'
        print(f"\n  {icon} {calc['bot_id']}")
        print(f"     Profit:    ${calc['profit']:.2f}")
        print(f"     Tier:      {calc['tier'].upper()}")
        if calc['qualified']:
            print(f"     Reward:    ${calc['reward_amount']:.2f} ({calc['reward_pct']:.1%})")
        else:
            print(f"     Reason:    {calc['reason']}")

    print("\n" + "=" * 70 + "\n")


def cmd_settle():
    """Run daily settlement."""
    show_banner()
    print("\n💰 DAILY SETTLEMENT")
    print("=" * 70)

    settlement = DailySettlement()

    # Sample profits
    bot_profits = {
        'bot_01_grid': 5.25,
        'bot_02_dca': 3.80,
        'bot_03_triarb': 1.50,
        'bot_04_funding': 2.20,
        'bot_05_bybit_grid': 1.85,
        'bot_06_scalper': 0.95,
        'bot_07_hyperliquid': 4.50,
        'bot_08_polymarket': 8.20,
    }

    batch = settlement.process_daily_settlement(bot_profits)

    print(f"\nSettlement ID:   {batch['settlement_id']}")
    print(f"Date:            {batch['date'][:10]}")
    print(f"Total Bots:      {batch['total_bots']}")
    print(f"Gross Profit:    ${batch['total_gross_profit']:.2f}")
    print(f"To Master (80%): ${batch['total_to_master_vault']:.2f}")
    print(f"To Reinvest:     ${batch['total_to_reinvest']:.2f}")
    print(f"Fees:            ${batch['total_fees']:.4f}")

    print("\nMaster Vault Addresses:")
    for chain, addr in settlement.MASTER_VAULTS.items():
        masked = addr[:15] + "..." if len(addr) > 15 else addr
        print(f"  {chain:12} {masked}")

    print("\n" + "=" * 70 + "\n")


def cmd_emergency():
    """Emergency stop all bots."""
    show_banner()
    print("\n🚨 EMERGENCY STOP")
    print("=" * 70)

    controller = CentralController()
    result = controller.emergency_stop_all('system')

    if result['success']:
        print("\n⚠️  ALL BOTS STOPPED")
        print("⚠️  EMERGENCY MODE ACTIVATED")
        print("\nManual intervention required to resume.")
    else:
        print(f"\n❌ Error: {result.get('error', 'Unknown error')}")

    print("\n" + "=" * 70 + "\n")


def cmd_ai():
    """Smart AI Router status and test."""
    show_banner()
    print("\n🧠 SMART AI ROUTER")
    print("=" * 70)

    router = SmartAIRouter()

    # Health check
    print("\nHealth Status:")
    print("-" * 70)
    import asyncio
    health = asyncio.run(router.health_check())
    for tier, status in health.items():
        icon = "✅" if status['healthy'] else "❌"
        print(f"  {icon} {tier:20} {status['healthy']}")

    # Stats
    print("\nRouter Statistics:")
    print("-" * 70)
    stats = router.get_stats()
    print(f"  Mode:           {stats['config']['mode']}")
    print(f"  Local Model:    {stats['config']['local_model']}")
    print(f"  Gemini Model:   {stats['config']['gemini_model']}")
    print(f"  Cache Entries:  {stats['cache']['entries']}")

    # Test generation
    print("\nTest Generation:")
    print("-" * 70)
    result = asyncio.run(router.generate(
        "What is grid trading? Answer in one sentence.",
        {'task_type': 'general'}
    ))

    if result.success:
        print(f"  ✅ Tier: {result.tier_used.value}")
        print(f"  ⏱️  Latency: {result.latency_ms:.1f}ms")
        print(f"  📝 Response: {result.response[:80]}...")
    else:
        print(f"  ❌ Error: {result.error}")

    print("\n" + "=" * 70 + "\n")


def cmd_jito():
    """Jito RPC Engine status."""
    show_banner()
    print("\n⚡ JITO RPC ENGINE")
    print("=" * 70)

    import asyncio
    from department_1.src.jito_rpc_engine import get_engine

    engine = get_engine()

    print("\nEndpoints:")
    print("-" * 70)
    stats = engine.get_stats()
    for ep in stats['endpoints']:
        print(f"  • {ep['provider']:20} (priority: {ep['priority']})")

    print(f"\n  Redis Available: {stats['redis_available']}")

    # Test connections
    print("\nConnection Tests:")
    print("-" * 70)

    async def test_connections():
        slot = await engine.get_slot()
        if slot:
            print(f"  ✅ Current Slot: {slot}")
        else:
            print(f"  ❌ Slot fetch failed")

        blockhash = await engine.get_latest_blockhash()
        if blockhash:
            print(f"  ✅ Blockhash: {blockhash[:20]}...")
        else:
            print(f"  ❌ Blockhash fetch failed")

    asyncio.run(test_connections())

    print("\n" + "=" * 70 + "\n")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        show_banner()
        print("\nUsage: python3 oz_a2m_control.py <command>")
        print("\nCommands:")
        print("  status     Show full system status")
        print("  wallets    Verify wallet connections")
        print("  rewards    Calculate rewards")
        print("  settle     Run daily settlement")
        print("  emergency  Emergency stop all bots")
        print("  ai         Smart AI Router status & test")
        print("  jito       Jito RPC Engine status")
        print()
        sys.exit(1)

    command = sys.argv[1].lower()

    commands = {
        'status': cmd_status,
        'wallets': cmd_wallets,
        'rewards': cmd_rewards,
        'settle': cmd_settle,
        'emergency': cmd_emergency,
        'ai': cmd_ai,
        'jito': cmd_jito,
    }

    if command in commands:
        commands[command]()
    else:
        print(f"Unknown command: {command}")
        print(f"Available: {', '.join(commands.keys())}")
        sys.exit(1)


if __name__ == '__main__':
    main()

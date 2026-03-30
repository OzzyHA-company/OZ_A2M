"""
OZ_A2M Unified Bot Manager
제7부서 통합 봇 관리자

이 모듈은 department_7.src.bot.unified_bot_manager에서 재낸포트합니다.
"""

# Canonical UnifiedBotManager를 재낸포트
from department_7.src.bot.unified_bot_manager import (
    UnifiedBotManager,
    BotConfig,
    BotInfo,
    BotType,
    BotStatus,
    get_bot_manager,
    reset_bot_manager,
    create_and_register_scalper_bot,
    create_and_register_grid_bot,
    create_and_register_dca_bot,
)

__all__ = [
    "UnifiedBotManager",
    "BotConfig",
    "BotInfo",
    "BotType",
    "BotStatus",
    "get_bot_manager",
    "reset_bot_manager",
    "create_and_register_scalper_bot",
    "create_and_register_grid_bot",
    "create_and_register_dca_bot",
]

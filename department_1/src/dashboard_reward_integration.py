"""
CEO Dashboard - Reward System Integration
RPG 대시보드 통합 모듈

Features:
- 봇 RPG 상태 조회 (Level/Grade/HP)
- 리더보드 API
- 자본 배분 현황
- 실시간 보상 점수
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path

import sys
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.reward_system import (
    RPGSystem,
    CapitalAllocator,
    RewardCalculator,
    BotClassifier,
)
from lib.core.reward_system.rpg_system import BotGrade

logger = logging.getLogger(__name__)


class DashboardRewardIntegration:
    """대시보드용 Reward System 통합"""

    def __init__(self):
        self.rpg_system = RPGSystem(storage_path="data/rpg_states.json")
        self.capital_allocator = CapitalAllocator(storage_path="data/capital_allocations.json")
        self.calculator = RewardCalculator()
        self.classifier = BotClassifier()

        # 데이터 캐시
        self._cache: Dict[str, Any] = {}
        self._last_update: Optional[datetime] = None

        # 기본 봇 등록
        self._init_bots()

    def _init_bots(self):
        """기본 봇 설정"""
        from lib.core.reward_system.bot_classifier import DEFAULT_BOT_CONFIGS

        for config in DEFAULT_BOT_CONFIGS:
            bot_id = config["bot_id"]
            capital = config["capital_usd"]

            if bot_id not in self.capital_allocator.allocations:
                self.capital_allocator.register_bot(bot_id, capital)

            self.classifier.create_profile(
                bot_id=bot_id,
                bot_name=config["name"],
                exchange=config["exchange"],
                symbols=config["symbols"],
                capital_usd=capital,
            )

        # 상태 로드
        self.rpg_system.load()
        self.capital_allocator.load()

    async def get_bot_rpg_status(self, bot_id: str) -> Dict[str, Any]:
        """봇 RPG 상태 조회"""
        state = self.rpg_system.get_or_create_state(bot_id)
        allocation = self.capital_allocator.allocations.get(bot_id)

        return {
            "bot_id": bot_id,
            "rpg": state.to_dict(),
            "capital": {
                "current": allocation.current_capital if allocation else 0,
                "base": allocation.base_capital if allocation else 0,
                "multiplier": round(allocation.current_capital / allocation.base_capital, 2) if allocation and allocation.base_capital else 1.0,
                "status": allocation.status.value if allocation else "unknown",
            } if allocation else None,
        }

    async def get_all_bots_rpg_status(self) -> List[Dict[str, Any]]:
        """모든 봇 RPG 상태"""
        from lib.core.reward_system.bot_classifier import DEFAULT_BOT_CONFIGS

        results = []
        for config in DEFAULT_BOT_CONFIGS:
            status = await self.get_bot_rpg_status(config["bot_id"])
            results.append(status)

        return results

    async def get_leaderboard(self, sort_by: str = "level", top_n: int = 11) -> Dict[str, Any]:
        """리더보드 조회"""
        leaderboard = self.rpg_system.get_leaderboard(sort_by=sort_by, top_n=top_n)

        # 등급별 통계
        grade_counts = {grade.kr_name: 0 for grade in BotGrade}
        for bot_data in leaderboard:
            grade_kr = bot_data.get("grade", {}).get("kr", "브론즈")
            if grade_kr in grade_counts:
                grade_counts[grade_kr] += 1

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "sort_by": sort_by,
            "total_bots": len(leaderboard),
            "leaderboard": leaderboard,
            "grade_distribution": grade_counts,
        }

    async def get_capital_allocation(self) -> Dict[str, Any]:
        """자본 배분 현황"""
        summary = self.capital_allocator.get_allocations_summary()

        # 변동 내역
        changes = []
        for bot_id, alloc in self.capital_allocator.allocations.items():
            if alloc.allocation_history:
                latest = alloc.allocation_history[-1]
                if abs(latest.get("change", 0)) > 0.01:
                    changes.append({
                        "bot_id": bot_id,
                        "timestamp": latest.get("timestamp"),
                        "change": latest.get("change"),
                        "change_pct": latest.get("change_pct"),
                        "reason": latest.get("reason"),
                    })

        # 최근 변경순 정렬
        changes.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "summary": summary,
            "recent_changes": changes[:10],  # 최근 10개
        }

    async def get_reward_scores(self) -> Dict[str, Any]:
        """보상 점수 현황"""
        scores = {}

        for bot_id in self.capital_allocator.allocations.keys():
            state = self.rpg_system.get_or_create_state(bot_id)

            # 최근 히스토리에서 점수 추정
            recent_scores = [
                h.get("score", 0) for h in state.history[-10:]
                if "score" in h
            ]

            avg_score = sum(recent_scores) / len(recent_scores) if recent_scores else 0

            profile = self.classifier.get_profile(bot_id)
            bot_type = profile.bot_type.value if profile else "unknown"

            scores[bot_id] = {
                "current_score": state.level.current * 10 + state.hp.current,  # 추정 점수
                "avg_score": round(avg_score, 2),
                "bot_type": bot_type,
                "grade": state.grade.en_name,
                "level": state.level.current,
            }

        # 평균 점수 계산
        all_scores = [s["current_score"] for s in scores.values()]
        avg_total = sum(all_scores) / len(all_scores) if all_scores else 0

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "average_score": round(avg_total, 2),
            "scores": scores,
        }

    async def get_system_overview(self) -> Dict[str, Any]:
        """Reward System 종합 현황"""
        rpg_summary = await self.get_all_bots_rpg_status()
        capital = await self.get_capital_allocation()
        leaderboard = await self.get_leaderboard()

        # 전체 통계
        total_hp = sum(s["rpg"]["hp"]["current"] for s in rpg_summary)
        avg_hp = total_hp / len(rpg_summary) if rpg_summary else 0

        total_level = sum(s["rpg"]["level"]["current"] for s in rpg_summary)
        avg_level = total_level / len(rpg_summary) if rpg_summary else 0

        # 위험 봇 (HP < 30)
        critical_bots = [
            s for s in rpg_summary
            if s["rpg"]["hp"]["is_critical"]
        ]

        # 고성과 봇 (Grade Diamond+)
        top_performers = [
            s for s in rpg_summary
            if s["rpg"]["grade"]["en"] in ["Diamond", "Legend"]
        ]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "summary": {
                "total_bots": len(rpg_summary),
                "average_hp": round(avg_hp, 2),
                "average_level": round(avg_level, 2),
                "critical_bots_count": len(critical_bots),
                "top_performers_count": len(top_performers),
                "total_capital_allocated": capital["summary"]["allocated"],
            },
            "rpg_status": rpg_summary,
            "capital_allocation": capital,
            "leaderboard": leaderboard,
            "alerts": {
                "critical_bots": [b["bot_id"] for b in critical_bots],
                "top_performers": [b["bot_id"] for b in top_performers],
            },
        }

    async def execute_capital_reallocation(self, dry_run: bool = False) -> Dict[str, Any]:
        """자본 재배분 실행"""
        # 현재 점수 기준으로 재배분 계산
        reward_results = {}

        for bot_id in self.capital_allocator.allocations.keys():
            # 봇 유형별 보상 함수
            profile = self.classifier.get_profile(bot_id)
            from lib.core.reward_system import RewardType
            reward_type = self.classifier.get_reward_type(profile.bot_type) if profile else RewardType.OZ_ENSEMBLE

            # 샘플 거래로 계산 (실제로는 버퍼에서)
            result = self.calculator.calculate(
                bot_id=bot_id,
                trades=[],  # 실제 데이터로 대체 필요
                reward_type=reward_type,
                lookback_days=1,
            )
            reward_results[bot_id] = result

        # 재배분 계산
        plans = self.capital_allocator.calculate_reallocation(reward_results)
        results = self.capital_allocator.apply_reallocation(plans, dry_run=dry_run)

        # 저장
        if not dry_run:
            self.capital_allocator.save()

        return results

    async def revive_bot(self, bot_id: str) -> Dict[str, Any]:
        """봇 재심사/재구성"""
        state = self.rpg_system.get_or_create_state(bot_id)

        if state.is_retired:
            revive_info = state.revive(reset_hp=True)
            self.rpg_system.save()

            return {
                "bot_id": bot_id,
                "action": "revived",
                "previous_revives": revive_info["revive_count"] - 1,
                "current_revives": revive_info["revive_count"],
                "new_level": revive_info["new_level"],
                "new_hp": revive_info["new_hp"],
            }

        return {
            "bot_id": bot_id,
            "action": "none",
            "reason": "bot_not_retired",
        }

    async def retire_bot(self, bot_id: str, reason: str = "manual") -> Dict[str, Any]:
        """봇 폐기"""
        state = self.rpg_system.get_or_create_state(bot_id)
        state.retire(reason)
        self.rpg_system.save()

        return {
            "bot_id": bot_id,
            "action": "retired",
            "reason": reason,
            "final_level": state.level.current,
            "final_grade": state.grade.en_name,
        }


# FastAPI 엔드포인트용 함수들 (ceo_dashboard_server.py에서 사용)
reward_integration = DashboardRewardIntegration()


async def get_rpg_status_endpoint(bot_id: Optional[str] = None):
    """GET /api/reward/rpg-status"""
    if bot_id:
        return await reward_integration.get_bot_rpg_status(bot_id)
    return await reward_integration.get_all_bots_rpg_status()


async def get_leaderboard_endpoint(sort_by: str = "level", top_n: int = 11):
    """GET /api/reward/leaderboard"""
    return await reward_integration.get_leaderboard(sort_by=sort_by, top_n=top_n)


async def get_capital_endpoint():
    """GET /api/reward/capital"""
    return await reward_integration.get_capital_allocation()


async def get_reward_overview_endpoint():
    """GET /api/reward/overview"""
    return await reward_integration.get_system_overview()


async def post_reallocate_endpoint(dry_run: bool = False):
    """POST /api/reward/reallocate"""
    return await reward_integration.execute_capital_reallocation(dry_run=dry_run)


async def post_revive_endpoint(bot_id: str):
    """POST /api/reward/bot/{bot_id}/revive"""
    return await reward_integration.revive_bot(bot_id)


async def post_retire_endpoint(bot_id: str, reason: str = "manual"):
    """POST /api/reward/bot/{bot_id}/retire"""
    return await reward_integration.retire_bot(bot_id, reason)

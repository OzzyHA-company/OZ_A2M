"""
Capital Allocator - 자본 배분 최적화 엔진

FinRL-Trading Ensemble Strategy 기반
"앙상블 보상 경쟁" 메커니즘 구현

핵심 로직:
1. 매일 새벽 1시 reward_score 계산
2. 점수 순위에 따른 자본 배분 자동 조정
   - 상위 20%: 자본 +20% 추가 배분
   - 하위 20%: 자본 -50% 회수, 대기 상태
3. 회수된 자본은 수익 상위 봇에 재배분

봇이 서로 자본을 "경쟁"해서 가져가는 구조
→ 시스템 전체 수익이 자동으로 최고 성과 봇에 집중
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import asyncio

from .reward_calculator import RewardResult
from .rpg_system import RPGSystem, BotGrade

logger = logging.getLogger(__name__)


class CapitalStatus(Enum):
    """자본 상태"""
    ACTIVE = "active"           # 정상 운영
    REDUCED = "reduced"         # 자본 감소
    STANDBY = "standby"         # 대기 상태
    RETIRED = "retired"         # 폐기


@dataclass
class CapitalAllocation:
    """자본 배분 정보"""
    bot_id: str
    current_capital: float      # 현재 자본
    base_capital: float         # 기준 자본 (초기)
    allocated_at: datetime      # 최근 배분 시점
    status: CapitalStatus = CapitalStatus.ACTIVE

    # 히스토리
    allocation_history: List[Dict[str, Any]] = field(default_factory=list)

    def adjust_capital(self, new_amount: float, reason: str) -> Dict[str, Any]:
        """자본 조정"""
        old_amount = self.current_capital
        self.current_capital = max(0, new_amount)

        record = {
            'timestamp': datetime.utcnow().isoformat(),
            'old_amount': old_amount,
            'new_amount': self.current_capital,
            'change': self.current_capital - old_amount,
            'change_pct': round((self.current_capital - old_amount) / old_amount * 100, 2) if old_amount > 0 else 0,
            'reason': reason,
        }

        self.allocation_history.append(record)

        # 상태 업데이트
        if self.current_capital == 0:
            self.status = CapitalStatus.STANDBY
        elif self.current_capital < self.base_capital * 0.5:
            self.status = CapitalStatus.REDUCED
        else:
            self.status = CapitalStatus.ACTIVE

        return record


class CapitalAllocator:
    """
    자본 배분 관리자

    FinRL-Trading Ensemble Strategy 방식
    성과 기반 동적 자본 재배분
    """

    # 재배분 규칙
    # ⚠️ 매일 장 마감: 수익은 마스터 금고로, 봇에는 원금만 남김
    # 순위/등급에 따른 자본 증감 없음
    REALLOCATION_RULES = {
        'max_capital_multiplier': 1.0,      # 원금 초과 불가
        'reallocation_interval_hours': 24,  # 매일 1회
    }

    def __init__(
        self,
        total_capital: float = 97.79,  # OZ_A2M 총 자본
        rpg_system: Optional[RPGSystem] = None,
        storage_path: Optional[str] = None,
    ):
        self.total_capital = total_capital
        self.rpg_system = rpg_system
        self.storage_path = storage_path or "data/capital_allocations.json"

        self.allocations: Dict[str, CapitalAllocation] = {}
        self.last_reallocation: Optional[datetime] = None

        self.logger = logging.getLogger(self.__class__.__name__)

    def register_bot(
        self,
        bot_id: str,
        base_capital: float,
    ) -> CapitalAllocation:
        """봇 등록 및 초기 자본 설정"""
        allocation = CapitalAllocation(
            bot_id=bot_id,
            current_capital=base_capital,
            base_capital=base_capital,
            allocated_at=datetime.utcnow(),
        )
        self.allocations[bot_id] = allocation
        self.logger.info(f"Registered {bot_id} with ${base_capital:.2f}")
        return allocation

    def calculate_reallocation(
        self,
        reward_results: Dict[str, RewardResult],
    ) -> Dict[str, Dict[str, Any]]:
        """
        일일 정산: 수익은 금고로, 모든 봇은 원금으로 리셋

        순위/등급에 따른 자본 증감 없음.
        성과가 좋든 나쁘든 원금만 유지.
        """
        plans = {}

        for bot_id, alloc in self.allocations.items():
            profit = alloc.current_capital - alloc.base_capital

            plans[bot_id] = {
                'action': 'reset_to_base',
                'current': alloc.current_capital,
                'proposed': alloc.base_capital,   # 원금으로 리셋
                'profit_to_vault': max(0.0, profit),  # 수익분 → 금고
                'change': alloc.base_capital - alloc.current_capital,
                'reason': 'daily_profit_to_vault',
            }

        return plans

    def apply_reallocation(
        self,
        plans: Dict[str, Dict[str, Any]],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        재배분 적용

        Args:
            plans: calculate_reallocation 결과
            dry_run: 시뮬레이션 모드

        Returns:
            실행 결과 요약
        """
        if dry_run:
            self.logger.info("DRY RUN - No actual changes made")

        results = {
            'timestamp': datetime.utcnow().isoformat(),
            'dry_run': dry_run,
            'changes': [],
            'summary': {
                'increased': 0,
                'decreased': 0,
                'maintained': 0,
                'total_redistributed': 0.0,
            }
        }

        total_to_vault = 0.0

        for bot_id, plan in plans.items():
            if bot_id not in self.allocations:
                continue

            profit_to_vault = plan.get('profit_to_vault', 0.0)
            total_to_vault += profit_to_vault

            if not dry_run:
                self.allocations[bot_id].adjust_capital(plan['proposed'], plan['reason'])

            results['changes'].append({
                'bot_id': bot_id,
                'action': plan['action'],
                'from': plan['current'],
                'to': plan['proposed'],
                'profit_to_vault': profit_to_vault,
            })
            results['summary']['maintained'] += 1

        results['summary']['total_to_vault'] = round(total_to_vault, 4)
        self.last_reallocation = datetime.utcnow()
        self.logger.info(f"Daily reset complete. 금고 입금: ${total_to_vault:.4f}")

        return results

    def ceo_invest(self, bot_id: str, amount: float, reason: str = "") -> Dict[str, Any]:
        """
        CEO 직접 추가 투자 — 수동 전용

        성과 좋은 봇에 CEO가 판단해서 직접 자본 추가.
        자동 호출 금지.

        Args:
            bot_id: 투자할 봇 ID
            amount: 추가 금액 ($)
            reason: 투자 사유 (기록용)
        """
        if bot_id not in self.allocations:
            raise ValueError(f"Bot {bot_id} not registered")
        if amount <= 0:
            raise ValueError("추가 투자금은 0보다 커야 합니다")

        alloc = self.allocations[bot_id]
        old_base = alloc.base_capital
        old_current = alloc.current_capital

        # base_capital도 올림 (이제 이게 새 원금)
        alloc.base_capital += amount
        alloc.current_capital += amount
        record = alloc.adjust_capital(alloc.current_capital, f"CEO투자: {reason}")

        self.logger.info(
            f"[CEO투자] {bot_id}: 원금 ${old_base:.2f} → ${alloc.base_capital:.2f} "
            f"(+${amount:.2f}) | 사유: {reason}"
        )

        return {
            'bot_id': bot_id,
            'added': amount,
            'old_base': old_base,
            'new_base': alloc.base_capital,
            'old_current': old_current,
            'new_current': alloc.current_capital,
            'reason': reason,
            'timestamp': datetime.utcnow().isoformat(),
        }

    def get_allocations_summary(self) -> Dict[str, Any]:
        """자본 배분 현황 요약"""
        total_allocated = sum(a.current_capital for a in self.allocations.values())

        return {
            'total_capital': self.total_capital,
            'allocated': round(total_allocated, 2),
            'unallocated': round(self.total_capital - total_allocated, 2),
            'allocation_pct': round(total_allocated / self.total_capital * 100, 2),
            'bots': len(self.allocations),
            'last_reallocation': self.last_reallocation.isoformat() if self.last_reallocation else None,
            'by_status': {
                status.value: len([a for a in self.allocations.values() if a.status == status])
                for status in CapitalStatus
            },
            'details': {
                bot_id: {
                    'current': alloc.current_capital,
                    'base': alloc.base_capital,
                    'ratio': round(alloc.current_capital / alloc.base_capital, 2),
                    'status': alloc.status.value,
                }
                for bot_id, alloc in self.allocations.items()
            }
        }

    def save(self) -> None:
        """상태 저장"""
        import os
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

        data = {
            'timestamp': datetime.utcnow().isoformat(),
            'total_capital': self.total_capital,
            'last_reallocation': self.last_reallocation.isoformat() if self.last_reallocation else None,
            'allocations': {
                bot_id: {
                    'current': alloc.current_capital,
                    'base': alloc.base_capital,
                    'allocated_at': alloc.allocated_at.isoformat(),
                    'status': alloc.status.value,
                    'history': alloc.allocation_history[-10:],  # 최근 10개
                }
                for bot_id, alloc in self.allocations.items()
            }
        }

        with open(self.storage_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    def load(self) -> None:
        """상태 로드"""
        import os
        if not os.path.exists(self.storage_path):
            return

        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)

            for bot_id, alloc_data in data.get('allocations', {}).items():
                self.allocations[bot_id] = CapitalAllocation(
                    bot_id=bot_id,
                    current_capital=alloc_data.get('current', 0),
                    base_capital=alloc_data.get('base', alloc_data.get('current', 0)),
                    allocated_at=datetime.fromisoformat(alloc_data['allocated_at']),
                    status=CapitalStatus(alloc_data.get('status', 'active')),
                )

            if data.get('last_reallocation'):
                self.last_reallocation = datetime.fromisoformat(data['last_reallocation'])

            self.logger.info(f"Loaded {len(self.allocations)} capital allocations")

        except Exception as e:
            self.logger.error(f"Failed to load capital allocations: {e}")

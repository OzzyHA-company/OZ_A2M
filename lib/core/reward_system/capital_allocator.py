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
    REALLOCATION_RULES = {
        'top_20_pct_bonus': 0.20,      # 상위 20%: +20%
        'bottom_20_pct_penalty': -0.50, # 하위 20%: -50%
        'min_capital_threshold': 5.0,   # 최소 자본 $5
        'max_capital_multiplier': 2.0,  # 최대 기준자본의 2배
        'reallocation_interval_hours': 24,  # 재배분 주기
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
        자본 재배분 계산

        Args:
            reward_results: {bot_id: RewardResult} 보상 결과

        Returns:
            {bot_id: reallocation_plan} 재배분 계획
        """
        if not reward_results:
            return {}

        # 점수 기준 정렬
        ranked = sorted(
            [(bot_id, result.score) for bot_id, result in reward_results.items()],
            key=lambda x: x[1],
            reverse=True
        )

        n_bots = len(ranked)
        top_20_count = max(1, int(n_bots * 0.2))
        bottom_20_count = max(1, int(n_bots * 0.2))

        top_bots = set([r[0] for r in ranked[:top_20_count]])
        bottom_bots = set([r[0] for r in ranked[-bottom_20_count:]])

        # 회수될 자본 계산
        reclaimed_capital = 0.0
        plans = {}

        # 1단계: 하위 봇에서 자본 회수
        for bot_id in bottom_bots:
            if bot_id not in self.allocations:
                continue

            alloc = self.allocations[bot_id]
            reduction = alloc.current_capital * abs(self.REALLOCATION_RULES['bottom_20_pct_penalty'])
            reclaimed_capital += reduction

            plans[bot_id] = {
                'action': 'reduce',
                'current': alloc.current_capital,
                'proposed': alloc.current_capital - reduction,
                'change': -reduction,
                'reason': 'bottom_20_performance',
                'rank': ranked.index((bot_id, reward_results[bot_id].score)) + 1,
            }

        # 2단계: 상위 봇에 자본 추가 배분
        bonus_per_bot = reclaimed_capital / len(top_bots) if top_bots else 0

        for bot_id in top_bots:
            if bot_id not in self.allocations:
                continue

            alloc = self.allocations[bot_id]

            # 기본 볼너스 + 등급 별 추가 볼너스
            grade_bonus = 0
            if self.rpg_system:
                state = self.rpg_system.get_or_create_state(bot_id)
                grade_multipliers = {
                    BotGrade.BRONZE: 0.0,
                    BotGrade.SILVER: 0.05,
                    BotGrade.GOLD: 0.10,
                    BotGrade.PLATINUM: 0.15,
                    BotGrade.DIAMOND: 0.20,
                    BotGrade.LEGEND: 0.30,
                }
                grade_bonus = alloc.current_capital * grade_multipliers.get(state.grade, 0)

            total_bonus = bonus_per_bot + grade_bonus

            # 최대 자본 한도 체크
            max_capital = alloc.base_capital * self.REALLOCATION_RULES['max_capital_multiplier']
            proposed = min(alloc.current_capital + total_bonus, max_capital)

            plans[bot_id] = {
                'action': 'increase',
                'current': alloc.current_capital,
                'proposed': proposed,
                'change': proposed - alloc.current_capital,
                'reason': 'top_20_performance',
                'rank': ranked.index((bot_id, reward_results[bot_id].score)) + 1,
                'bonus_breakdown': {
                    'ensemble_share': bonus_per_bot,
                    'grade_bonus': grade_bonus,
                }
            }

        # 3단계: 중위 봇은 유지
        middle_bots = set(self.allocations.keys()) - top_bots - bottom_bots
        for bot_id in middle_bots:
            if bot_id not in self.allocations:
                continue

            rank = next((i+1 for i, (bid, _) in enumerate(ranked) if bid == bot_id), n_bots // 2)
            plans[bot_id] = {
                'action': 'maintain',
                'current': self.allocations[bot_id].current_capital,
                'proposed': self.allocations[bot_id].current_capital,
                'change': 0,
                'reason': 'mid_performance',
                'rank': rank,
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

        for bot_id, plan in plans.items():
            if bot_id not in self.allocations:
                continue

            if not dry_run:
                record = self.allocations[bot_id].adjust_capital(
                    plan['proposed'],
                    plan['reason']
                )

            results['changes'].append({
                'bot_id': bot_id,
                'action': plan['action'],
                'amount': plan['change'],
                'from': plan['current'],
                'to': plan['proposed'],
                'reason': plan['reason'],
            })

            if plan['action'] == 'increase':
                results['summary']['increased'] += 1
                results['summary']['total_redistributed'] += plan['change']
            elif plan['action'] == 'reduce':
                results['summary']['decreased'] += 1
            else:
                results['summary']['maintained'] += 1

        self.last_reallocation = datetime.utcnow()

        self.logger.info(
            f"Reallocation complete: +{results['summary']['increased']}, "
            f"-{results['summary']['decreased']}, "
            f"={results['summary']['maintained']}"
        )

        return results

    def get_opportunity_bonus(
        self,
        bot_id: str,
        opportunity_type: str,
        volatility_spike: Optional[float] = None,
        funding_extreme: Optional[float] = None,
    ) -> float:
        """
        기회 포착 보너스 (수익 극대화 핵심)

        Args:
            bot_id: 봇 ID
            opportunity_type: 'volatility', 'funding', 'launch', 'fear_greed'
            volatility_spike: 변동성 지수 (ATR 기준)
            funding_extreme: 펀딩비 극단값

        Returns:
            float: 보너스 자본액
        """
        if bot_id not in self.allocations:
            return 0.0

        base_capital = self.allocations[bot_id].current_capital
        bonus = 0.0

        if opportunity_type == 'volatility' and volatility_spike:
            # 변동성 급등 → Scalper/Sniper 보너스
            if volatility_spike > 2.0:  # 2배 이상 변동성
                bonus = base_capital * 0.15  # 15% 추가
                self.logger.info(f"Volatility bonus for {bot_id}: ${bonus:.2f}")

        elif opportunity_type == 'funding' and funding_extreme:
            # 펀딩비 극단값 → Funding Rate 보너스
            if abs(funding_extreme) > 0.1:  # 0.1% 이상
                bonus = base_capital * 0.20  # 20% 추가
                self.logger.info(f"Funding extreme bonus for {bot_id}: ${bonus:.2f}")

        elif opportunity_type == 'launch':
            # 새 토큰 런칭 → Sniper 우선권
            bonus = base_capital * 0.25  # 25% 추가
            self.logger.info(f"Launch bonus for {bot_id}: ${bonus:.2f}")

        elif opportunity_type == 'fear_greed':
            # 극단 공포/탐욕 → 역추세 보너스
            bonus = base_capital * 0.10  # 10% 추가
            self.logger.info(f"Fear/Greed bonus for {bot_id}: ${bonus:.2f}")

        return bonus

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

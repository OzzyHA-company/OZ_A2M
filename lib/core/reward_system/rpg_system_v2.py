"""
RPG System v2 - 완전 개편된 RPG 보상 시스템

핵심 원칙:
- HP: 시간 회복 금지, 오직 성과로만 증감
- 레벨: 하띙 가능 (수익 저조 시 강등)
- 10티어 등급 + 승급 미션
- 자기경쟁 + 상대경쟁 이중 구조
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from enum import Enum, auto
import json
import logging

logger = logging.getLogger(__name__)


class BotTier(Enum):
    """10티어 등급 시스템"""
    NOVICE = ("입문자", "Novice", 1, 9, "#808080", "⚪")
    IRON = ("아이언", "Iron", 10, 19, "#5C4033", "🟤")
    BRONZE = ("브론즈", "Bronze", 20, 29, "#CD7F32", "🥉")
    SILVER = ("실버", "Silver", 30, 39, "#C0C0C0", "🥈")
    GOLD = ("골드", "Gold", 40, 49, "#FFD700", "🥇")
    PLATINUM = ("플래티넘", "Platinum", 50, 59, "#E5E4E2", "💿")
    EMERALD = ("에메랄드", "Emerald", 60, 69, "#50C878", "💚")
    DIAMOND = ("다이아몬드", "Diamond", 70, 79, "#B9F2FF", "💎")
    MASTER = ("마스터", "Master", 80, 89, "#9B59B6", "👑")
    GRANDMASTER = ("그랜드마스터", "Grandmaster", 90, 99, "#FF6B35", "🔥")
    CHALLENGER = ("챌린저", "Challenger", 100, 999, "#FFD700", "🏆")

    def __init__(self, kr_name, en_name, min_lv, max_lv, color, emoji):
        self.kr_name = kr_name
        self.en_name = en_name
        self.min_level = min_lv
        self.max_level = max_lv
        self.color = color
        self.emoji = emoji

    @classmethod
    def from_level(cls, level: int) -> "BotTier":
        """레벨로 등급 결정"""
        for tier in cls:
            if tier.min_level <= level <= tier.max_level:
                return tier
        return cls.NOVICE if level < 1 else cls.CHALLENGER


@dataclass
class PromotionMission:
    """승급 미션"""
    from_tier: BotTier
    to_tier: BotTier
    required_level: int
    missions: List[Dict]
    rewards: Dict

    @staticmethod
    def get_mission(tier: BotTier) -> Optional["PromotionMission"]:
        """등급별 승급 미션"""
        missions = {
            BotTier.NOVICE: PromotionMission(
                BotTier.NOVICE, BotTier.IRON, 10,
                [
                    {"type": "total_trades", "value": 10, "desc": "10회 거래 완료"},
                    {"type": "win_rate", "value": 40, "desc": "승률 40% 이상"},
                ],
                {"title": "아이언 트레이더", "badge": "iron_wings", "exp_bonus": 50}
            ),
            BotTier.IRON: PromotionMission(
                BotTier.IRON, BotTier.BRONZE, 20,
                [
                    {"type": "consecutive_profit_days", "value": 3, "desc": "3일 연속 수익"},
                    {"type": "max_drawdown_under", "value": 5, "desc": "최대낙폭 5% 이하"},
                    {"type": "total_profit", "value": 10, "desc": "누적 수익 $10+"},
                ],
                {"title": "브론즈 트레이더", "badge": "bronze_wings", "exp_bonus": 100}
            ),
            BotTier.BRONZE: PromotionMission(
                BotTier.BRONZE, BotTier.SILVER, 30,
                [
                    {"type": "consecutive_profit_days", "value": 5, "desc": "5일 연속 수익"},
                    {"type": "sharpe_ratio", "value": 1.0, "desc": "샤프 비율 1.0+"},
                    {"type": "total_trades", "value": 50, "desc": "50회 거래"},
                ],
                {"title": "실버 트레이더", "badge": "silver_wings", "exp_bonus": 150}
            ),
            # ... 더 많은 미션 정의 가능
        }
        return missions.get(tier)


@dataclass
class BotHP:
    """HP 시스템 - 시간 회복 금지"""
    current: float = 100.0
    max_hp: float = 100.0

    # HP 변경 기준 (이벤트 기반만)
    HP_GAIN_PROFIT_5PCT = 15      # +5% 수익 시
    HP_GAIN_PROFIT_10PCT = 25     # +10% 수익 시
    HP_GAIN_PROFIT_15PCT = 40     # +15% 수익 시
    HP_GAIN_STREAK_3 = 10         # 3연승 시
    HP_GAIN_STREAK_5 = 20         # 5연승 시

    HP_LOSS_LOSS_5PCT = -15       # -5% 손실 시
    HP_LOSS_LOSS_10PCT = -20      # -10% 손실 시
    HP_LOSS_NO_STOPLOSS = -15     # 손절 미준수
    HP_LOSS_MAX_DRAWDOWN = -20    # 최대낙폭 초과
    HP_IDLE_DAY = -3              # 24시간 거래 없음 (미활동 패널티)

    def modify(self, amount: float) -> Tuple[float, bool]:
        """HP 수정"""
        self.current = max(0, min(self.max_hp, self.current + amount))
        return self.current, self.current <= 0  # (새 HP, 사망 여부)

    @property
    def is_dead(self) -> bool:
        """HP 0 = 사망"""
        return self.current <= 0

    @property
    def is_critical(self) -> bool:
        """위험 상태"""
        return self.current < 30

    @property
    def is_healthy(self) -> bool:
        """건강 상태"""
        return self.current > 70


@dataclass
class BotLevel:
    """레벨 시스템 - 하띙 가능"""
    current: int = 1
    total_exp: float = 0.0

    # EXP 구간별 필요량
    LEVEL_EXP_REQUIREMENTS = {
        1: 0, 2: 100, 3: 220, 4: 360, 5: 520,
        6: 700, 7: 900, 8: 1120, 9: 1360, 10: 1600,
        # ... 100까지 정의
    }

    def add_exp(self, amount: float) -> Tuple[bool, int]:
        """
        EXP 추가
        Returns: (레벨변화 여부, 새 레벨)
        """
        old_level = self.current
        self.total_exp = max(0, self.total_exp + amount)  # 음수 가능 (하띙)

        # 레벨 재계산
        new_level = self._calculate_level_from_exp()

        if new_level != old_level:
            self.current = new_level
            logger.info(f"Level changed: {old_level} → {new_level}")
            return True, new_level

        return False, old_level

    def _calculate_level_from_exp(self) -> int:
        """EXP 기반 레벨 계산"""
        total = self.total_exp
        for level in range(100, 0, -1):
            req = self.LEVEL_EXP_REQUIREMENTS.get(level, level * 100)
            if total >= req:
                return level
        return 1

    @property
    def progress_pct(self) -> float:
        """현재 레벨 진행률"""
        current_req = self.LEVEL_EXP_REQUIREMENTS.get(self.current, self.current * 100)
        next_req = self.LEVEL_EXP_REQUIREMENTS.get(self.current + 1, (self.current + 1) * 100)
        current_exp = self.total_exp - current_req
        needed = next_req - current_req
        return min(100, (current_exp / needed) * 100) if needed > 0 else 100


@dataclass
class BotTitle:
    """칭호 시스템"""
    title_id: str
    kr_name: str
    condition: str
    is_active: bool = True


@dataclass
class BotBadge:
    """뱃지 시스템"""
    badge_id: str
    kr_name: str
    tier: BotTier
    icon: str
    is_active: bool = True


@dataclass
class BotRPGState:
    """봇 RPG 상태 v2"""
    bot_id: str
    bot_name: str
    tier: BotTier = BotTier.NOVICE
    level: BotLevel = field(default_factory=BotLevel)
    hp: BotHP = field(default_factory=BotHP)
    titles: List[BotTitle] = field(default_factory=list)
    badges: List[BotBadge] = field(default_factory=list)

    # 통계
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    max_consecutive_wins: int = 0

    # 수익 추적
    daily_profits: List[Dict] = field(default_factory=list)  # 최근 30일
    total_profit_usd: float = 0.0

    # 메타
    is_retired: bool = False  # HP 0으로 사망
    retired_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def update_from_trade_result(self, pnl_pct: float, win: bool) -> Dict:
        """거래 결과로 상태 업데이트"""
        self.total_trades += 1
        self.updated_at = datetime.utcnow()
        changes = {'hp_change': 0, 'exp_change': 0, 'level_changed': False}

        if win:
            self.win_trades += 1
            self.consecutive_wins += 1
            self.consecutive_losses = 0
            self.max_consecutive_wins = max(self.max_consecutive_wins, self.consecutive_wins)

            # HP 회복 (성과 기반)
            if pnl_pct >= 15:
                hp_gain = self.hp.HP_GAIN_PROFIT_15PCT
            elif pnl_pct >= 10:
                hp_gain = self.hp.HP_GAIN_PROFIT_10PCT
            elif pnl_pct >= 5:
                hp_gain = self.hp.HP_GAIN_PROFIT_5PCT
            else:
                hp_gain = 0

            # 연승 보너스
            if self.consecutive_wins >= 5:
                hp_gain += self.hp.HP_GAIN_STREAK_5
            elif self.consecutive_wins >= 3:
                hp_gain += self.hp.HP_GAIN_STREAK_3

            new_hp, died = self.hp.modify(hp_gain)
            changes['hp_change'] = hp_gain

            # EXP 획득
            exp_gain = 10 + pnl_pct * 2
            level_changed, new_level = self.level.add_exp(exp_gain)
            changes['exp_change'] = exp_gain
            changes['level_changed'] = level_changed

        else:
            self.loss_trades += 1
            self.consecutive_losses += 1
            self.consecutive_wins = 0

            # HP 감소
            if pnl_pct <= -10:
                hp_loss = self.hp.HP_LOSS_LOSS_10PCT
            elif pnl_pct <= -5:
                hp_loss = self.hp.HP_LOSS_LOSS_5PCT
            else:
                hp_loss = -5

            new_hp, died = self.hp.modify(hp_loss)
            changes['hp_change'] = hp_loss

            # EXP 소량 획득 (학습용)
            exp_gain = 3
            self.level.add_exp(exp_gain)
            changes['exp_change'] = exp_gain

        # 등급 동기화
        self.tier = BotTier.from_level(self.level.current)

        # 사망 체크
        if self.hp.is_dead:
            self.is_retired = True
            self.retired_at = datetime.utcnow()
            changes['died'] = True

        return changes

    def update_daily_settlement(self, profit_pct: float):
        """일일 정산 업데이트"""
        today = datetime.utcnow().date().isoformat()

        # 오늘 수익 기록
        self.daily_profits.append({
            'date': today,
            'profit_pct': profit_pct
        })
        self.daily_profits = self.daily_profits[-30:]  # 30일 유지

        # EXP/HP 업데이트
        if profit_pct > 0:
            exp_gain = profit_pct * 5  # 1% = 5 EXP
            self.level.add_exp(exp_gain)

            # HP 회복
            if profit_pct >= 5:
                self.hp.modify(self.hp.HP_GAIN_PROFIT_5PCT)
        else:
            # 손실 시 HP 감소
            if profit_pct <= -5:
                self.hp.modify(self.hp.HP_LOSS_LOSS_5PCT)

        # 미활동 패널티 초기화 (거래 했으므로)
        # (이 부분은 별도로 처리)

    def check_promotion_mission(self) -> Optional[Dict]:
        """승급 미션 체크"""
        mission = PromotionMission.get_mission(self.tier)
        if not mission:
            return None

        # 레벨 체크
        if self.level.current < mission.required_level:
            return None

        # 미션 완료 여부 체크 (간단화)
        return {
            'can_promote': True,
            'mission': mission,
            'from_tier': mission.from_tier.kr_name,
            'to_tier': mission.to_tier.kr_name
        }

    def apply_idle_penalty(self):
        """미활동 패널티 적용 (24시간 거래 없음)"""
        self.hp.modify(self.hp.HP_IDLE_DAY)
        logger.warning(f"{self.bot_id}: Idle penalty applied (-{self.hp.HP_IDLE_DAY} HP)")


class RPGSystemV2:
    """RPG 시스템 v2 메인 관리자"""

    def __init__(self, storage_path: str = "data/rpg_states_v2.json"):
        self.storage_path = storage_path
        self.states: Dict[str, BotRPGState] = {}
        self.unlocked_milestones: Set[str] = set()  # 중복 방지
        self.load()

    def get_or_create_state(self, bot_id: str, bot_name: str = None) -> BotRPGState:
        """봇 상태 조회 또는 생성"""
        if bot_id not in self.states:
            self.states[bot_id] = BotRPGState(
                bot_id=bot_id,
                bot_name=bot_name or bot_id
            )
        return self.states[bot_id]

    def update_from_trade(self, bot_id: str, pnl_pct: float, win: bool) -> Dict:
        """거래 결과 업데이트"""
        state = self.get_or_create_state(bot_id)
        return state.update_from_trade_result(pnl_pct, win)

    def update_daily(self, bot_id: str, profit_pct: float):
        """일일 업데이트"""
        state = self.get_or_create_state(bot_id)
        state.update_daily_settlement(profit_pct)

        # 마일스톤 체크
        self._check_milestones(bot_id)

        self.save()

    def _check_milestones(self, bot_id: str):
        """마일스톤 체크 (중복 방지)"""
        state = self.get_or_create_state(bot_id)
        level = state.level.current

        # 레벨 마일스톤
        milestone_key = f"{bot_id}_lv{level}"
        if milestone_key not in self.unlocked_milestones:
            self.unlocked_milestones.add(milestone_key)
            logger.info(f"🎉 Milestone unlocked: {bot_id} reached Lv.{level}")

            # 특별 레벨 보상
            if level in [10, 20, 30, 40, 50]:
                self._grant_milestone_reward(bot_id, level)

    def _grant_milestone_reward(self, bot_id: str, level: int):
        """마일스톤 보상 지급"""
        # TODO: 특별 칭호/뱃지 지급
        logger.info(f"Granting milestone reward to {bot_id} for Lv.{level}")

    def get_leaderboard(self, sort_by: str = "score") -> List[Dict]:
        """리더보드 생성"""
        results = []
        for bot_id, state in self.states.items():
            score = (
                state.level.current * 10 +
                state.hp.current +
                state.total_profit_usd * 0.1
            )
            results.append({
                'bot_id': bot_id,
                'bot_name': state.bot_name,
                'tier': state.tier.kr_name,
                'level': state.level.current,
                'hp': state.hp.current,
                'score': score,
                'total_profit': state.total_profit_usd
            })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results

    def save(self):
        """상태 저장"""
        import os
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

        data = {
            'timestamp': datetime.utcnow().isoformat(),
            'states': {k: self._state_to_dict(v) for k, v in self.states.items()},
            'milestones': list(self.unlocked_milestones)
        }

        with open(self.storage_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    def load(self):
        """상태 로드"""
        import os
        if not os.path.exists(self.storage_path):
            return

        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)

            # 상태 복원
            for bot_id, state_data in data.get('states', {}).items():
                state = BotRPGState(
                    bot_id=bot_id,
                    bot_name=state_data.get('bot_name', bot_id)
                )
                state.level.current = state_data.get('level', 1)
                state.level.total_exp = state_data.get('total_exp', 0)
                state.hp.current = state_data.get('hp', 100)
                state.total_trades = state_data.get('total_trades', 0)
                state.win_trades = state_data.get('win_trades', 0)
                state.tier = BotTier.from_level(state.level.current)
                self.states[bot_id] = state

            self.unlocked_milestones = set(data.get('milestones', []))

        except Exception as e:
            logger.error(f"Failed to load RPG states: {e}")

    def _state_to_dict(self, state: BotRPGState) -> Dict:
        """상태를 딕셔너리로 변환"""
        return {
            'bot_id': state.bot_id,
            'bot_name': state.bot_name,
            'level': state.level.current,
            'total_exp': state.level.total_exp,
            'hp': state.hp.current,
            'tier': state.tier.kr_name,
            'total_trades': state.total_trades,
            'win_trades': state.win_trades,
            'total_profit': state.total_profit_usd,
            'is_retired': state.is_retired
        }


# 싱글톤
_rpg_v2 = None

def get_rpg_v2() -> RPGSystemV2:
    """RPG System v2 싱글톤"""
    global _rpg_v2
    if _rpg_v2 is None:
        _rpg_v2 = RPGSystemV2()
    return _rpg_v2

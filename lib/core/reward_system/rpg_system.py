"""
RPG System - 게이미피케이션 기반 봇 성과 관리

레벨, 등급, HP 시스템을 통해 봇 성과를 시각화하고 동기화
실패한 봇은 재심사 → 폐기 or 재구성

Grade Tiers:
- Bronze (브론즈)     - 입문
- Silver (실버)       - 성장
- Gold (골드)         - 숙련
- Platinum (플래티넘) - 전문
- Diamond (다이아몬드) - 마스터
- Legend (레전드)     - 전설

Level: 1 ~ 100
HP: 0 ~ 100 (0 되면 재심사)
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum, auto
import json
import logging

logger = logging.getLogger(__name__)


class BotGrade(Enum):
    """봇 등급 (티어)"""
    BRONZE = ("Bronze", "브론즈", 1, 20, "#CD7F32")
    SILVER = ("Silver", "실버", 21, 40, "#C0C0C0")
    GOLD = ("Gold", "골드", 41, 60, "#FFD700")
    PLATINUM = ("Platinum", "플래티넘", 61, 75, "#E5E4E2")
    DIAMOND = ("Diamond", "다이아몬드", 76, 90, "#B9F2FF")
    LEGEND = ("Legend", "레전드", 91, 100, "#FF6B35")

    def __init__(self, en_name: str, kr_name: str, min_lv: int, max_lv: int, color: str):
        self.en_name = en_name
        self.kr_name = kr_name
        self.min_level = min_lv
        self.max_level = max_lv
        self.color = color

    @classmethod
    def from_level(cls, level: int) -> "BotGrade":
        """레벨로 등급 결정"""
        for grade in cls:
            if grade.min_level <= level <= grade.max_level:
                return grade
        return cls.BRONZE if level < 1 else cls.LEGEND

    @classmethod
    def from_score(cls, score: float) -> "BotGrade":
        """성과 점수로 등급 결정 (0~100)"""
        if score >= 95:
            return cls.LEGEND
        elif score >= 85:
            return cls.DIAMOND
        elif score >= 70:
            return cls.PLATINUM
        elif score >= 50:
            return cls.GOLD
        elif score >= 30:
            return cls.SILVER
        else:
            return cls.BRONZE


@dataclass
class BotLevel:
    """봇 레벨 정보"""
    current: int = 1
    exp: float = 0.0
    total_exp: float = 0.0

    # 레벨업 필요 경험치 (지수 증가)
    BASE_EXP = 100
    EXP_MULTIPLIER = 1.15

    def add_exp(self, amount: float) -> Tuple[bool, int]:
        """
        경험치 추가

        Returns:
            (레벨업 여부, 새로운 레벨)
        """
        self.exp += amount
        self.total_exp += amount

        old_level = self.current

        # 레벨업 체크
        while self.exp >= self._required_exp_for_next():
            self.exp -= self._required_exp_for_next()
            self.current = min(100, self.current + 1)

        leveled_up = self.current > old_level
        if leveled_up:
            logger.info(f"Level up! {old_level} -> {self.current}")

        return leveled_up, self.current

    def _required_exp_for_next(self) -> float:
        """다음 레벨 필요 경험치"""
        return self.BASE_EXP * (self.EXP_MULTIPLIER ** (self.current - 1))

    @property
    def progress_pct(self) -> float:
        """현재 레벨 진행률 (%)"""
        required = self._required_exp_for_next()
        return min(100, (self.exp / required) * 100) if required > 0 else 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'current': self.current,
            'exp': round(self.exp, 2),
            'total_exp': round(self.total_exp, 2),
            'progress_pct': round(self.progress_pct, 2),
            'next_exp': round(self._required_exp_for_next(), 2),
        }


@dataclass
class BotHP:
    """봇 HP (철수/재심사 임계값)"""
    current: float = 100.0
    max_hp: float = 100.0

    # HP 변동 기준
    HP_GAIN_WIN = 5.0           # 수익 거래 시
    HP_GAIN_STREAK = 10.0       # 연승 시
    HP_LOSS_LOSE = -8.0         # 손실 거래 시
    HP_LOSS_DRAWDOWN = -15.0    # 큰 낙폭 시
    HP_PASSIVE_RECOVERY = 2.0   # 시간당 자연 회복

    def modify(self, amount: float) -> Tuple[float, bool]:
        """
        HP 수정

        Returns:
            (새 HP, 철수 여부 - HP <= 0)
        """
        self.current = max(0, min(self.max_hp, self.current + amount))
        return self.current, self.current <= 0

    def recover(self, amount: Optional[float] = None) -> float:
        """HP 회복"""
        recover_amount = amount or self.HP_PASSIVE_RECOVERY
        self.current = min(self.max_hp, self.current + recover_amount)
        return self.current

    @property
    def is_critical(self) -> bool:
        """위험 상태 (HP < 30%)"""
        return self.current < 30

    @property
    def is_healthy(self) -> bool:
        """건강 상태 (HP > 70%)"""
        return self.current > 70

    def to_dict(self) -> Dict[str, Any]:
        return {
            'current': round(self.current, 2),
            'max': self.max_hp,
            'pct': round((self.current / self.max_hp) * 100, 2),
            'is_critical': self.is_critical,
            'is_healthy': self.is_healthy,
        }


@dataclass
class BotRPGState:
    """봇 RPG 상태 전체"""
    bot_id: str
    bot_name: str
    level: BotLevel = field(default_factory=BotLevel)
    hp: BotHP = field(default_factory=BotHP)
    grade: BotGrade = field(default=BotGrade.BRONZE)

    # 통계
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0

    # 히스토리
    history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    # 메타데이터
    revive_count: int = 0  # 재심사/재구성 횟수
    is_retired: bool = False
    retire_reason: Optional[str] = None

    def update_from_trade(self, pnl: float, win: bool) -> Dict[str, Any]:
        """거래 결과로 상태 업데이트"""
        self.total_trades += 1
        self.updated_at = datetime.utcnow()

        changes = {
            'bot_id': self.bot_id,
            'timestamp': self.updated_at.isoformat(),
            'pnl': pnl,
            'win': win,
        }

        if win:
            self.win_trades += 1
            self.consecutive_wins += 1
            self.consecutive_losses = 0
            self.max_consecutive_wins = max(self.max_consecutive_wins, self.consecutive_wins)

            # HP 회복
            hp_gain = self.hp.HP_GAIN_WIN
            if self.consecutive_wins >= 3:
                hp_gain += self.hp.HP_GAIN_STREAK
                changes['streak_bonus'] = True

            new_hp, died = self.hp.modify(hp_gain)
            changes['hp_change'] = hp_gain
            changes['hp'] = new_hp

            # 경험치 획득 (수익에 비례)
            exp_gain = 10 + abs(pnl) * 0.5
            leveled_up, new_level = self.level.add_exp(exp_gain)
            changes['exp_gain'] = round(exp_gain, 2)
            changes['leveled_up'] = leveled_up
            changes['new_level'] = new_level if leveled_up else None

        else:
            self.loss_trades += 1
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            self.max_consecutive_losses = max(self.max_consecutive_losses, self.consecutive_losses)

            # HP 감소
            hp_loss = self.hp.HP_LOSS_LOSE
            if pnl < -5:  # 큰 손실
                hp_loss += self.hp.HP_LOSS_DRAWDOWN
                changes['big_loss'] = True

            new_hp, died = self.hp.modify(hp_loss)
            changes['hp_change'] = hp_loss
            changes['hp'] = new_hp
            changes['died'] = died

            # 경험치 소량 획득 (학습용)
            exp_gain = 3
            self.level.add_exp(exp_gain)
            changes['exp_gain'] = exp_gain

        # 등급 업데이트
        old_grade = self.grade
        self.grade = BotGrade.from_level(self.level.current)
        if self.grade != old_grade:
            changes['grade_up'] = True
            changes['old_grade'] = old_grade.en_name
            changes['new_grade'] = self.grade.en_name

        # 히스토리 기록
        self.history.append(changes)
        if len(self.history) > 1000:  # 최대 1000개 유지
            self.history = self.history[-1000:]

        return changes

    def update_from_reward_score(self, score: float) -> Dict[str, Any]:
        """보상 점수로 상태 업데이트 (일간/주간)"""
        self.updated_at = datetime.utcnow()

        # 높은 점수 = 추가 경험치
        if score >= 80:
            bonus_exp = 50
        elif score >= 60:
            bonus_exp = 30
        elif score >= 40:
            bonus_exp = 15
        else:
            bonus_exp = 5

        leveled_up, new_level = self.level.add_exp(bonus_exp)

        # 등급 동기화
        self.grade = BotGrade.from_level(self.level.current)

        return {
            'score': score,
            'bonus_exp': bonus_exp,
            'leveled_up': leveled_up,
            'new_level': new_level if leveled_up else None,
            'grade': self.grade.en_name,
        }

    def retire(self, reason: str) -> None:
        """봇 폐기"""
        self.is_retired = True
        self.retire_reason = reason
        self.updated_at = datetime.utcnow()
        logger.warning(f"Bot {self.bot_id} retired: {reason}")

    def revive(self, reset_hp: bool = True) -> Dict[str, Any]:
        """봇 재심사/재구성"""
        self.revive_count += 1
        self.is_retired = False
        self.retire_reason = None

        if reset_hp:
            self.hp.current = 50  # 반피로 재시작

        # 레벨 페널티
        if self.level.current > 10:
            self.level.current -= 5
            self.level.exp = 0

        self.updated_at = datetime.utcnow()

        return {
            'revive_count': self.revive_count,
            'new_level': self.level.current,
            'new_hp': self.hp.current,
        }

    def to_dict(self) -> Dict[str, Any]:
        """전체 상태 직렬화"""
        return {
            'bot_id': self.bot_id,
            'bot_name': self.bot_name,
            'level': self.level.to_dict(),
            'hp': self.hp.to_dict(),
            'grade': {
                'en': self.grade.en_name,
                'kr': self.grade.kr_name,
                'color': self.grade.color,
            },
            'stats': {
                'total_trades': self.total_trades,
                'win_trades': self.win_trades,
                'loss_trades': self.loss_trades,
                'win_rate': round(self.win_trades / self.total_trades * 100, 2) if self.total_trades > 0 else 0,
                'consecutive_wins': self.consecutive_wins,
                'consecutive_losses': self.consecutive_losses,
                'max_consecutive_wins': self.max_consecutive_wins,
                'max_consecutive_losses': self.max_consecutive_losses,
            },
            'meta': {
                'revive_count': self.revive_count,
                'is_retired': self.is_retired,
                'retire_reason': self.retire_reason,
                'created_at': self.created_at.isoformat(),
                'updated_at': self.updated_at.isoformat(),
            },
        }


class RPGSystem:
    """
    RPG 시스템 관리자

    모든 봇의 레벨/등급/HP 상태 관리
    """

    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = storage_path or "data/rpg_states.json"
        self.states: Dict[str, BotRPGState] = {}
        self.logger = logging.getLogger(self.__class__.__name__)

    def get_or_create_state(
        self,
        bot_id: str,
        bot_name: Optional[str] = None
    ) -> BotRPGState:
        """봇 상태 조회 또는 생성"""
        if bot_id not in self.states:
            self.states[bot_id] = BotRPGState(
                bot_id=bot_id,
                bot_name=bot_name or bot_id,
            )
            self.logger.info(f"Created new RPG state for {bot_id}")
        return self.states[bot_id]

    def update_from_trade(
        self,
        bot_id: str,
        pnl: float,
        win: bool,
        bot_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """거래 결과로 상태 업데이트"""
        state = self.get_or_create_state(bot_id, bot_name)
        return state.update_from_trade(pnl, win)

    def update_from_reward_score(
        self,
        bot_id: str,
        score: float,
        bot_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """보상 점수로 상태 업데이트"""
        state = self.get_or_create_state(bot_id, bot_name)
        return state.update_from_reward_score(score)

    def get_leaderboard(
        self,
        sort_by: str = "level",
        top_n: int = 10
    ) -> List[Dict[str, Any]]:
        """리더보드 생성"""
        states = list(self.states.values())

        if sort_by == "level":
            states.sort(key=lambda s: (s.level.current, s.level.total_exp), reverse=True)
        elif sort_by == "win_rate":
            states.sort(
                key=lambda s: s.win_trades / s.total_trades if s.total_trades > 0 else 0,
                reverse=True
            )
        elif sort_by == "grade":
            grade_order = {g: i for i, g in enumerate(BotGrade)}
            states.sort(key=lambda s: grade_order[s.grade], reverse=True)

        return [s.to_dict() for s in states[:top_n]]

    def save(self) -> None:
        """상태 저장"""
        import os
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

        data = {
            'timestamp': datetime.utcnow().isoformat(),
            'states': {k: v.to_dict() for k, v in self.states.items()},
        }

        with open(self.storage_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)

        self.logger.info(f"Saved {len(self.states)} RPG states to {self.storage_path}")

    def load(self) -> None:
        """상태 로드"""
        import os
        if not os.path.exists(self.storage_path):
            self.logger.info(f"No RPG state file found at {self.storage_path}")
            return

        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)

            for bot_id, state_data in data.get('states', {}).items():
                state = BotRPGState(
                    bot_id=bot_id,
                    bot_name=state_data.get('bot_name', bot_id),
                )
                state.level.current = state_data.get('level', {}).get('current', 1)
                state.level.exp = state_data.get('level', {}).get('exp', 0)
                state.level.total_exp = state_data.get('level', {}).get('total_exp', 0)
                state.hp.current = state_data.get('hp', {}).get('current', 100)
                state.total_trades = state_data.get('stats', {}).get('total_trades', 0)
                state.win_trades = state_data.get('stats', {}).get('win_trades', 0)
                state.loss_trades = state_data.get('stats', {}).get('loss_trades', 0)
                self.states[bot_id] = state

            self.logger.info(f"Loaded {len(self.states)} RPG states from {self.storage_path}")

        except Exception as e:
            self.logger.error(f"Failed to load RPG states: {e}")

    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """모든 상태 반환"""
        return {k: v.to_dict() for k, v in self.states.items()}

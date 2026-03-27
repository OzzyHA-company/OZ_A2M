"""
OZ_A2M 제2부서: 정보검증분석센터 - 데이터 모델

이 모듈은 정보검증분석센터에서 사용하는 모든 데이터 클래스와 열거형을 정의합니다.
- 매매 신호 유형 및 방향
- 검증 상태
- 필터링된 데이터, 트레이딩 신호, 검증 결과 등의 데이터 구조
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Any


class SignalType(Enum):
    """매매 신호 유형"""
    MOMENTUM = "momentum"           # 모멘텀
    BREAKOUT = "breakout"           # 돌파
    MEAN_REVERSION = "mean_reversion"  # 평균회귀
    TREND_FOLLOWING = "trend"       # 추세추종
    SENTIMENT = "sentiment"         # 감성기반


class SignalDirection(Enum):
    """신호 방향"""
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class VerificationStatus(Enum):
    """검증 상태"""
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


@dataclass
class FilteredData:
    """노이즈 필터링된 데이터

    Attributes:
        symbol: 거래 심볼 (예: "BTC-USDT")
        timestamp: 데이터 생성 시간
        original_price: 원본 가격
        filtered_price: 필터링된 가격
        confidence: 데이터 신뢰도 (0.0 ~ 1.0)
        is_outlier: 이상치 여부
        smoothing_applied: 적용된 스묘딩 방식 ('ema', 'kalman', 'median', 'none')
        metadata: 추가 메타데이터
    """
    symbol: str
    timestamp: datetime
    original_price: Decimal
    filtered_price: Decimal
    confidence: float = 1.0
    is_outlier: bool = False
    smoothing_applied: str = "none"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradingSignal:
    """트레이딩 신호

    Attributes:
        id: 고유 신호 ID
        symbol: 거래 심볼
        signal_type: 신호 유형 (모멘텀, 돌파 등)
        direction: 매매 방향 (LONG, SHORT, NEUTRAL)
        timestamp: 신호 생성 시간
        confidence: 신호 신뢰도 (0.0 ~ 1.0)
        entry_price: 진입 가격
        stop_loss: 손절 가격
        take_profit: 익절 가격
        position_size: 포지션 크기 (0.0 ~ 1.0, 포트폴리오 비율)
        indicators: 사용된 기술적 지표값들
        verification_score: 9-step 검증 점수
        expiration: 신호 만료 시간
        metadata: 추가 메타데이터
    """
    id: str
    symbol: str
    signal_type: SignalType
    direction: SignalDirection
    timestamp: datetime
    confidence: float
    entry_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    position_size: float = 0.0
    indicators: Dict[str, float] = field(default_factory=dict)
    verification_score: float = 0.0
    expiration: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """신호 생성 후 기본값 설정"""
        if self.expiration is None:
            # 기본 30분 후 만료
            self.expiration = self.timestamp + timedelta(minutes=30)

    def is_expired(self, current_time: Optional[datetime] = None) -> bool:
        """신호 만료 여부 확인"""
        if current_time is None:
            current_time = datetime.now()
        return current_time > self.expiration


@dataclass
class VerificationStep:
    """개별 검증 단계 결과

    Attributes:
        step_number: 검증 단계 번호 (1-9)
        name: 검증 단계 이름
        status: 검증 상태 (PASSED, FAILED, WARNING)
        score: 검증 점수 (0.0 ~ 1.0)
        message: 검증 결과 메시지
        details: 상세 검증 데이터
    """
    step_number: int
    name: str
    status: VerificationStatus
    score: float
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationResult:
    """9-step 검증 결과

    Attributes:
        signal_id: 검증된 신호 ID
        symbol: 거래 심볼
        timestamp: 검증 완료 시간
        overall_score: 전체 검증 점수 (0.0 ~ 1.0)
        status: 전체 검증 상태
        steps: 각 검증 단계 결과 목록
        passed_steps: 통과한 단계 수
        failed_steps: 실패한 단계 수
        warnings: 경고 메시지 목록
        recommendations: 개선 권장사항 목록
    """
    signal_id: str
    symbol: str
    timestamp: datetime
    overall_score: float
    status: VerificationStatus
    steps: List[VerificationStep]
    passed_steps: int = 0
    failed_steps: int = 0
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def __post_init__(self):
        """검증 결과 후처리"""
        # 통과/실패 단계 수 계산
        self.passed_steps = sum(
            1 for step in self.steps if step.status == VerificationStatus.PASSED
        )
        self.failed_steps = sum(
            1 for step in self.steps if step.status == VerificationStatus.FAILED
        )


@dataclass
class IndicatorValues:
    """기술적 지표 값들

    Attributes:
        symbol: 거래 심볼
        timestamp: 지표 계산 시간

        # Trend indicators
        sma_20: 20일 단순이동평균
        sma_50: 50일 단순이동평균
        ema_12: 12일 지수이동평균
        ema_26: 26일 지수이동평균

        # Momentum indicators
        rsi_14: 14일 RSI
        rsi_6: 6일 RSI
        macd: MACD 라인
        macd_signal: MACD 시그널 라인
        macd_histogram: MACD 히스토그램

        # Volatility indicators
        bb_upper: 볼린저 밴드 상단
        bb_middle: 볼린저 밴드 중간
        bb_lower: 볼린저 밴드 하단
        atr_14: 14일 ATR

        # Volume indicators
        volume_sma: 거래량 이동평균
        obv: OBV (On Balance Volume)

        # Custom indicators
        custom: 사용자 정의 지표값들
    """
    symbol: str
    timestamp: datetime

    # Trend indicators
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    ema_12: Optional[float] = None
    ema_26: Optional[float] = None

    # Momentum indicators
    rsi_14: Optional[float] = None
    rsi_6: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None

    # Volatility indicators
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    atr_14: Optional[float] = None

    # Volume indicators
    volume_sma: Optional[float] = None
    obv: Optional[float] = None

    # Custom indicators
    custom: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, float]:
        """지표값을 딕셔너리로 변환"""
        result = {}
        for key, value in self.__dict__.items():
            if key == 'custom':
                result.update(value)
            elif key not in ('symbol', 'timestamp') and value is not None:
                result[key] = value
        return result


@dataclass
class SignalPerformance:
    """신호 성과 데이터

    Attributes:
        signal_id: 신호 ID
        symbol: 거래 심볼
        entry_price: 실제 진입 가격
        exit_price: 실제 청산 가격
        entry_time: 진입 시간
        exit_time: 청산 시간
        pnl: 손익 (절대값)
        pnl_percent: 손익률 (%)
        max_drawdown: 최대 낙폭
        holding_period: 보유 기간 (초)
        was_profitable: 수익 여부
    """
    signal_id: str
    symbol: str
    entry_price: Decimal
    exit_price: Decimal
    entry_time: datetime
    exit_time: datetime
    pnl: Decimal = Decimal('0')
    pnl_percent: float = 0.0
    max_drawdown: float = 0.0
    holding_period: int = 0
    was_profitable: bool = False

    def __post_init__(self):
        """성과 계산"""
        self.pnl = self.exit_price - self.entry_price
        if self.entry_price != 0:
            self.pnl_percent = float(self.pnl / self.entry_price) * 100
        self.was_profitable = self.pnl > 0
        self.holding_period = int((self.exit_time - self.entry_time).total_seconds())


# 9-step 검증 가중치 설정
DEFAULT_STEP_WEIGHTS = {
    1: 0.10,   # Data Freshness
    2: 0.15,   # Price Consistency
    3: 0.10,   # Volume Validation
    4: 0.10,   # Volatility Check
    5: 0.10,   # Liquidity Assessment
    6: 0.15,   # Trend Confirmation
    7: 0.10,   # Momentum Validation
    8: 0.10,   # Signal Quality
    9: 0.10,   # Risk Assessment
}

# 검증 기본 설정
DEFAULT_VERIFICATION_CONFIG = {
    'min_overall_score': 0.65,
    'step_weights': DEFAULT_STEP_WEIGHTS,
    'freshness_threshold_seconds': 300,  # 5 minutes
    'price_deviation_threshold': 0.02,   # 2%
    'min_volume_ratio': 0.1,             # 10% of average
    'max_atr_ratio': 0.05,               # 5% of price
    'max_spread_pct': 0.005,             # 0.5%
    'min_adx': 20,
    'rsi_oversold': 30,
    'rsi_overbought': 70,
    'min_backtest_win_rate': 0.55,
    'max_position_size': 0.2,            # 20% of portfolio
}

# 노이즈 필터 기본 설정
DEFAULT_NOISE_FILTER_CONFIG = {
    'outlier_method': 'zscore',          # 'zscore', 'iqr', 'isolation_forest'
    'outlier_threshold': 3.0,            # Z-score threshold
    'smoothing_method': 'ema',           # 'ema', 'kalman', 'median', 'none'
    'ema_span': 10,
    'kalman_process_variance': 1e-5,
    'kalman_measurement_variance': 1e-2,
}

# 신호 생성 기본 설정
DEFAULT_SIGNAL_GENERATOR_CONFIG = {
    'enabled_types': ['momentum', 'breakout', 'mean_reversion'],
    'min_confidence': 0.6,
    'max_signals_per_symbol': 3,
    'signal_expiry_minutes': 30,
}

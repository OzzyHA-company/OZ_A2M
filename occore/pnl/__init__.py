"""
제5부서: 일일 성과분석팀 (PnL Center)

수익/손실 계산 및 성과 분석을 담당하는 부서입니다.

주요 기능:
- 거래 수익/손실 실시간 계산
- 일일/주간/월간 성과 집계
- 샤프 비율, MDD 등 성과 지표 분석
- 리포트 생성 및 출력
"""

# Models
from .models import (
    PnLType,
    TradeStatus,
    PositionSide,
    TradeRecord,
    DailyPnL,
    PerformanceMetrics,
    PositionSummary,
    DEFAULT_PNL_CONFIG,
)

# Exceptions
from .exceptions import (
    PnLError,
    TradeNotFoundError,
    InvalidTradeError,
    InsufficientDataError,
    CalculationError,
)

# Calculator
from .calculator import (
    ProfitCalculator,
    get_calculator,
    init_calculator,
)

# Performance
from .performance import (
    PerformanceAnalyzer,
    get_analyzer,
    init_analyzer,
)

# Report
from .report import (
    ReportGenerator,
    get_report_generator,
    init_report_generator,
)

# Config
from .config import DEFAULT_PNL_CONFIG

__all__ = [
    # Enums
    "PnLType",
    "TradeStatus",
    "PositionSide",
    # Dataclasses
    "TradeRecord",
    "DailyPnL",
    "PerformanceMetrics",
    "PositionSummary",
    # Exceptions
    "PnLError",
    "TradeNotFoundError",
    "InvalidTradeError",
    "InsufficientDataError",
    "CalculationError",
    # Classes
    "ProfitCalculator",
    "PerformanceAnalyzer",
    "ReportGenerator",
    # Singleton getters
    "get_calculator",
    "init_calculator",
    "get_analyzer",
    "init_analyzer",
    "get_report_generator",
    "init_report_generator",
    # Config
    "DEFAULT_PNL_CONFIG",
]

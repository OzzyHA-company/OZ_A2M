"""
제5부서: 일일 성과분석팀 (PnL Center) - 예외 정의

수익/손실 계산 및 성과 분석 관련 예외 클래스들을 정의합니다.
"""

from typing import Optional


class PnLError(Exception):
    """PnL 부서 기본 예외"""
    pass


class TradeNotFoundError(PnLError):
    """거래를 찾을 수 없을 때 발생하는 예외"""

    def __init__(self, trade_id: str):
        self.trade_id = trade_id
        super().__init__(f"Trade '{trade_id}' not found")


class InvalidTradeError(PnLError):
    """거래 데이터가 유효하지 않을 때 발생하는 예외"""

    def __init__(self, message: str, field: Optional[str] = None):
        self.field = field
        super().__init__(message)


class InsufficientDataError(PnLError):
    """성과 분석을 위한 데이터가 충분하지 않을 때 발생하는 예외"""

    def __init__(self, metric: str, required: int, actual: int):
        self.metric = metric
        self.required = required
        self.actual = actual
        super().__init__(
            f"Insufficient data for {metric}: "
            f"required {required}, got {actual}"
        )


class CalculationError(PnLError):
    """계산 중 오류 발생 시 예외"""

    def __init__(self, operation: str, reason: str):
        self.operation = operation
        super().__init__(f"Calculation error in {operation}: {reason}")

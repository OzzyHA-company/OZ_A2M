"""RiskMetricsCalculator stub — 호환성 모듈"""
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class RiskMetricsCalculator:
    """위험 메트릭스 계산기 (기본 구현)"""

    def calculate_metrics(self, trades: List[Any] = None, **kwargs) -> Dict:
        """거래 데이터 기반 위험 메트릭스 계산"""
        trades = trades or []
        return {
            "total_trades": len(trades),
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "risk_level": "low",
        }

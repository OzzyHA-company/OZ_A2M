"""
제5부서: 일일 성과분석팀 (PnL Center) - 설정

PnL 계산 및 성과 분석에 사용되는 기본 설정값들을 정의합니다.
"""

from decimal import Decimal
from typing import Dict, Any


DEFAULT_PNL_CONFIG: Dict[str, Any] = {
    # PnL 계산 설정
    'realized_pnl_threshold': Decimal('0.01'),  # 최소 실현 손익 단위
    'daily_reset_hour': 0,  # UTC 기준 일일 리셋 시간 (자정)
    'max_trade_history': 10000,  # 최대 거래 이력 저장 개수

    # 성과 분석 설정
    'sharpe_risk_free_rate': 0.02,  # 연간 무위험 수익률 (2%)
    'sharpe_periods_per_year': 252,  # 거래일 기준 (주식)
    'crypto_periods_per_year': 365,  # 암호화폐는 365일

    # 리포트 설정
    'report_format': 'table',  # 기본 출력 형식: 'json', 'csv', 'table'
    'report_timezone': 'UTC',
    'decimal_precision': 8,  # 소수점 정밀도

    # MDD 계산 설정
    'mdd_rolling_window': None,  # None이면 전체 기간

    # 수수료/슬리피지 기본값
    'default_fee_rate': Decimal('0.001'),  # 0.1%
    'default_slippage': Decimal('0.0005'),  # 0.05%
}


# 계산 설정
CALCULATION_CONFIG = {
    'decimal_precision': 8,
    'rounding_mode': 'ROUND_HALF_UP',
}


# 리포트 출력 형식별 설정
REPORT_FORMATS = {
    'table': {
        'header_style': 'bold',
        'border_char': '═',
        'column_width': 20,
    },
    'json': {
        'indent': 2,
        'sort_keys': True,
    },
    'csv': {
        'delimiter': ',',
        'include_header': True,
    },
}

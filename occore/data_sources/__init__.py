"""
OZ_A2M 통합 데이터 소스 어댑터

부서별 데이터 제공:
- 제1부서 (관제탑): OpenBB, yfinance 통합
- 외부 탐색팀: 뉴스, RSS, 감성 분석
- 제2부서 (검증센터): 데이터 검증 및 신호 생성
"""

from .openbb_adapter import OpenBBAdapter
from .news_collector import NewsCollector, SentimentAnalyzer
from .data_router import DataRouter

__all__ = [
    "OpenBBAdapter",
    "NewsCollector",
    "SentimentAnalyzer",
    "DataRouter",
]

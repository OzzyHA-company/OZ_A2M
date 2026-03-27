"""
OZ_A2M 데이터 라우터

모든 데이터 소스(거래소, OpenBB, 뉴스)를 수집하고 각 부서로 라우팅
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class Department(Enum):
    """OZ_A2M 부서"""
    CONTROL_TOWER = "control_tower"      # 제1부서: 관제탑
    VERIFICATION = "verification"        # 제2부서: 검증센터
    SECURITY = "security"                # 제3부서: 보안팀
    DEVOPS = "devops"                    # 제4부서: 유지보수
    PNL = "pnl"                          # 제5부서: 성과분석
    RND = "rnd"                          # 제6부서: 연구개발
    SCOUT = "scout"                      # 외부 탐색팀


@dataclass
class DataPackage:
    """데이터 패키지"""
    source: str                          # 데이터 출처 (exchange, openbb, news)
    department: Department               # 대상 부서
    data_type: str                       # 데이터 유형 (price, news, sentiment)
    payload: Dict[str, Any]              # 실제 데이터
    timestamp: datetime
    priority: int = 5                    # 우선순위 (1-10, 낮을수록 중요)


class DataRouter:
    """
    데이터 라우터

    기능:
    - 다양한 데이터 소스 수집 통합
    - 부서별 데이터 라우팅
    - 데이터 큐 관리
    - Elasticsearch 저장 연동
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}

        # 데이터 소스
        self._openbb = None
        self._news_collector = None
        self._es_client = None

        # 큐
        self._queues: Dict[Department, List[DataPackage]] = {
            dept: [] for dept in Department
        }

        self._init_sources()

    def _init_sources(self):
        """데이터 소스 초기화"""
        try:
            from .openbb_adapter import OpenBBAdapter
            self._openbb = OpenBBAdapter()
        except Exception as e:
            logger.warning(f"OpenBB not initialized: {e}")

        try:
            from .news_collector import NewsCollector
            self._news_collector = NewsCollector()
        except Exception as e:
            logger.warning(f"NewsCollector not initialized: {e}")

    def route_price_data(self, symbol: str, data: Dict[str, Any],
                         source: str = "exchange") -> None:
        """
        가격 데이터 라우팅

        - 제1부서 (관제탑): 실시간 전황판 업데이트
        - 제2부서 (검증): 신호 생성
        - 제3부서 (보안): 이상 가격 감지
        """
        package = DataPackage(
            source=source,
            department=Department.CONTROL_TOWER,
            data_type="price",
            payload={"symbol": symbol, **data},
            timestamp=datetime.now(),
            priority=1
        )

        self._queues[Department.CONTROL_TOWER].append(package)
        self._queues[Department.VERIFICATION].append(package)

        logger.debug(f"Routed price data for {symbol}")

    def route_news_data(self, articles: List[Any]) -> None:
        """
        뉴스 데이터 라우팅

        - 외부 탐색팀: 원본 수집
        - 제2부서 (검증): 감성 분석 및 신호 생성
        - 제1부서 (관제탑): 통합 전황판 표시
        """
        package = DataPackage(
            source="news",
            department=Department.SCOUT,
            data_type="news",
            payload={"articles": articles},
            timestamp=datetime.now(),
            priority=3
        )

        self._queues[Department.SCOUT].append(package)
        self._queues[Department.VERIFICATION].append(package)
        self._queues[Department.CONTROL_TOWER].append(package)

        logger.debug(f"Routed {len(articles)} news articles")

    def route_sentiment_data(self, symbol: str, sentiment: Dict[str, Any]) -> None:
        """
        감성 데이터 라우팅

        - 제2부서 (검증): 매매 신호 생성
        - 제6부서 (R&D): 전략 최적화
        - 제1부서 (관제탑): 시장 감정 표시
        """
        package = DataPackage(
            source="sentiment",
            department=Department.VERIFICATION,
            data_type="sentiment",
            payload={"symbol": symbol, **sentiment},
            timestamp=datetime.now(),
            priority=2
        )

        self._queues[Department.VERIFICATION].append(package)
        self._queues[Department.RND].append(package)
        self._queues[Department.CONTROL_TOWER].append(package)

    def route_audit_log(self, log_entry: Dict[str, Any]) -> None:
        """
        감사 로그 라우팅

        - 제3부서 (보안): 보안 감사 로그
        - 제4부서 (유지보수): 시스템 모니터링
        """
        package = DataPackage(
            source="audit",
            department=Department.SECURITY,
            data_type="audit_log",
            payload=log_entry,
            timestamp=datetime.now(),
            priority=2
        )

        self._queues[Department.SECURITY].append(package)
        self._queues[Department.DEVOPS].append(package)

    def get_queue(self, department: Department, clear: bool = True) -> List[DataPackage]:
        """부서별 큐 조회"""
        items = self._queues[department].copy()
        if clear:
            self._queues[department] = []
        return items

    def get_queue_stats(self) -> Dict[str, int]:
        """큐 상태 통계"""
        return {
            dept.value: len(queue)
            for dept, queue in self._queues.items()
        }

    def collect_all(self, symbols: List[str]) -> Dict[str, Any]:
        """
        모든 데이터 소스에서 수집

        Args:
            symbols: 수집할 심볼 목록

        Returns:
            통합 데이터 패키지
        """
        results = {
            "timestamp": datetime.now().isoformat(),
            "symbols": symbols,
            "prices": {},
            "news": {},
            "sentiment": {}
        }

        # 가격 데이터 수집
        if self._openbb:
            for symbol in symbols:
                try:
                    price_data = self._openbb.get_stock_price(symbol)
                    if price_data:
                        results["prices"][symbol] = price_data
                        self.route_price_data(symbol, price_data, "openbb")
                except Exception as e:
                    logger.error(f"Error collecting price for {symbol}: {e}")

        # 뉴스 데이터 수집
        if self._news_collector:
            for symbol in symbols:
                try:
                    articles = self._news_collector.collect_yahoo_news(symbol)
                    if articles:
                        results["news"][symbol] = [
                            {
                                "title": a.title,
                                "sentiment": a.sentiment_label,
                                "score": a.sentiment_score
                            }
                            for a in articles
                        ]

                        sentiment_summary = self._news_collector.get_sentiment_summary(articles)
                        results["sentiment"][symbol] = sentiment_summary

                        self.route_news_data(articles)
                        self.route_sentiment_data(symbol, sentiment_summary)

                except Exception as e:
                    logger.error(f"Error collecting news for {symbol}: {e}")

        return results

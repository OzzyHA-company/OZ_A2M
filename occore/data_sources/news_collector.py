"""
OZ_A2M 외부 탐색팀: 뉴스 수집 및 감성 분석

외부 뉴스, RSS, 커뮤니티 데이터 수집 및 감성 분석
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
import re

logger = logging.getLogger(__name__)


@dataclass
class NewsArticle:
    """뉴스 기사 데이터"""
    title: str
    content: str
    url: str
    source: str
    published_at: datetime
    symbols: List[str]
    sentiment_score: Optional[float] = None
    sentiment_label: Optional[str] = None


class SentimentAnalyzer:
    """
    VADER 기반 감성 분석기

    기능:
    - 뉴스 제목/본문 감성 분석
    - 암호화폐/주식 특화 감성 사전
    - 긍정/부정/중립 분류
    """

    def __init__(self):
        self._analyzer = None
        self._init_analyzer()

    def _init_analyzer(self):
        """VADER 분석기 초기화"""
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            self._analyzer = SentimentIntensityAnalyzer()

            # 금융/암호화폐 특화 단어 추가
            self._analyzer.lexicon.update({
                'pump': 2.0,
                'dump': -2.0,
                'moon': 3.0,
                'crash': -3.0,
                'bullish': 2.5,
                'bearish': -2.5,
                'hodl': 1.0,
                'fomo': -1.0,
                'fud': -2.5,
                'mooning': 3.0,
                'buying': 1.5,
                'selling': -1.5,
                'long': 1.0,
                'short': -1.0,
                'breakout': 2.0,
                'breakdown': -2.0,
                'support': 1.0,
                'resistance': -0.5,
                'correction': -1.5,
                'rally': 2.5,
                'dip': -1.0,
            })

        except Exception as e:
            logger.error(f"Failed to init sentiment analyzer: {e}")

    def analyze(self, text: str) -> Dict[str, Any]:
        """
        텍스트 감성 분석

        Args:
            text: 분석할 텍스트

        Returns:
            감성 분석 결과 (compound, pos, neg, neu, label)
        """
        if not self._analyzer:
            return {"compound": 0, "label": "neutral"}

        try:
            scores = self._analyzer.polarity_scores(text)

            # 레이블 결정
            compound = scores['compound']
            if compound >= 0.05:
                label = "positive"
            elif compound <= -0.05:
                label = "negative"
            else:
                label = "neutral"

            return {
                "compound": compound,
                "positive": scores['pos'],
                "negative": scores['neg'],
                "neutral": scores['neu'],
                "label": label
            }

        except Exception as e:
            logger.error(f"Sentiment analysis error: {e}")
            return {"compound": 0, "label": "neutral"}

    def analyze_batch(self, texts: List[str]) -> List[Dict[str, Any]]:
        """배치 감성 분석"""
        return [self.analyze(text) for text in texts]


class NewsCollector:
    """
    뉴스 수집기

    기능:
    - RSS 피드 수집
    - 뉴스 크롤링
    - 키워드 기반 필터링
    - 실시간 뉴스 모니터링
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.sentiment_analyzer = SentimentAnalyzer()
        self._rss_feeds = self.config.get('rss_feeds', [])
        self._keywords = self.config.get('keywords', [
            'bitcoin', 'btc', 'ethereum', 'eth', 'crypto',
            'fed', 'fomc', 'inflation', 'recession',
            'sec', 'etf', 'blackrock', ' grayscale'
        ])

    def collect_from_rss(self, feed_url: Optional[str] = None) -> List[NewsArticle]:
        """RSS 피드에서 뉴스 수집"""
        articles = []

        try:
            import feedparser

            feeds = [feed_url] if feed_url else self._rss_feeds

            for url in feeds:
                try:
                    feed = feedparser.parse(url)

                    for entry in feed.entries[:20]:  # 최신 20개
                        title = entry.get('title', '')
                        content = entry.get('summary', '')

                        # 키워드 필터링
                        if not self._contains_keywords(title + content):
                            continue

                        # 심볼 추출
                        symbols = self._extract_symbols(title + content)

                        # 감성 분석
                        sentiment = self.sentiment_analyzer.analyze(title)

                        article = NewsArticle(
                            title=title,
                            content=content,
                            url=entry.get('link', ''),
                            source=feed.feed.get('title', url),
                            published_at=self._parse_date(entry.get('published')),
                            symbols=symbols,
                            sentiment_score=sentiment['compound'],
                            sentiment_label=sentiment['label']
                        )

                        articles.append(article)

                except Exception as e:
                    logger.error(f"RSS parse error for {url}: {e}")

        except ImportError:
            logger.warning("feedparser not installed, skipping RSS")

        return articles

    def collect_yahoo_news(self, symbol: str) -> List[NewsArticle]:
        """Yahoo Finance에서 뉴스 수집"""
        articles = []

        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            news_list = ticker.news[:10]

            for item in news_list:
                title = item.get('title', '')
                content = item.get('summary', '')

                sentiment = self.sentiment_analyzer.analyze(title)

                article = NewsArticle(
                    title=title,
                    content=content,
                    url=item.get('link', ''),
                    source=item.get('publisher', 'Yahoo Finance'),
                    published_at=datetime.fromtimestamp(item.get('published', 0)),
                    symbols=[symbol],
                    sentiment_score=sentiment['compound'],
                    sentiment_label=sentiment['label']
                )

                articles.append(article)

        except Exception as e:
            logger.error(f"Yahoo news collection error: {e}")

        return articles

    def _contains_keywords(self, text: str) -> bool:
        """텍스트에 키워드 포함 여부 확인"""
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in self._keywords)

    def _extract_symbols(self, text: str) -> List[str]:
        """텍스트에서 심볼 추출"""
        # 대문자 2-5글자 패턴 (주식 심볼)
        pattern = r'\b[A-Z]{2,5}\b'
        matches = re.findall(pattern, text)

        # 일반적인 단어 필터링
        common_words = {'CEO', 'CFO', 'THE', 'AND', 'FOR', 'USD', 'ETF'}
        symbols = [s for s in matches if s not in common_words]

        return list(set(symbols))

    def _parse_date(self, date_str: Optional[str]) -> datetime:
        """날짜 문자열 파싱"""
        if not date_str:
            return datetime.now()

        try:
            # RSS 표준 형식
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str)
        except:
            try:
                return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            except:
                return datetime.now()

    def get_sentiment_summary(self, articles: List[NewsArticle]) -> Dict[str, Any]:
        """뉴스 감성 요약"""
        if not articles:
            return {"count": 0, "average_sentiment": 0, "label": "neutral"}

        scores = [a.sentiment_score for a in articles if a.sentiment_score is not None]
        avg_score = sum(scores) / len(scores) if scores else 0

        positive = sum(1 for s in scores if s >= 0.05)
        negative = sum(1 for s in scores if s <= -0.05)
        neutral = len(scores) - positive - negative

        if avg_score >= 0.1:
            label = "positive"
        elif avg_score <= -0.1:
            label = "negative"
        else:
            label = "neutral"

        return {
            "count": len(articles),
            "average_sentiment": avg_score,
            "label": label,
            "positive_count": positive,
            "negative_count": negative,
            "neutral_count": neutral,
            "timestamp": datetime.now().isoformat()
        }

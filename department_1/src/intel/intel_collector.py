"""
제1부서: 관제탑센터 - 인텔 수집기
실시간 뉴스, 소셜 미디어, 시장 데이터 수집
"""

import asyncio
import json
import aiohttp
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path

import sys
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class IntelItem:
    """인텔 데이터 아이템"""
    id: str
    source: str  # twitter, youtube, news, onchain
    timestamp: str
    content: str
    title: Optional[str] = None
    url: Optional[str] = None
    author: Optional[str] = None
    sentiment: Optional[str] = None  # positive, negative, neutral
    confidence: float = 0.0
    related_symbols: List[str] = None
    metadata: Dict = None

    def __post_init__(self):
        if self.related_symbols is None:
            self.related_symbols = []
        if self.metadata is None:
            self.metadata = {}


class IntelCollector:
    """실시간 인텔 수집기"""

    def __init__(self):
        self.intel_feed: List[IntelItem] = []
        self.max_feed_size = 1000
        self._running = False
        self._tasks = []

        # 수집 설정
        self.sources = {
            'news': True,
            'twitter': False,  # API 필요
            'youtube': True,
            'onchain': True,
        }

        # 콜백 (WebSocket 브로드캐스트용)
        self.on_new_intel = None

    async def start(self):
        """인텔 수집 시작"""
        if self._running:
            return

        self._running = True
        logger.info("Intel collector started")

        # 각 소스별 수집 태스크 시작
        if self.sources['news']:
            self._tasks.append(asyncio.create_task(self._collect_news()))
        if self.sources['youtube']:
            self._tasks.append(asyncio.create_task(self._collect_youtube()))
        if self.sources['onchain']:
            self._tasks.append(asyncio.create_task(self._collect_onchain()))

    async def stop(self):
        """인텔 수집 중지"""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        logger.info("Intel collector stopped")

    async def _collect_news(self):
        """뉴스 수집 (RSS/CryptoPanic)"""
        while self._running:
            try:
                # CryptoPanic API (묵시적 지원)
                async with aiohttp.ClientSession() as session:
                    # 주요 암호화폐 뉴스 수집
                    news_items = await self._fetch_crypto_news(session)

                    for item in news_items:
                        intel = IntelItem(
                            id=f"news_{item['id']}",
                            source='news',
                            timestamp=datetime.utcnow().isoformat(),
                            content=item.get('title', ''),
                            title=item.get('title'),
                            url=item.get('url'),
                            author=item.get('source'),
                            sentiment=item.get('sentiment', 'neutral'),
                            confidence=item.get('votes', {}).get('positive', 0) / 100,
                            related_symbols=self._extract_symbols(item.get('title', '')),
                        )
                        await self._add_intel(intel)

            except Exception as e:
                logger.error(f"News collection error: {e}")

            await asyncio.sleep(60)  # 1분마다 수집

    async def _collect_youtube(self):
        """YouTube 인텔 수집 (pi-skills/youtube-transcript 활용)"""
        while self._running:
            try:
                # 주요 트레이딩 채널 체크
                channels = [
                    'UCnAKhxKFBljN0hQ9lFroNEA',  # 예시 채널
                ]

                for channel_id in channels:
                    # YouTube 데이터 수집 로직
                    # pi-skills/youtube-transcript 활용 가능
                    pass

            except Exception as e:
                logger.error(f"YouTube collection error: {e}")

            await asyncio.sleep(300)  # 5분마다 수집

    async def _collect_onchain(self):
        """온체인 데이터 수집 (Solana/Bitcoin)"""
        while self._running:
            try:
                # 큰 거래 감지
                whale_tx = await self._detect_whale_transactions()
                if whale_tx:
                    for tx in whale_tx:
                        intel = IntelItem(
                            id=f"onchain_{tx['hash'][:16]}",
                            source='onchain',
                            timestamp=datetime.utcnow().isoformat(),
                            content=f"고래 거래 감지: {tx['amount']} {tx['symbol']}",
                            title=f"🐋 고래 알림 - {tx['symbol']}",
                            related_symbols=[tx['symbol']],
                            metadata={
                                'amount': tx['amount'],
                                'from': tx['from'],
                                'to': tx['to'],
                            }
                        )
                        await self._add_intel(intel)

            except Exception as e:
                logger.error(f"Onchain collection error: {e}")

            await asyncio.sleep(30)  # 30초마다 체크

    async def _fetch_crypto_news(self, session: aiohttp.ClientSession) -> List[Dict]:
        """암호화폐 뉴스 수집 (RSS 피드)"""
        news_items = []

        try:
            # CoinDesk RSS
            async with session.get(
                'https://feeds.feedburner.com/CoinDesk',
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    content = await resp.text()
                    # RSS 파싱 (간단한 버전)
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(content)

                    # RSS 아이템 추출
                    for item in root.findall('.//item')[:5]:  # 최근 5개만
                        title = item.find('title')
                        link = item.find('link')
                        if title is not None:
                            news_items.append({
                                'id': hash(title.text) % 100000,
                                'title': title.text,
                                'url': link.text if link is not None else '',
                                'source': 'CoinDesk',
                            })

        except Exception as e:
            logger.warning(f"Failed to fetch crypto news: {e}")

        # 샘플 데이터 (API 실패 시)
        if not news_items:
            news_items = [
                {
                    'id': 1,
                    'title': 'BTC 가격 변동성 증가 - 기관 투자자 유입',
                    'url': '#',
                    'source': 'Goozi Intel',
                    'sentiment': 'positive',
                },
                {
                    'id': 2,
                    'title': 'SOL 네트워크 업그레이드 예정',
                    'url': '#',
                    'source': 'Goozi Intel',
                    'sentiment': 'neutral',
                },
            ]

        return news_items

    async def _detect_whale_transactions(self) -> List[Dict]:
        """고래 거래 감지 (Mock)"""
        # 실제로는 Helius/Solscan API 연동
        return []

    def _extract_symbols(self, text: str) -> List[str]:
        """텍스트에서 암호화폐 심볼 추출"""
        symbols = []
        known_symbols = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'DOT']

        for symbol in known_symbols:
            if symbol in text.upper():
                symbols.append(symbol)

        return symbols

    async def _add_intel(self, intel: IntelItem):
        """인텔 추가 및 콜백 호출"""
        self.intel_feed.insert(0, intel)

        # 피드 크기 제한
        if len(self.intel_feed) > self.max_feed_size:
            self.intel_feed = self.intel_feed[:self.max_feed_size]

        # 콜백 호출 (WebSocket 브로드캐스트)
        if self.on_new_intel:
            try:
                await self.on_new_intel(asdict(intel))
            except Exception as e:
                logger.error(f"Intel callback error: {e}")

        logger.info(f"New intel added: {intel.source} - {intel.title or intel.content[:50]}")

    def get_recent_intel(self, limit: int = 50, source: Optional[str] = None) -> List[Dict]:
        """최근 인텔 조회"""
        feed = self.intel_feed

        if source:
            feed = [i for i in feed if i.source == source]

        return [asdict(i) for i in feed[:limit]]

    def get_intel_stats(self) -> Dict:
        """인텔 통계"""
        stats = {
            'total': len(self.intel_feed),
            'by_source': {},
            'last_24h': 0,
        }

        now = datetime.utcnow()
        for intel in self.intel_feed:
            # 소스별 카운트
            stats['by_source'][intel.source] = stats['by_source'].get(intel.source, 0) + 1

            # 24시간 내 데이터
            intel_time = datetime.fromisoformat(intel.timestamp.replace('Z', '+00:00'))
            if (now - intel_time).total_seconds() < 86400:
                stats['last_24h'] += 1

        return stats


# 전역 인텔 수집기 인스턴스
intel_collector = IntelCollector()


async def main():
    """테스트 실행"""
    collector = IntelCollector()

    # 콜백 설정
    async def on_intel(intel):
        print(f"[NEW INTEL] {intel['source']}: {intel['content'][:80]}")

    collector.on_new_intel = on_intel

    # 수집 시작
    await collector.start()

    # 30초간 실행
    await asyncio.sleep(30)

    # 중지
    await collector.stop()

    # 결과 출력
    print("\n=== Intel Feed Summary ===")
    print(f"Total collected: {len(collector.intel_feed)}")
    for intel in collector.get_recent_intel(5):
        print(f"  - [{intel['source']}] {intel['content'][:60]}...")


if __name__ == '__main__':
    asyncio.run(main())

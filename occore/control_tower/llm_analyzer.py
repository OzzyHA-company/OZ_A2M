"""
OZ_A2M 제1부서: 관제탑센터 - LLM 분석 엔진

AI 기반 시장 분석 및 인사이트 생성
"""

import os
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any

from .collector import MarketSnapshot
from .alert_manager import AlertManager, AlertLevel, AlertCategory

logger = logging.getLogger(__name__)


@dataclass
class MarketInsight:
    """시장 인사이트"""
    timestamp: datetime
    symbol: str
    sentiment: str  # 'bullish', 'bearish', 'neutral'
    confidence: float  # 0.0 ~ 1.0
    summary: str
    key_factors: List[str]
    recommendation: str
    risk_level: str  # 'low', 'medium', 'high'


class LLMAnalyzer:
    """
    LLM 기반 시장 분석 엔진

    기능:
    - 시장 데이터 AI 분석
    - 자연어 인사이트 생성
    - 트레이딩 시그널 생성
    """

    def __init__(self, alert_manager: AlertManager, config: Optional[Dict] = None):
        self.config = config or {}
        self.alert_manager = alert_manager

        # LLM 설정
        self._provider = self.config.get('llm_provider', 'gemini')
        self._model = self.config.get('model', 'gemini-2.5-flash')
        self._api_key = self.config.get('api_key') or os.getenv('GEMINI_API_KEY')

    async def analyze_market(self, snapshot: MarketSnapshot) -> Optional[MarketInsight]:
        """시장 데이터 분석"""
        try:
            # 데이터 준비
            market_data = self._prepare_market_data(snapshot)

            # 프롬프트 생성
            prompt = self._create_analysis_prompt(market_data)

            # LLM 호출
            response = await self._call_llm(prompt)

            if not response:
                return None

            # 응답 파싱
            insight = self._parse_insight(response, snapshot.symbol)

            # 고위험 인사이트는 알림 생성
            if insight and insight.risk_level == 'high':
                self.alert_manager.create_alert(
                    level=AlertLevel.HIGH,
                    category=AlertCategory.PRICE,
                    title=f"{snapshot.symbol} 고위험 시장 상황",
                    message=insight.summary,
                    source='llm_analyzer',
                    metadata={
                        'symbol': snapshot.symbol,
                        'sentiment': insight.sentiment,
                        'confidence': insight.confidence
                    }
                )

            return insight

        except Exception as e:
            logger.error(f"Error analyzing market: {e}")
            return None

    def _prepare_market_data(self, snapshot: MarketSnapshot) -> Dict[str, Any]:
        """시장 데이터 준비"""
        exchanges_data = []

        for ex, ticker in snapshot.exchanges.items():
            exchanges_data.append({
                'exchange': ex,
                'price': float(ticker.last),
                'bid': float(ticker.bid),
                'ask': float(ticker.ask),
                'volume_24h': float(ticker.volume_24h),
                'change_24h_pct': ticker.change_24h_pct
            })

        return {
            'symbol': snapshot.symbol,
            'timestamp': snapshot.timestamp.isoformat(),
            'average_price': float(snapshot.average_price),
            'total_volume': float(snapshot.total_volume),
            'price_variance_pct': snapshot.price_variance,
            'exchanges': exchanges_data,
            'arbitrage_opportunities': len(snapshot.arbitrage_opportunities)
        }

    def _create_analysis_prompt(self, market_data: Dict) -> str:
        """분석 프롬프트 생성"""
        return f"""다음 암호화폐 시장 데이터를 분석하고 트레이딩 인사이트를 제공하세요.

심볼: {market_data['symbol']}
타임스탬프: {market_data['timestamp']}
평균 가격: ${market_data['average_price']:.4f}
24시간 거래량: ${market_data['total_volume']:,.2f}
가격 분산: {market_data['price_variance_pct']:.2f}%
아비트라지 기회: {market_data['arbitrage_opportunities']}개

거래소별 데이터:
{json.dumps(market_data['exchanges'], indent=2, ensure_ascii=False)}

다음 JSON 형식으로 응답하세요:
{{
    "sentiment": "bullish|bearish|neutral",
    "confidence": 0.0~1.0,
    "summary": "시장 상황 요약 (한국어)",
    "key_factors": ["주요 요인 1", "주요 요인 2", "주요 요인 3"],
    "recommendation": "트레이딩 추천 (한국어)",
    "risk_level": "low|medium|high"
}}
"""

    async def _call_llm(self, prompt: str) -> Optional[str]:
        """LLM API 호출"""
        try:
            if self._provider == 'gemini':
                return await self._call_gemini(prompt)
            elif self._provider == 'openai':
                return await self._call_openai(prompt)
            else:
                logger.error(f"Unknown LLM provider: {self._provider}")
                return None

        except Exception as e:
            logger.error(f"LLM API error: {e}")
            return None

    async def _call_gemini(self, prompt: str) -> Optional[str]:
        """Gemini API 호출"""
        try:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)
            model = genai.GenerativeModel(self._model)

            response = model.generate_content(prompt)
            return response.text

        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return None

    async def _call_openai(self, prompt: str) -> Optional[str]:
        """OpenAI API 호출"""
        try:
            import openai

            client = openai.AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))

            response = await client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "당신은 암호화폐 트레이딩 전문가입니다."},
                    {"role": "user", "content": prompt}
                ]
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return None

    def _parse_insight(self, response: str, symbol: str) -> Optional[MarketInsight]:
        """LLM 응답 파싱"""
        try:
            # JSON 추출
            json_start = response.find('{')
            json_end = response.rfind('}')

            if json_start == -1 or json_end == -1:
                logger.warning("No JSON found in LLM response")
                return None

            json_str = response[json_start:json_end + 1]
            data = json.loads(json_str)

            return MarketInsight(
                timestamp=datetime.now(),
                symbol=symbol,
                sentiment=data.get('sentiment', 'neutral'),
                confidence=data.get('confidence', 0.5),
                summary=data.get('summary', ''),
                key_factors=data.get('key_factors', []),
                recommendation=data.get('recommendation', ''),
                risk_level=data.get('risk_level', 'medium')
            )

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return None

    async def generate_market_report(self, snapshots: List[MarketSnapshot]) -> str:
        """종합 시장 보고서 생성"""
        try:
            summaries = []
            for snapshot in snapshots:
                insight = await self.analyze_market(snapshot)
                if insight:
                    summaries.append(f"""
## {snapshot.symbol}
- 감정: {insight.sentiment.upper()} (신뢰도: {insight.confidence:.1%})
- 요약: {insight.summary}
- 추천: {insight.recommendation}
- 위험도: {insight.risk_level}
""")

            return f"""# OZ_A2M 시장 분석 보고서
생성 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{chr(10).join(summaries)}
"""

        except Exception as e:
            logger.error(f"Error generating report: {e}")
            return "보고서 생성 중 오류가 발생했습니다."

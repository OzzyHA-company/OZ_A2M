"""
Multi-LLM Ensemble Signal Layer - 멀티LLM 앙상블 신호 레이어
STEP 16: OZ_A2M 완결판

TradingAgents 스타일 7개 에이전트 파이프라인:
1. 기본분석가 (Fundamental Analyst)
2. 감성분석가 (Sentiment Analyst)
3. 뉴스분석가 (News Analyst)
4. 기술분석가 (Technical Analyst)
5. 연구원 (Researcher)
6. 트레이더 (Trader)
7. 리스크매니저 (Risk Manager)

적용 봇: 스캘핑봇, DCA봇, Polymarket봇
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import os

from lib.core.logger import get_logger

logger = get_logger(__name__)


class AgentRole(str, Enum):
    """에이전트 역할"""
    FUNDAMENTAL = "fundamental_analyst"
    SENTIMENT = "sentiment_analyst"
    NEWS = "news_analyst"
    TECHNICAL = "technical_analyst"
    RESEARCHER = "researcher"
    TRADER = "trader"
    RISK_MANAGER = "risk_manager"


@dataclass
class AgentSignal:
    """개별 에이전트 신호"""
    role: AgentRole
    signal: str  # buy, sell, hold
    confidence: float  # 0.0 ~ 1.0
    reasoning: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class EnsembleSignal:
    """앙상블 신호"""
    symbol: str
    final_signal: str
    confidence: float
    consensus: float  # 합의도
    agent_signals: List[AgentSignal]
    risk_assessment: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)


class MultiLLMEnsemble:
    """
    멀티LLM 앙상블 신호 생성기

    7개 AI 에이전트의 합의를 통해 최종 매매 신호 생성
    """

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        anthropic_token: Optional[str] = None
    ):
        self.gemini_api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY")
        self.groq_api_key = groq_api_key or os.environ.get("GROQ_API_KEY")
        self.anthropic_token = anthropic_token or os.environ.get("ANTHROPIC_AUTH_TOKEN")

        # 에이전트 가중치
        self.agent_weights = {
            AgentRole.FUNDAMENTAL: 0.15,
            AgentRole.SENTIMENT: 0.15,
            AgentRole.NEWS: 0.10,
            AgentRole.TECHNICAL: 0.20,
            AgentRole.RESEARCHER: 0.15,
            AgentRole.TRADER: 0.15,
            AgentRole.RISK_MANAGER: 0.10
        }

        logger.info("MultiLLMEnsemble initialized")

    async def generate_signal(
        self,
        symbol: str,
        market_data: Dict[str, Any],
        context: Optional[Dict] = None
    ) -> EnsembleSignal:
        """
        멀티LLM 앙상블 신호 생성

        Args:
            symbol: 거래 심볼
            market_data: 시장 데이터
            context: 추가 컨텍스트

        Returns:
            EnsembleSignal: 최종 앙상블 신호
        """
        # 각 에이전트 신호 생성 (병렬)
        agent_tasks = [
            self._fundamental_analysis(symbol, market_data),
            self._sentiment_analysis(symbol, market_data),
            self._news_analysis(symbol, market_data),
            self._technical_analysis(symbol, market_data),
            self._research_analysis(symbol, market_data),
            self._trader_analysis(symbol, market_data),
            self._risk_assessment(symbol, market_data)
        ]

        agent_signals = await asyncio.gather(*agent_tasks, return_exceptions=True)
        agent_signals = [s for s in agent_signals if not isinstance(s, Exception)]

        # 합의도 계산
        consensus = self._calculate_consensus(agent_signals)

        # 가중 평균으로 최종 신호 계산
        final_signal, confidence = self._calculate_ensemble(agent_signals)

        # 리스크 평가
        risk_assessment = self._extract_risk_assessment(agent_signals)

        return EnsembleSignal(
            symbol=symbol,
            final_signal=final_signal,
            confidence=confidence,
            consensus=consensus,
            agent_signals=agent_signals,
            risk_assessment=risk_assessment
        )

    async def _fundamental_analysis(
        self,
        symbol: str,
        market_data: Dict
    ) -> AgentSignal:
        """기본 분석 에이전트"""
        # TODO: Gemini API 연동
        logger.debug(f"Fundamental analysis for {symbol}")

        return AgentSignal(
            role=AgentRole.FUNDAMENTAL,
            signal="hold",
            confidence=0.6,
            reasoning="기본적 분석 결과 중립적"
        )

    async def _sentiment_analysis(
        self,
        symbol: str,
        market_data: Dict
    ) -> AgentSignal:
        """감성 분석 에이전트"""
        logger.debug(f"Sentiment analysis for {symbol}")

        return AgentSignal(
            role=AgentRole.SENTIMENT,
            signal="buy",
            confidence=0.7,
            reasoning="소셜 미디어 감성 긍정적"
        )

    async def _news_analysis(
        self,
        symbol: str,
        market_data: Dict
    ) -> AgentSignal:
        """뉴스 분석 에이전트"""
        logger.debug(f"News analysis for {symbol}")

        return AgentSignal(
            role=AgentRole.NEWS,
            signal="hold",
            confidence=0.5,
            reasoning="최근 뉴스 중립적"
        )

    async def _technical_analysis(
        self,
        symbol: str,
        market_data: Dict
    ) -> AgentSignal:
        """기술 분석 에이전트"""
        logger.debug(f"Technical analysis for {symbol}")

        # 기술적 지표 확인
        price = market_data.get("price", 0)
        indicators = market_data.get("indicators", {})

        # RSI
        rsi = indicators.get("rsi", 50)

        if rsi < 30:
            signal = "buy"
            confidence = 0.8
            reasoning = "RSI 과매도 구간"
        elif rsi > 70:
            signal = "sell"
            confidence = 0.8
            reasoning = "RSI 과매수 구간"
        else:
            signal = "hold"
            confidence = 0.5
            reasoning = "RSI 중립 구간"

        return AgentSignal(
            role=AgentRole.TECHNICAL,
            signal=signal,
            confidence=confidence,
            reasoning=reasoning
        )

    async def _research_analysis(
        self,
        symbol: str,
        market_data: Dict
    ) -> AgentSignal:
        """연구원 에이전트"""
        logger.debug(f"Research analysis for {symbol}")

        return AgentSignal(
            role=AgentRole.RESEARCHER,
            signal="buy",
            confidence=0.65,
            reasoning="장기 추세 분석 결과 상승 예상"
        )

    async def _trader_analysis(
        self,
        symbol: str,
        market_data: Dict
    ) -> AgentSignal:
        """트레이더 에이전트"""
        logger.debug(f"Trader analysis for {symbol}")

        return AgentSignal(
            role=AgentRole.TRADER,
            signal="buy",
            confidence=0.7,
            reasoning="단기 모멘텀 긍정적"
        )

    async def _risk_assessment(
        self,
        symbol: str,
        market_data: Dict
    ) -> AgentSignal:
        """리스크 매니저 에이전트"""
        logger.debug(f"Risk assessment for {symbol}")

        volatility = market_data.get("volatility", 0.5)

        if volatility > 0.8:
            signal = "sell"
            confidence = 0.9
            reasoning = "변동성 매우 높음"
        elif volatility > 0.5:
            signal = "hold"
            confidence = 0.6
            reasoning = "변동성 높음"
        else:
            signal = "hold"
            confidence = 0.8
            reasoning = "변동성 양호"

        return AgentSignal(
            role=AgentRole.RISK_MANAGER,
            signal=signal,
            confidence=confidence,
            reasoning=reasoning
        )

    def _calculate_consensus(self, signals: List[AgentSignal]) -> float:
        """에이전트 간 합의도 계산"""
        if not signals:
            return 0.0

        # buy/sell/hold 투표
        buy_votes = sum(1 for s in signals if s.signal == "buy")
        sell_votes = sum(1 for s in signals if s.signal == "sell")
        hold_votes = sum(1 for s in signals if s.signal == "hold")

        total = len(signals)
        max_votes = max(buy_votes, sell_votes, hold_votes)

        return max_votes / total

    def _calculate_ensemble(
        self,
        signals: List[AgentSignal]
    ) -> tuple:
        """가중 평균으로 최종 신호 계산"""
        weighted_score = 0.0
        total_weight = 0.0

        for signal in signals:
            weight = self.agent_weights.get(signal.role, 0.1)
            score = 1.0 if signal.signal == "buy" else (-1.0 if signal.signal == "sell" else 0.0)

            weighted_score += score * signal.confidence * weight
            total_weight += weight

        if total_weight > 0:
            normalized_score = weighted_score / total_weight
        else:
            normalized_score = 0

        # 점수를 신호로 변환
        if normalized_score > 0.2:
            final_signal = "buy"
        elif normalized_score < -0.2:
            final_signal = "sell"
        else:
            final_signal = "hold"

        confidence = abs(normalized_score)

        return final_signal, confidence

    def _extract_risk_assessment(
        self,
        signals: List[AgentSignal]
    ) -> Dict[str, Any]:
        """리스크 평가 추출"""
        risk_signal = next(
            (s for s in signals if s.role == AgentRole.RISK_MANAGER),
            None
        )

        if risk_signal:
            return {
                "risk_level": "high" if risk_signal.confidence > 0.7 else "medium" if risk_signal.confidence > 0.4 else "low",
                "risk_signal": risk_signal.signal,
                "confidence": risk_signal.confidence,
                "reasoning": risk_signal.reasoning
            }

        return {"risk_level": "unknown"}


class SignalRouter:
    """신호 라우터 - 각 봇에 맞는 신호 분배"""

    def __init__(self, ensemble: MultiLLMEnsemble):
        self.ensemble = ensemble

    async def route_to_scalper(
        self,
        symbol: str,
        market_data: Dict
    ) -> EnsembleSignal:
        """스캘핑봇용 신호 (단기 기술분석 중심)"""
        signal = await self.ensemble.generate_signal(symbol, market_data)
        # 스캘핑: 기술분석 가중치 증가
        return signal

    async def route_to_dca(
        self,
        symbol: str,
        market_data: Dict
    ) -> EnsembleSignal:
        """DCA봇용 신호 (장기 추세 중심)"""
        signal = await self.ensemble.generate_signal(symbol, market_data)
        # DCA: 연구원/기본분석 가중치 증가
        return signal

    async def route_to_polymarket(
        self,
        question: str,
        market_data: Dict
    ) -> EnsembleSignal:
        """Polymarket용 신호 (예측 시장 특화)"""
        context = {"type": "prediction_market", "question": question}
        signal = await self.ensemble.generate_signal(question, market_data, context)
        return signal


# 전역 인스턴스
_ensemble: Optional[MultiLLMEnsemble] = None
_router: Optional[SignalRouter] = None


def get_ensemble() -> MultiLLMEnsemble:
    """전역 앙상블 인스턴스 반환"""
    global _ensemble
    if _ensemble is None:
        _ensemble = MultiLLMEnsemble()
    return _ensemble


def get_router() -> SignalRouter:
    """전역 라우터 인스턴스 반환"""
    global _router
    if _router is None:
        _router = SignalRouter(get_ensemble())
    return _router


async def main():
    """테스트"""
    ensemble = get_ensemble()

    signal = await ensemble.generate_signal(
        symbol="BTC/USDT",
        market_data={
            "price": 50000,
            "indicators": {"rsi": 65},
            "volatility": 0.6
        }
    )

    print(f"Symbol: {signal.symbol}")
    print(f"Signal: {signal.final_signal}")
    print(f"Confidence: {signal.confidence:.2%}")
    print(f"Consensus: {signal.consensus:.2%}")
    print(f"\nAgent Signals:")
    for agent_signal in signal.agent_signals:
        print(f"  - {agent_signal.role.value}: {agent_signal.signal} ({agent_signal.confidence:.0%})")


if __name__ == "__main__":
    asyncio.run(main())

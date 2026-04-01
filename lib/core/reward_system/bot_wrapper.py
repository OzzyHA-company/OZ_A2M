"""
Bot Wrapper - Reward System 통합 봇 래퍼

기존 봇을 쉽게 Reward System에 통합하기 위한 데코레이터/래퍼

Features:
- 자동 거래 데이터 MQTT 발행
- LLM Confidence 전파 (Phase 2)
- 자동 HP/RPG 업데이트
- 에피소드 메모리 기록

Usage:
    @reward_aware(bot_id="grid_bot", bot_name="Grid Bot")
    async def my_trading_strategy(data):
        ...
        return TradeResult(pnl=profit, win=True)
"""

import asyncio
import functools
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Union
from contextlib import asynccontextmanager

try:
    import aiomqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False

logger = logging.getLogger(__name__)


@dataclass
class TradeResult:
    """거래 결과"""
    pnl: float              # 손익 (USD)
    pnl_pct: float = 0.0    # 수익률 (%)
    win: bool = False       # 승/패
    position_size: float = 0.0
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    holding_hours: float = 0.0
    symbol: str = "UNKNOWN"
    leverage: float = 1.0

    # 시장 데이터
    market_price: Optional[float] = None
    volume_24h: Optional[float] = None
    volatility_atr: Optional[float] = None
    trend: str = "sideways"
    market_regime: str = "normal"

    # AI/LLM 데이터 (Phase 2)
    llm_confidence: float = 0.5  # 0.0 ~ 1.0
    signal_strength: str = "neutral"  # strong, moderate, weak, neutral

    def to_mqtt_payload(self) -> Dict[str, Any]:
        """MQTT 발행용 페이로드"""
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'win': self.win,
            'position_size': self.position_size,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'holding_hours': self.holding_hours,
            'symbol': self.symbol,
            'leverage': self.leverage,
            'price': self.market_price,
            'volume_24h': self.volume_24h,
            'volatility_atr': self.volatility_atr,
            'trend': self.trend,
            'market_regime': self.market_regime,
            'llm_confidence': self.llm_confidence,
            'signal_strength': self.signal_strength,
        }


@dataclass
class SignalResult:
    """AI 신호 결과 (Phase 2 - LLM Confidence)"""
    signal: str  # buy, sell, hold
    confidence: float  # 0.0 ~ 1.0
    strength: str = "neutral"  # strong, moderate, weak
    reasoning: Optional[str] = None

    def to_mqtt_payload(self) -> Dict[str, Any]:
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'signal': self.signal,
            'llm_confidence': self.confidence,
            'signal_strength': self.strength,
            'reasoning': self.reasoning,
        }


class RewardSystemClient:
    """
    Reward System MQTT 클라이언트

    봇들이 Reward System과 통신하기 위한 클라이언트
    """

    def __init__(
        self,
        bot_id: str,
        bot_name: str,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
    ):
        self.bot_id = bot_id
        self.bot_name = bot_name
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port

        self._client: Optional[Any] = None
        self._connected = False
        self._buffer: List[Dict] = []  # 오프라인 버퍼

    async def connect(self):
        """MQTT 연결"""
        if not HAS_MQTT:
            logger.warning("aiomqtt not installed, operating in offline mode")
            return

        try:
            self._client = aiomqtt.Client(
                hostname=self.mqtt_host,
                port=self.mqtt_port,
                client_id=f"bot_{self.bot_id}",
            )
            await self._client.__aenter__()
            self._connected = True

            # 버퍼된 메시지 발행
            for payload in self._buffer:
                await self._publish(payload)
            self._buffer.clear()

            logger.info(f"Bot {self.bot_id} connected to Reward System")

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            self._connected = False

    async def disconnect(self):
        """연결 종료"""
        if self._client and self._connected:
            await self._client.__aexit__(None, None, None)
            self._connected = False

    async def publish_trade(self, result: TradeResult):
        """거래 결과 발행"""
        payload = result.to_mqtt_payload()
        payload['bot_name'] = self.bot_name

        topic = f"oz/a2m/bots/{self.bot_id}/trade"
        await self._publish_with_topic(topic, payload)

    async def publish_signal(self, result: SignalResult):
        """AI 신호 발행 (Phase 2)"""
        payload = result.to_mqtt_payload()

        topic = f"oz/a2m/bots/{self.bot_id}/signal"
        await self._publish_with_topic(topic, payload)

    async def publish_status(self, status: str, details: Optional[Dict] = None):
        """상태 발행"""
        payload = {
            'timestamp': datetime.utcnow().isoformat(),
            'status': status,
            'details': details or {},
        }

        topic = f"oz/a2m/bots/{self.bot_id}/status"
        await self._publish_with_topic(topic, payload)

    async def _publish_with_topic(self, topic: str, payload: Dict):
        """토픽으로 발행"""
        if not self._connected or not HAS_MQTT:
            # 오프라인 모드 - 버퍼에 저장
            self._buffer.append({'topic': topic, 'payload': payload})
            if len(self._buffer) > 100:
                self._buffer = self._buffer[-100:]
            return

        try:
            await self._client.publish(
                topic,
                json.dumps(payload),
                qos=1,
            )
        except Exception as e:
            logger.error(f"Publish error: {e}")
            self._buffer.append({'topic': topic, 'payload': payload})

    async def _publish(self, data: Dict):
        """버퍼 데이터 발행"""
        if not self._connected or not HAS_MQTT:
            return

        try:
            await self._client.publish(
                data['topic'],
                json.dumps(data['payload']),
                qos=1,
            )
        except Exception as e:
            logger.error(f"Buffer publish error: {e}")

    @asynccontextmanager
    async def session(self):
        """컨텍스트 매니저"""
        await self.connect()
        try:
            yield self
        finally:
            await self.disconnect()


def reward_aware(
    bot_id: str,
    bot_name: str,
    mqtt_host: str = "localhost",
    mqtt_port: int = 1883,
    auto_publish: bool = True,
):
    """
    Reward System 통합 데코레이터

    봇 함수를 Reward System과 연동

    Args:
        bot_id: 봇 ID
        bot_name: 봇 이름
        mqtt_host: MQTT 브로커 주소
        mqtt_port: MQTT 브로커 포트
        auto_publish: 자동 발행 여부

    Usage:
        @reward_aware(bot_id="grid_bot", bot_name="Grid Bot")
        async def grid_strategy(market_data):
            # ... 트레이딩 로직 ...
            return TradeResult(pnl=profit, win=profit > 0, ...)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            client = RewardSystemClient(
                bot_id=bot_id,
                bot_name=bot_name,
                mqtt_host=mqtt_host,
                mqtt_port=mqtt_port,
            )

            async with client.session():
                # 상태 발행 - 시작
                if auto_publish:
                    await client.publish_status("running")

                try:
                    # 원래 함수 실행
                    result = await func(*args, **kwargs)

                    # 결과 발행
                    if auto_publish and result is not None:
                        if isinstance(result, TradeResult):
                            await client.publish_trade(result)
                        elif isinstance(result, SignalResult):
                            await client.publish_signal(result)
                        elif isinstance(result, dict):
                            # 딕셔너리에서 TradeResult 생성
                            trade_result = TradeResult(**result)
                            await client.publish_trade(trade_result)

                    return result

                except Exception as e:
                    # 오류 상태 발행
                    if auto_publish:
                        await client.publish_status("error", {'error': str(e)})
                    raise

        return wrapper
    return decorator


class RewardAwareBot:
    """
    Reward System 통합 봇 기본 클래스

    상속받아 사용하는 방식

    Usage:
        class MyGridBot(RewardAwareBot):
            def __init__(self):
                super().__init__(bot_id="grid_bot", bot_name="Grid Bot")

            async def execute_trade(self, signal):
                # ... 거래 실행 ...
                return TradeResult(pnl=profit, win=profit > 0, ...)
    """

    def __init__(
        self,
        bot_id: str,
        bot_name: str,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
    ):
        self.bot_id = bot_id
        self.bot_name = bot_name
        self.client = RewardSystemClient(
            bot_id=bot_id,
            bot_name=bot_name,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
        )
        self._trade_count = 0
        self._total_pnl = 0.0

    async def connect(self):
        """Reward System 연결"""
        await self.client.connect()
        await self.client.publish_status("connected", {
            'bot_id': self.bot_id,
            'bot_name': self.bot_name,
        })

    async def disconnect(self):
        """연결 종료"""
        await self.client.publish_status("disconnected", {
            'total_trades': self._trade_count,
            'total_pnl': self._total_pnl,
        })
        await self.client.disconnect()

    async def report_trade(self, result: TradeResult) -> None:
        """거래 보고"""
        await self.client.publish_trade(result)
        self._trade_count += 1
        self._total_pnl += result.pnl

    async def report_signal(self, result: SignalResult) -> None:
        """신호 보고 (Phase 2)"""
        await self.client.publish_signal(result)

    async def report_status(self, status: str, details: Optional[Dict] = None):
        """상태 보고"""
        await self.client.publish_status(status, details)

    @asynccontextmanager
    async def session(self):
        """세션 컨텍스트"""
        await self.connect()
        try:
            yield self
        finally:
            await self.disconnect()


# TradingAgents 연동 (Phase 2)
class TradingAgentsBridge:
    """
    TradingAgents와 Reward System 연동 브릿지

    LLM Confidence를 Reward System에 전달
    """

    def __init__(
        self,
        bot_id: str,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
    ):
        self.bot_id = bot_id
        self.client = RewardSystemClient(
            bot_id=bot_id,
            bot_name=f"{bot_id}_trading_agents",
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
        )

    async def report_llm_consensus(
        self,
        agent_votes: Dict[str, str],  # {agent_name: decision}
        confidence: float,
        reasoning: Optional[str] = None,
    ):
        """
        TradingAgents 합의 결과 보고

        7개 에이전트 앙상블 결과를 Reward System에 전달
        """
        # 신호 강도 결정
        if confidence >= 0.8:
            strength = "strong"
        elif confidence >= 0.6:
            strength = "moderate"
        elif confidence >= 0.4:
            strength = "weak"
        else:
            strength = "neutral"

        result = SignalResult(
            signal=self._get_majority_vote(agent_votes),
            confidence=confidence,
            strength=strength,
            reasoning=reasoning,
        )

        await self.client.publish_signal(result)

    def _get_majority_vote(self, votes: Dict[str, str]) -> str:
        """다수결 투표"""
        from collections import Counter

        if not votes:
            return "hold"

        vote_counts = Counter(votes.values())
        return vote_counts.most_common(1)[0][0]


# 편의 함수들
def create_trade_result(
    pnl: float,
    win: Optional[bool] = None,
    **kwargs
) -> TradeResult:
    """TradeResult 편의 생성"""
    if win is None:
        win = pnl > 0

    return TradeResult(pnl=pnl, win=win, **kwargs)


def create_signal_result(
    signal: str,
    confidence: float,
    **kwargs
) -> SignalResult:
    """SignalResult 편의 생성"""
    return SignalResult(signal=signal, confidence=confidence, **kwargs)

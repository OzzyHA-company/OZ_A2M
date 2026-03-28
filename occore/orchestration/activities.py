"""
Temporal Activities

워크플로우 활동 구현
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from temporalio import activity

from lib.core.tracer import get_tracer
from lib.messaging.event_bus import get_event_bus

logger = logging.getLogger(__name__)
tracer = get_tracer("oz_a2m_orchestration")

# Activity Context
activity_info = activity.info


class ActivityInput:
    """활동 입력 데이터"""
    def __init__(self, data: Dict[str, Any]):
        self.data = data

    def to_dict(self) -> Dict[str, Any]:
        return self.data


class MarketDataInput:
    """시장 데이터 수집 입력"""
    def __init__(self, symbol: str, timeframe: str, exchange: str = "binance"):
        self.symbol = symbol
        self.timeframe = timeframe
        self.exchange = exchange

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "exchange": self.exchange,
        }


class SignalInput:
    """신호 생성 입력"""
    def __init__(self, symbol: str, price: float, indicators: Dict[str, Any]):
        self.symbol = symbol
        self.price = price
        self.indicators = indicators

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "indicators": self.indicators,
        }


class BotCommandInput:
    """봇 명령 입력"""
    def __init__(
        self,
        bot_id: str,
        command: str,
        params: Optional[Dict[str, Any]] = None
    ):
        self.bot_id = bot_id
        self.command = command
        self.params = params or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bot_id": self.bot_id,
            "command": self.command,
            "params": self.params,
        }


class ExecutionResultInput:
    """실행 결과 저장 입력"""
    def __init__(
        self,
        bot_id: str,
        signal_id: str,
        result: Dict[str, Any],
        success: bool = True
    ):
        self.bot_id = bot_id
        self.signal_id = signal_id
        self.result = result
        self.success = success

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bot_id": self.bot_id,
            "signal_id": self.signal_id,
            "result": self.result,
            "success": self.success,
            "timestamp": datetime.utcnow().isoformat(),
        }


@activity.defn
async def collect_market_data(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    시장 데이터 수집 활동

    Args:
        input_data: MarketDataInput.to_dict() 형태

    Returns:
        수집된 시장 데이터
    """
    with tracer.span("activity.collect_market_data", input_data):
        logger.info(f"Collecting market data: {input_data}")

        symbol = input_data.get("symbol", "BTC/USDT")
        timeframe = input_data.get("timeframe", "1m")
        exchange = input_data.get("exchange", "binance")

        # 실제 구현에서는 CCXT나 거래소 API 호출
        # 현재는 Mock 데이터 반환
        mock_data = {
            "symbol": symbol,
            "timeframe": timeframe,
            "exchange": exchange,
            "ohlcv": {
                "open": 50000.0,
                "high": 51000.0,
                "low": 49500.0,
                "close": 50500.0,
                "volume": 100.5,
            },
            "timestamp": datetime.utcnow().isoformat(),
            "indicators": {
                "ema_20": 50200.0,
                "ema_50": 49800.0,
                "rsi": 55.0,
                "macd": 0.5,
                "macd_signal": 0.3,
            }
        }

        logger.info(f"Market data collected: {symbol}")
        return mock_data


@activity.defn
async def generate_trading_signal(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    트레이딩 신호 생성 활동

    Args:
        input_data: SignalInput.to_dict() 형태 + market_data

    Returns:
        생성된 트레이딩 신호
    """
    with tracer.span("activity.generate_trading_signal", input_data):
        logger.info(f"Generating trading signal: {input_data}")

        symbol = input_data.get("symbol", "BTC/USDT")
        price = input_data.get("price", 0.0)
        indicators = input_data.get("indicators", {})

        # EMA 크로스오버 전략 (Trend Following)
        ema_fast = indicators.get("ema_20", 0)
        ema_slow = indicators.get("ema_50", 0)
        macd = indicators.get("macd", 0)

        signal = {
            "signal_id": f"sig_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            "symbol": symbol,
            "timestamp": datetime.utcnow().isoformat(),
            "action": "HOLD",
            "confidence": 0.0,
            "reason": "",
            "price": price,
        }

        # 매수 신호: Fast EMA > Slow EMA 그리고 MACD > 0
        if ema_fast > ema_slow and macd > 0:
            signal["action"] = "BUY"
            signal["confidence"] = min(0.95, 0.5 + abs(macd))
            signal["reason"] = f"EMA crossover: {ema_fast:.2f} > {ema_slow:.2f}, MACD: {macd:.4f}"

        # 매도 신호: Fast EMA < Slow EMA 그리고 MACD < 0
        elif ema_fast < ema_slow and macd < 0:
            signal["action"] = "SELL"
            signal["confidence"] = min(0.95, 0.5 + abs(macd))
            signal["reason"] = f"EMA crossunder: {ema_fast:.2f} < {ema_slow:.2f}, MACD: {macd:.4f}"

        else:
            signal["reason"] = f"No clear trend: EMA diff={ema_fast-ema_slow:.2f}, MACD={macd:.4f}"

        logger.info(f"Signal generated: {signal['action']} ({signal['confidence']:.2%})")
        return signal


@activity.defn
async def execute_bot_command(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    봇 명령 실행 활동

    Args:
        input_data: BotCommandInput.to_dict() 형태

    Returns:
        명령 실행 결과
    """
    with tracer.span("activity.execute_bot_command", input_data):
        logger.info(f"Executing bot command: {input_data}")

        bot_id = input_data.get("bot_id", "unknown")
        command = input_data.get("command", "")
        params = input_data.get("params", {})

        # MQTT로 명령 발행
        event_bus = get_event_bus(enable_kafka=False)
        topic = f"oz/a2m/command/{bot_id}"

        command_payload = {
            "bot_id": bot_id,
            "command": command,
            "params": params,
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            # 비동기로 MQTT 발행
            await event_bus.publish_async(topic, command_payload)

            result = {
                "bot_id": bot_id,
                "command": command,
                "status": "sent",
                "topic": topic,
                "timestamp": datetime.utcnow().isoformat(),
            }
            logger.info(f"Command sent to {bot_id}: {command}")
            return result

        except Exception as e:
            logger.error(f"Failed to send command: {e}")
            return {
                "bot_id": bot_id,
                "command": command,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }


@activity.defn
async def save_execution_result(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    실행 결과 저장 활동

    Args:
        input_data: ExecutionResultInput.to_dict() 형태

    Returns:
        저장 결과
    """
    with tracer.span("activity.save_execution_result", input_data):
        logger.info(f"Saving execution result: {input_data}")

        bot_id = input_data.get("bot_id", "unknown")
        signal_id = input_data.get("signal_id", "unknown")
        result = input_data.get("result", {})
        success = input_data.get("success", True)

        # 실행 결과를 이벤트 버스로 발행 (Kafka에 저장)
        event_bus = get_event_bus()

        result_payload = {
            "bot_id": bot_id,
            "signal_id": signal_id,
            "execution_result": result,
            "success": success,
            "saved_at": datetime.utcnow().isoformat(),
        }

        try:
            # Kafka로 결과 저장 (HIGH priority)
            await event_bus.publish_async(
                "oz.a2m.execution.results",
                result_payload,
                priority="HIGH"
            )

            save_result = {
                "signal_id": signal_id,
                "bot_id": bot_id,
                "status": "saved",
                "timestamp": datetime.utcnow().isoformat(),
            }
            logger.info(f"Execution result saved: {signal_id}")
            return save_result

        except Exception as e:
            logger.error(f"Failed to save result: {e}")
            return {
                "signal_id": signal_id,
                "bot_id": bot_id,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

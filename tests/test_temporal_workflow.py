"""
Temporal Workflow Tests

STEP 4: Temporal 워크플로우 오케스트레이션 테스트
"""

import pytest
import asyncio
from datetime import timedelta
from unittest.mock import Mock, patch, AsyncMock

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.client import Client

from occore.orchestration.workflows import (
    MarketDataPipelineWorkflow,
    BatchSignalProcessingWorkflow,
    ScheduledMonitoringWorkflow,
    MarketDataPipelineInput,
    MarketDataPipelineResult,
)
from occore.orchestration.activities import (
    collect_market_data,
    generate_trading_signal,
    execute_bot_command,
    save_execution_result,
)


# Global test environment fixture
@pytest.fixture(scope="module")
async def temporal_env():
    """Temporal 테스트 환경"""
    async with await WorkflowEnvironment.start_time_skipping() as e:
        yield e


class TestMarketDataPipelineWorkflow:
    """MarketDataPipelineWorkflow 테스트"""

    @pytest.mark.skip(reason="Temporal integration test requires running Temporal server")
    @pytest.mark.asyncio
    async def test_workflow_success_buy_signal(self, temporal_env):
        """매수 신호 생성 워크플로우 테스트"""
        # 이 테스트는 실제 Temporal 서버가 필요합니다
        pass

    @pytest.mark.skip(reason="Temporal integration test requires running Temporal server")
    @pytest.mark.asyncio
    async def test_workflow_hold_signal(self, temporal_env):
        """HOLD 신호 테스트 (실행 없음)"""
        pass

    @pytest.mark.skip(reason="Temporal integration test requires running Temporal server")
    @pytest.mark.asyncio
    async def test_workflow_sell_signal(self, temporal_env):
        """매도 신호 생성 워크플로우 테스트"""
        pass


class TestActivityFunctions:
    """Activity 함수 직접 테스트"""

    @pytest.mark.asyncio
    async def test_collect_market_data(self):
        """시장 데이터 수집 액티비티 테스트"""
        input_data = {
            "symbol": "BTC/USDT",
            "timeframe": "1m",
            "exchange": "binance",
        }

        result = await collect_market_data(input_data)

        assert result["symbol"] == "BTC/USDT"
        assert "ohlcv" in result
        assert "indicators" in result
        assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_generate_trading_signal_buy(self):
        """매수 신호 생성 액티비티 테스트"""
        input_data = {
            "symbol": "BTC/USDT",
            "price": 50500.0,
            "indicators": {
                "ema_20": 50200.0,
                "ema_50": 49800.0,
                "macd": 0.5,
            }
        }

        result = await generate_trading_signal(input_data)

        assert result["action"] == "BUY"
        assert result["confidence"] > 0.5
        assert "signal_id" in result
        assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_generate_trading_signal_sell(self):
        """매도 신호 생성 액티비티 테스트"""
        input_data = {
            "symbol": "BTC/USDT",
            "price": 49500.0,
            "indicators": {
                "ema_20": 49800.0,
                "ema_50": 50200.0,
                "macd": -0.5,
            }
        }

        result = await generate_trading_signal(input_data)

        assert result["action"] == "SELL"
        assert result["confidence"] > 0.5

    @pytest.mark.asyncio
    async def test_generate_trading_signal_hold(self):
        """HOLD 신호 생성 액티비티 테스트"""
        input_data = {
            "symbol": "BTC/USDT",
            "price": 50000.0,
            "indicators": {
                "ema_20": 49900.0,
                "ema_50": 49950.0,
                "macd": 0.0,
            }
        }

        result = await generate_trading_signal(input_data)

        assert result["action"] == "HOLD"

    @pytest.mark.asyncio
    async def test_execute_bot_command(self):
        """봇 명령 실행 액티비티 테스트"""
        input_data = {
            "bot_id": "test_bot",
            "command": "buy",
            "params": {"price": 50000.0},
        }

        with patch("occore.orchestration.activities.get_event_bus") as mock_get_bus:
            mock_bus = AsyncMock()
            mock_get_bus.return_value = mock_bus

            result = await execute_bot_command(input_data)

            assert result["bot_id"] == "test_bot"
            assert result["command"] == "buy"
            assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_save_execution_result(self):
        """실행 결과 저장 액티비티 테스트"""
        input_data = {
            "bot_id": "test_bot",
            "signal_id": "sig_001",
            "result": {"status": "success"},
            "success": True,
        }

        with patch("occore.orchestration.activities.get_event_bus") as mock_get_bus:
            mock_bus = AsyncMock()
            mock_get_bus.return_value = mock_bus

            result = await save_execution_result(input_data)

            assert result["signal_id"] == "sig_001"
            assert result["status"] == "saved"


class TestWorkflowInputOutput:
    """워크플로우 입출력 테스트"""

    def test_market_data_pipeline_input_defaults(self):
        """기본값이 있는 입력 테스트"""
        input_data = MarketDataPipelineInput()

        assert input_data.symbol == "BTC/USDT"
        assert input_data.timeframe == "1m"
        assert input_data.exchange == "binance"
        assert input_data.bot_id == "trend_follower_001"
        assert input_data.enable_execution is True

    def test_market_data_pipeline_input_custom(self):
        """커스텀 입력 테스트"""
        input_data = MarketDataPipelineInput(
            symbol="ETH/USDT",
            timeframe="5m",
            exchange="bybit",
            bot_id="scalping_bot_001",
            enable_execution=False,
        )

        assert input_data.symbol == "ETH/USDT"
        assert input_data.timeframe == "5m"
        assert input_data.exchange == "bybit"
        assert input_data.bot_id == "scalping_bot_001"
        assert input_data.enable_execution is False

    def test_market_data_pipeline_result_success(self):
        """성공 결과 테스트"""
        result = MarketDataPipelineResult(
            success=True,
            signal={"action": "BUY", "confidence": 0.9},
            execution_result={"status": "sent"},
            duration_seconds=1.5,
        )

        assert result.success is True
        assert result.error_message is None

    def test_market_data_pipeline_result_failure(self):
        """실패 결과 테스트"""
        result = MarketDataPipelineResult(
            success=False,
            signal=None,
            execution_result=None,
            duration_seconds=0.5,
            error_message="Connection failed",
        )

        assert result.success is False
        assert result.error_message == "Connection failed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

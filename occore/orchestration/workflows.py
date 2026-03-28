"""
Temporal Workflows

OZ_A2M 워크플로우 정의
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from .activities import (
        collect_market_data,
        generate_trading_signal,
        execute_bot_command,
        save_execution_result,
    )
    from lib.core.tracer import get_tracer


@dataclass
class MarketDataPipelineInput:
    """Market Data Pipeline 워크플로우 입력"""
    symbol: str = "BTC/USDT"
    timeframe: str = "1m"
    exchange: str = "binance"
    bot_id: str = "trend_follower_001"
    enable_execution: bool = True


@dataclass
class MarketDataPipelineResult:
    """Market Data Pipeline 워크플로우 결과"""
    success: bool
    signal: Optional[Dict[str, Any]]
    execution_result: Optional[Dict[str, Any]]
    duration_seconds: float
    error_message: Optional[str] = None


@workflow.defn
class MarketDataPipelineWorkflow:
    """
    시장 데이터 파이프라인 워크플로우

    Pipeline:
        1. 시장 데이터 수집 (collect_market_data)
        2. 트레이딩 신호 생성 (generate_trading_signal)
        3. 봇 명령 실행 (execute_bot_command) - 선택적
        4. 결과 저장 (save_execution_result)
    """

    def __init__(self):
        self._progress: Dict[str, Any] = {}
        self._current_step: str = "initialized"

    @workflow.run
    async def run(
        self,
        input_data: MarketDataPipelineInput
    ) -> MarketDataPipelineResult:
        """
        워크플로우 실행

        Args:
            input_data: 파이프라인 입력 파라미터

        Returns:
            MarketDataPipelineResult: 실행 결과
        """
        start_time = workflow.now()
        self._current_step = "started"

        try:
            # Step 1: 시장 데이터 수집
            self._current_step = "collecting_market_data"
            self._update_progress("step", "collect_market_data")

            market_data = await workflow.execute_activity(
                collect_market_data,
                {
                    "symbol": input_data.symbol,
                    "timeframe": input_data.timeframe,
                    "exchange": input_data.exchange,
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=10),
                    maximum_attempts=3,
                ),
            )

            # Step 2: 트레이딩 신호 생성
            self._current_step = "generating_signal"
            self._update_progress("step", "generate_trading_signal")

            ohlcv = market_data.get("ohlcv", {})
            indicators = market_data.get("indicators", {})

            signal = await workflow.execute_activity(
                generate_trading_signal,
                {
                    "symbol": input_data.symbol,
                    "price": ohlcv.get("close", 0),
                    "indicators": indicators,
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=5),
                    maximum_attempts=3,
                ),
            )

            # Step 3 & 4: 실행 및 저장 (HOLD가 아닌 경우)
            execution_result = None
            save_result = None

            if signal.get("action") != "HOLD" and input_data.enable_execution:
                self._current_step = "executing_command"
                self._update_progress("step", "execute_bot_command")

                execution_result = await workflow.execute_activity(
                    execute_bot_command,
                    {
                        "bot_id": input_data.bot_id,
                        "command": signal.get("action", "HOLD").lower(),
                        "params": {
                            "symbol": input_data.symbol,
                            "price": ohlcv.get("close"),
                            "confidence": signal.get("confidence"),
                            "reason": signal.get("reason"),
                        },
                    },
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=1),
                        maximum_interval=timedelta(seconds=5),
                        maximum_attempts=2,
                    ),
                )

                # Step 4: 결과 저장
                self._current_step = "saving_result"
                self._update_progress("step", "save_execution_result")

                save_result = await workflow.execute_activity(
                    save_execution_result,
                    {
                        "bot_id": input_data.bot_id,
                        "signal_id": signal.get("signal_id"),
                        "result": execution_result,
                        "success": execution_result.get("status") == "sent",
                    },
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=1),
                        maximum_interval=timedelta(seconds=5),
                        maximum_attempts=3,
                    ),
                )

            # 완료
            duration = (workflow.now() - start_time).total_seconds()
            self._current_step = "completed"
            self._update_progress("status", "completed")

            return MarketDataPipelineResult(
                success=True,
                signal=signal,
                execution_result=execution_result,
                duration_seconds=duration,
            )

        except Exception as e:
            duration = (workflow.now() - start_time).total_seconds()
            self._current_step = "failed"
            self._update_progress("status", "failed")
            self._update_progress("error", str(e))

            return MarketDataPipelineResult(
                success=False,
                signal=None,
                execution_result=None,
                duration_seconds=duration,
                error_message=str(e),
            )

    @workflow.query
    def get_progress(self) -> Dict[str, Any]:
        """현재 진행 상황 조회"""
        return {
            "current_step": self._current_step,
            "progress": self._progress,
            "timestamp": workflow.now().isoformat(),
        }

    def _update_progress(self, key: str, value: Any):
        """진행 상황 업데이트"""
        self._progress[key] = value
        self._progress["updated_at"] = workflow.now().isoformat()


@workflow.defn
class BatchSignalProcessingWorkflow:
    """
    배치 신호 처리 워크플로우

    여러 심볼에 대해 신호를 병렬로 생성하고 처리
    """

    @workflow.run
    async def run(
        self,
        symbols: List[str],
        timeframe: str = "1m",
        bot_id_prefix: str = "trend_follower"
    ) -> List[MarketDataPipelineResult]:
        """
        배치 신호 처리 실행

        Args:
            symbols: 처리할 심볼 목록
            timeframe: 시간 프레임
            bot_id_prefix: 봇 ID 접두사

        Returns:
            각 심볼별 처리 결과 목록
        """
        results = []

        # 각 심볼별로 MarketDataPipelineWorkflow 실행
        tasks = []
        for i, symbol in enumerate(symbols):
            input_data = MarketDataPipelineInput(
                symbol=symbol,
                timeframe=timeframe,
                bot_id=f"{bot_id_prefix}_{i+1:03d}",
            )

            # 자식 워크플로우 실행
            handle = await workflow.execute_child_workflow(
                MarketDataPipelineWorkflow.run,
                input_data,
                id=f"market-pipeline-{symbol.replace('/', '-')}-{workflow.now().strftime('%Y%m%d-%H%M%S')}",
            )
            tasks.append(handle)

        # 모든 결과 수집
        for i, task in enumerate(tasks):
            try:
                result = await task
                results.append(result)
            except Exception as e:
                results.append(MarketDataPipelineResult(
                    success=False,
                    signal=None,
                    execution_result=None,
                    duration_seconds=0,
                    error_message=str(e),
                ))

        return results


@workflow.defn
class ScheduledMonitoringWorkflow:
    """
    예약된 모니터링 워크플로우

    주기적으로 실행되는 모니터링 작업
    """

    @workflow.run
    async def run(
        self,
        check_interval_minutes: int = 5,
        duration_hours: int = 24,
    ) -> Dict[str, Any]:
        """
        예약된 모니터링 실행

        Args:
            check_interval_minutes: 체크 간격 (분)
            duration_hours: 총 실행 시간 (시간)

        Returns:
            모니터링 결과 요약
        """
        start_time = workflow.now()
        end_time = start_time + timedelta(hours=duration_hours)

        execution_count = 0
        errors = []

        while workflow.now() < end_time:
            execution_count += 1

            try:
                # 시장 데이터 파이프라인 실행
                input_data = MarketDataPipelineInput(
                    symbol="BTC/USDT",
                    timeframe="5m",
                    enable_execution=True,
                )

                result = await workflow.execute_child_workflow(
                    MarketDataPipelineWorkflow.run,
                    input_data,
                    id=f"scheduled-pipeline-{execution_count}-{workflow.now().strftime('%Y%m%d-%H%M%S')}",
                )

                if not result.success:
                    errors.append({
                        "execution": execution_count,
                        "error": result.error_message,
                        "time": workflow.now().isoformat(),
                    })

            except Exception as e:
                errors.append({
                    "execution": execution_count,
                    "error": str(e),
                    "time": workflow.now().isoformat(),
                })

            # 다음 실행까지 대기
            await workflow.sleep(timedelta(minutes=check_interval_minutes))

        total_duration = (workflow.now() - start_time).total_seconds()

        return {
            "total_executions": execution_count,
            "successful": execution_count - len(errors),
            "failed": len(errors),
            "duration_seconds": total_duration,
            "errors": errors[:10],  # 최대 10개까지만
        }

#!/usr/bin/env python3
"""
Temporal Worker 실행 스크립트

OZ_A2M Temporal Worker
"""

import asyncio
import logging
import os
import sys
from typing import List

import structlog
from temporalio.client import Client
from temporalio.worker import Worker

# 프로젝트 루트 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from occore.orchestration.workflows import (
    MarketDataPipelineWorkflow,
    BatchSignalProcessingWorkflow,
    ScheduledMonitoringWorkflow,
)
from occore.orchestration.activities import (
    collect_market_data,
    generate_trading_signal,
    execute_bot_command,
    save_execution_result,
)
from lib.core.tracer import get_tracer

# 로깅 설정
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# 설정
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost")
TEMPORAL_PORT = int(os.getenv("TEMPORAL_PORT", "7233"))
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
WORKER_TASK_QUEUE = os.getenv("WORKER_TASK_QUEUE", "oz-a2m-queue")

# OpenTelemetry Tracer
tracer = get_tracer("oz_a2m_worker")


async def create_temporal_client() -> Client:
    """Temporal 클라이언트 생성"""
    temporal_address = f"{TEMPORAL_HOST}:{TEMPORAL_PORT}"
    logger.info(f"Connecting to Temporal at {temporal_address}")

    try:
        client = await Client.connect(
            temporal_address,
            namespace=TEMPORAL_NAMESPACE,
        )
        logger.info("Temporal client connected successfully")
        return client
    except Exception as e:
        logger.error(f"Failed to connect to Temporal: {e}")
        raise


async def run_worker():
    """Temporal Worker 실행"""
    with tracer.span("worker.start"):
        logger.info("Starting OZ_A2M Temporal Worker")
        logger.info(f"Task Queue: {WORKER_TASK_QUEUE}")
        logger.info(f"Namespace: {TEMPORAL_NAMESPACE}")

        # 클라이언트 연결
        client = await create_temporal_client()

        # 워커 생성
        worker = Worker(
            client,
            task_queue=WORKER_TASK_QUEUE,
            workflows=[
                MarketDataPipelineWorkflow,
                BatchSignalProcessingWorkflow,
                ScheduledMonitoringWorkflow,
            ],
            activities=[
                collect_market_data,
                generate_trading_signal,
                execute_bot_command,
                save_execution_result,
            ],
            # 워커 설정
            max_concurrent_activities=10,
            max_concurrent_workflow_tasks=5,
        )

        logger.info("Worker initialized, starting...")

        try:
            # 워커 실행
            await worker.run()
        except asyncio.CancelledError:
            logger.info("Worker cancelled")
        except Exception as e:
            logger.error(f"Worker error: {e}")
            raise
        finally:
            logger.info("Worker stopped")


async def start_workflow_example():
    """워크플로우 시작 예제"""
    client = await create_temporal_client()

    from occore.orchestration.workflows import MarketDataPipelineInput

    input_data = MarketDataPipelineInput(
        symbol="BTC/USDT",
        timeframe="1m",
        bot_id="trend_follower_001",
        enable_execution=True,
    )

    result = await client.execute_workflow(
        MarketDataPipelineWorkflow.run,
        input_data,
        id="market-pipeline-example",
        task_queue=WORKER_TASK_QUEUE,
    )

    logger.info(f"Workflow result: {result}")
    return result


async def list_workflows():
    """실행 중인 워크플로우 목록 조회"""
    client = await create_temporal_client()

    # 워크플로우 목록 조회 (간단한 예제)
    # 실제로는 ListWorkflowExecutions API 사용
    logger.info("Workflow listing not implemented in this example")
    return []


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OZ_A2M Temporal Worker")
    parser.add_argument(
        "command",
        choices=["worker", "start", "list"],
        default="worker",
        nargs="?",
        help="Command to execute: worker (run worker), start (start example workflow), list (list workflows)"
    )

    args = parser.parse_args()

    if args.command == "worker":
        # 워커 실행
        try:
            asyncio.run(run_worker())
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
    elif args.command == "start":
        # 예제 워크플로우 시작
        asyncio.run(start_workflow_example())
    elif args.command == "list":
        # 워크플로우 목록 조회
        asyncio.run(list_workflows())

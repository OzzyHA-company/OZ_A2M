#!/usr/bin/env python3
"""
Ray RLlib 강화학습 엔진

백테스트 병렬화 및 최적 파라미터 자동 탐색
- Ray RLlib 기반 전략 최적화
- GPU 활용 병렬 백테스트
- 분산 학습 지원
"""

import os
import json
import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import ray
from ray import tune
from ray.rllib.algorithms.ppo import PPOConfig
from ray.rllib.env.env_context import EnvContext

from lib.core.logger import get_logger
from lib.core.tracer import get_tracer, trace_function

logger = get_logger(__name__)
tracer = get_tracer("ray_engine")


@dataclass
class BacktestConfig:
    """백테스트 설정"""
    strategy_name: str
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    start_date: str = "2024-01-01"
    end_date: str = "2024-12-31"
    initial_capital: float = 10000.0
    params: Dict[str, Any] = None

    def __post_init__(self):
        if self.params is None:
            self.params = {}


@dataclass
class BacktestResult:
    """백테스트 결과"""
    config: BacktestConfig
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    trades_count: int
    profit_factor: float
    duration_seconds: float
    timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.config.strategy_name,
            "symbol": self.config.symbol,
            "total_return": self.total_return,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "trades_count": self.trades_count,
            "profit_factor": self.profit_factor,
            "duration": self.duration_seconds,
            "timestamp": self.timestamp.isoformat(),
        }


@ray.remote
class BacktestWorker:
    """백테스트 워커 (Ray Actor)"""

    def __init__(self, worker_id: int):
        self.worker_id = worker_id
        self.logger = get_logger(f"backtest_worker_{worker_id}")
        self.logger.info(f"BacktestWorker {worker_id} initialized")

    def run_backtest(self, config: BacktestConfig) -> BacktestResult:
        """백테스트 실행"""
        import random
        import time

        start_time = time.time()

        # 모의 백테스트 결과 (실제 구현에서는 전략 로직 실행)
        # 파라미터에 따라 결과 변화 시뮬레이션
        params = config.params

        # 기본 지표 (랜덤 + 파라미터 영향)
        base_return = random.uniform(-20, 40)
        param_bonus = sum(params.values()) * 0.1 if params else 0

        total_return = base_return + param_bonus
        sharpe_ratio = random.uniform(0.5, 2.0) + (param_bonus / 100)
        max_drawdown = random.uniform(5, 25)
        win_rate = random.uniform(40, 65)
        trades_count = random.randint(50, 500)
        profit_factor = random.uniform(1.0, 2.5)

        duration = time.time() - start_time

        return BacktestResult(
            config=config,
            total_return=total_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            trades_count=trades_count,
            profit_factor=profit_factor,
            duration_seconds=duration,
            timestamp=datetime.utcnow(),
        )


class RayEngine:
    """
    Ray RLlib 강화학습 엔진

    기능:
    1. 병렬 백테스트 실행
    2. 파라미터 최적화 (Grid Search, Random Search)
    3. 분산 학습 관리
    4. GPU 리소스 활용
    """

    def __init__(
        self,
        num_workers: int = 4,
        use_gpu: bool = False,
        head_address: Optional[str] = None,
    ):
        self.num_workers = num_workers
        self.use_gpu = use_gpu
        self.head_address = head_address
        self.initialized = False
        self.workers: List[ray.actor.ActorHandle] = []

        self.logger = get_logger(__name__)
        self.logger.info(f"RayEngine initialized (workers={num_workers}, gpu={use_gpu})")

    @trace_function("ray_init")
    def initialize(self) -> bool:
        """Ray 클러스터 초기화"""
        if self.initialized:
            return True

        try:
            if self.head_address:
                # 기존 클러스터 연결
                ray.init(address=self.head_address)
                self.logger.info(f"Connected to Ray cluster: {self.head_address}")
            else:
                # 로컬 모드 시작
                resources = {}
                if self.use_gpu:
                    resources["num_gpus"] = 1

                ray.init(
                    ignore_reinit_error=True,
                    include_dashboard=False,
                    **resources
                )
                self.logger.info("Ray initialized in local mode")

            # 워커 생성
            self.workers = [
                BacktestWorker.remote(i)
                for i in range(self.num_workers)
            ]

            self.initialized = True
            return True

        except Exception as e:
            self.logger.error(f"Ray initialization failed: {e}")
            return False

    def shutdown(self):
        """Ray 클러스터 종료"""
        if self.initialized:
            ray.shutdown()
            self.initialized = False
            self.workers = []
            self.logger.info("Ray shutdown complete")

    @trace_function("ray_parallel_backtest")
    def run_parallel_backtests(
        self,
        configs: List[BacktestConfig],
    ) -> List[BacktestResult]:
        """
        병렬 백테스트 실행

        Args:
            configs: 백테스트 설정 목록

        Returns:
            백테스트 결과 목록
        """
        if not self.initialized:
            self.initialize()

        # 워커에 작업 분배
        futures = []
        for i, config in enumerate(configs):
            worker = self.workers[i % len(self.workers)]
            future = worker.run_backtest.remote(config)
            futures.append(future)

        # 결과 수집
        results = ray.get(futures)
        self.logger.info(f"Completed {len(results)} parallel backtests")

        return results

    @trace_function("ray_optimize")
    def optimize_parameters(
        self,
        strategy_name: str,
        param_space: Dict[str, Any],
        num_samples: int = 20,
        metric: str = "sharpe_ratio",
        mode: str = "max",
    ) -> Dict[str, Any]:
        """
        파라미터 최적화 (Ray Tune 사용)

        Args:
            strategy_name: 전략 이름
            param_space: 파라미터 탐색 공간
            num_samples: 샘플링 횟수
            metric: 최적화 지표
            mode: "max" 또는 "min"

        Returns:
            최적 파라미터 조합
        """
        if not self.initialized:
            self.initialize()

        def objective(config):
            """최적화 목표 함수"""
            backtest_config = BacktestConfig(
                strategy_name=strategy_name,
                params=config,
            )

            # 단일 백테스트 실행
            worker = BacktestWorker.remote(0)
            result = ray.get(worker.run_backtest.remote(backtest_config))

            return {
                "sharpe_ratio": result.sharpe_ratio,
                "total_return": result.total_return,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
            }

        # Ray Tune 실행
        analysis = tune.run(
            objective,
            config=param_space,
            num_samples=num_samples,
            metric=metric,
            mode=mode,
            verbose=1,
            local_dir="/tmp/ray_results",
        )

        best_config = analysis.best_config
        best_metrics = analysis.best_result

        self.logger.info(f"Optimization complete. Best {metric}: {best_metrics[metric]:.2f}")

        return {
            "best_params": best_config,
            "best_metrics": best_metrics,
            "total_trials": len(analysis.trials),
        }

    def grid_search(
        self,
        strategy_name: str,
        param_grid: Dict[str, List[Any]],
    ) -> List[BacktestResult]:
        """
        그리드 서치 실행

        Args:
            strategy_name: 전략 이름
            param_grid: 파라미터 그리드

        Returns:
            모든 조합의 백테스트 결과
        """
        # 그리드 생성
        import itertools

        keys = list(param_grid.keys())
        values = list(param_grid.values())

        configs = []
        for combination in itertools.product(*values):
            params = dict(zip(keys, combination))
            configs.append(BacktestConfig(
                strategy_name=strategy_name,
                params=params,
            ))

        self.logger.info(f"Grid search: {len(configs)} combinations")

        return self.run_parallel_backtests(configs)

    def get_cluster_info(self) -> Dict[str, Any]:
        """클러스터 정보 조회"""
        if not self.initialized:
            return {"status": "not_initialized"}

        resources = ray.cluster_resources()
        available = ray.available_resources()

        return {
            "status": "initialized",
            "total_workers": len(self.workers),
            "cluster_resources": resources,
            "available_resources": available,
            "gpu_enabled": self.use_gpu,
        }


class StrategyOptimizer:
    """전략 최적화 도구"""

    def __init__(self, engine: RayEngine):
        self.engine = engine
        self.logger = get_logger(__name__)

    def find_optimal_params(
        self,
        strategy_name: str,
        param_ranges: Dict[str, tuple],  # (min, max, step)
        top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        최적 파라미터 탐색

        Args:
            strategy_name: 전략 이름
            param_ranges: 파라미터 범위
            top_n: 반환할 상위 결과 수

        Returns:
            상위 N개 결과
        """
        # 그리드 생성
        import numpy as np

        param_grid = {}
        for key, (min_val, max_val, step) in param_ranges.items():
            if isinstance(min_val, int):
                param_grid[key] = list(range(min_val, max_val + 1, step))
            else:
                param_grid[key] = np.arange(min_val, max_val, step).tolist()

        # 병렬 실행
        results = self.engine.grid_search(strategy_name, param_grid)

        # Sharpe ratio 기준 정렬
        sorted_results = sorted(
            results,
            key=lambda x: x.sharpe_ratio,
            reverse=True
        )

        return [
            {
                "params": r.config.params,
                "sharpe_ratio": r.sharpe_ratio,
                "total_return": r.total_return,
                "max_drawdown": r.max_drawdown,
                "win_rate": r.win_rate,
            }
            for r in sorted_results[:top_n]
        ]


def main():
    """메인 실행 예제"""
    # Ray 엔진 초기화
    engine = RayEngine(num_workers=4, use_gpu=False)

    if not engine.initialize():
        print("Failed to initialize Ray")
        return

    try:
        # 샘플 백테스트
        configs = [
            BacktestConfig(
                strategy_name="trend_following",
                symbol="BTC/USDT",
                params={"ema_fast": 10, "ema_slow": 50},
            ),
            BacktestConfig(
                strategy_name="trend_following",
                symbol="ETH/USDT",
                params={"ema_fast": 20, "ema_slow": 100},
            ),
        ]

        results = engine.run_parallel_backtests(configs)

        for r in results:
            print(f"\n{r.config.symbol}: Return={r.total_return:.2f}%, Sharpe={r.sharpe_ratio:.2f}")

        # 최적화 예제
        param_space = {
            "ema_fast": tune.choice([5, 10, 15, 20]),
            "ema_slow": tune.choice([30, 50, 100]),
            "rsi_period": tune.choice([7, 14, 21]),
        }

        optimization_result = engine.optimize_parameters(
            strategy_name="trend_following",
            param_space=param_space,
            num_samples=10,
        )

        print(f"\nBest params: {optimization_result['best_params']}")

    finally:
        engine.shutdown()


if __name__ == "__main__":
    main()

"""
Ray RLlib Engine Tests

STEP 8: Ray 강화학습 엔진 테스트
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock

from occore.research.ray_engine import (
    RayEngine,
    BacktestConfig,
    BacktestResult,
    StrategyOptimizer,
)


class TestBacktestConfig:
    """BacktestConfig 테스트"""

    def test_config_creation(self):
        """설정 생성 테스트"""
        config = BacktestConfig(
            strategy_name="trend_following",
            symbol="BTC/USDT",
            timeframe="1h",
            params={"ema_fast": 10, "ema_slow": 50},
        )

        assert config.strategy_name == "trend_following"
        assert config.symbol == "BTC/USDT"
        assert config.params["ema_fast"] == 10


class TestRayEngine:
    """RayEngine 테스트"""

    @pytest.fixture
    def engine(self):
        """테스트용 엔진"""
        return RayEngine(num_workers=2, use_gpu=False)

    def test_engine_initialization(self, engine):
        """엔진 초기화 테스트"""
        assert engine.num_workers == 2
        assert engine.use_gpu is False
        assert engine.initialized is False

    def test_cluster_info_not_initialized(self, engine):
        """초기화되지 않은 상태 테스트"""
        info = engine.get_cluster_info()
        assert info["status"] == "not_initialized"


class TestStrategyOptimizer:
    """StrategyOptimizer 테스트"""

    @pytest.fixture
    def optimizer(self):
        """테스트용 옵티마이저"""
        engine = RayEngine(num_workers=2, use_gpu=False)
        return StrategyOptimizer(engine)

    def test_optimizer_creation(self, optimizer):
        """옵티마이저 생성 테스트"""
        assert optimizer.engine is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

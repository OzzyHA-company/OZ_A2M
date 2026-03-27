"""
OZ_A2M 제6부서: 연구개발팀 - 자동 전략 생성기

성과 데이터 기반 신규 전략 자동 생성 및 최적화
"""

import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
import json
import random

logger = logging.getLogger(__name__)


@dataclass
class StrategyTemplate:
    """전략 템플릿"""
    name: str
    description: str
    entry_conditions: List[str]
    exit_conditions: List[str]
    risk_management: Dict[str, float]
    parameters: Dict[str, Any]
    performance_threshold: float


@dataclass
class GeneratedStrategy:
    """생성된 전략"""
    id: str
    name: str
    template: str
    parameters: Dict[str, Any]
    created_at: datetime
    backtest_result: Optional[Dict]
    status: str  # pending/tested/deployed/rejected
    score: float  # 종합 점수


class StrategyGenerator:
    """
    자동 전략 생성기

    기능:
    - 템플릿 기반 전략 생성
    - 유전 알고리즘 최적화
    - 성과 기반 전략 선택
    - 자동 백테스트 및 검증
    """

    # 기본 전략 템플릿
    DEFAULT_TEMPLATES = [
        StrategyTemplate(
            name="momentum_breakout",
            description="가격 돌파 + 거래량 급증 기반 모멘텀 전략",
            entry_conditions=[
                "close > high.rolling(20).shift(1)",
                "volume > volume.rolling(20).mean() * 1.5"
            ],
            exit_conditions=[
                "close < low.rolling(10).shift(1)",
                "profit >= take_profit",
                "loss <= stop_loss"
            ],
            risk_management={
                "stop_loss": 0.02,
                "take_profit": 0.06,
                "position_size": 0.1
            },
            parameters={
                "lookback": [10, 20, 30],
                "volume_threshold": [1.2, 1.5, 2.0],
                "stop_loss": [0.01, 0.02, 0.03],
                "take_profit": [0.03, 0.06, 0.09]
            },
            performance_threshold=1.5
        ),
        StrategyTemplate(
            name="mean_reversion",
            description="RSI 과매수/과매도 기반 평균회귀 전략",
            entry_conditions=[
                "rsi(14) < 30",
                "close < bb_lower(20, 2)"
            ],
            exit_conditions=[
                "rsi(14) > 70",
                "close > bb_upper(20, 2)",
                "holding_days >= max_hold"
            ],
            risk_management={
                "stop_loss": 0.03,
                "take_profit": 0.05,
                "position_size": 0.08
            },
            parameters={
                "rsi_period": [10, 14, 21],
                "rsi_oversold": [20, 30, 40],
                "rsi_overbought": [60, 70, 80],
                "bb_period": [15, 20, 25],
                "max_hold": [3, 5, 10]
            },
            performance_threshold=1.3
        ),
        StrategyTemplate(
            name="trend_following",
            description="이동평균 크로스오버 추세추종 전략",
            entry_conditions=[
                "sma(10) > sma(30)",
                "sma(10).diff() > 0",
                "adx(14) > 25"
            ],
            exit_conditions=[
                "sma(10) < sma(30)",
                "adx(14) < 20"
            ],
            risk_management={
                "stop_loss": 0.04,
                "take_profit": 0.08,
                "trailing_stop": 0.03,
                "position_size": 0.12
            },
            parameters={
                "fast_ma": [5, 10, 15],
                "slow_ma": [20, 30, 50],
                "adx_period": [10, 14, 20],
                "adx_threshold": [20, 25, 30]
            },
            performance_threshold=1.4
        ),
        StrategyTemplate(
            name="volatility_breakout",
            description="ATR 기반 변동성 돌파 전략",
            entry_conditions=[
                "close > high(1) + atr(14) * multiplier",
                "atr(14) > atr(14).rolling(20).mean()"
            ],
            exit_conditions=[
                "close < low(1) - atr(14) * multiplier",
                "profit >= take_profit * 2"
            ],
            risk_management={
                "stop_loss": 0.025,
                "take_profit": 0.05,
                "position_size": 0.1
            },
            parameters={
                "atr_period": [10, 14, 20],
                "multiplier": [1.0, 1.5, 2.0, 2.5],
                "atr_threshold": [1.0, 1.2, 1.5]
            },
            performance_threshold=1.35
        ),
        StrategyTemplate(
            name="sentiment_momentum",
            description="감성 분석 + 모멘텀 결합 전략",
            entry_conditions=[
                "sentiment_score > 0.3",
                "sentiment_momentum > 0",
                "close > close.shift(5) * 1.02"
            ],
            exit_conditions=[
                "sentiment_score < -0.2",
                "sentiment_momentum < 0",
                "profit >= take_profit"
            ],
            risk_management={
                "stop_loss": 0.03,
                "take_profit": 0.06,
                "position_size": 0.1
            },
            parameters={
                "sentiment_threshold": [0.2, 0.3, 0.4],
                "momentum_lookback": [3, 5, 10],
                "sentiment_window": [3, 5, 7]
            },
            performance_threshold=1.6
        )
    ]

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.templates = self.config.get('templates', self.DEFAULT_TEMPLATES)
        self._generated_strategies: List[GeneratedStrategy] = []
        self._strategy_counter = 0

        # 백테스트 엔진
        self._backtest_engine = None
        self._init_backtest_engine()

    def _init_backtest_engine(self):
        """백테스트 엔진 초기화"""
        try:
            from .backtest_engine import get_backtest_engine
            self._backtest_engine = get_backtest_engine()
        except Exception as e:
            logger.warning(f"Backtest engine not initialized: {e}")

    def generate_strategy(self, template: Optional[StrategyTemplate] = None,
                         random_params: bool = True) -> GeneratedStrategy:
        """
        새로운 전략 생성

        Args:
            template: 사용할 템플릿 (None이면 랜덤 선택)
            random_params: 랜덤 파라미터 생성 여부
        """
        # 템플릿 선택
        if template is None:
            template = random.choice(self.templates)

        self._strategy_counter += 1
        strategy_id = f"STRAT-{datetime.now().strftime('%Y%m%d')}-{self._strategy_counter:04d}"

        # 파라미터 생성
        if random_params:
            params = self._generate_random_params(template.parameters)
        else:
            params = {k: v[0] if isinstance(v, list) else v
                     for k, v in template.parameters.items()}

        strategy = GeneratedStrategy(
            id=strategy_id,
            name=f"{template.name}_{self._strategy_counter}",
            template=template.name,
            parameters=params,
            created_at=datetime.now(),
            backtest_result=None,
            status="pending",
            score=0.0
        )

        self._generated_strategies.append(strategy)
        logger.info(f"Generated strategy: {strategy.name} ({strategy.id})")

        return strategy

    def _generate_random_params(self, param_ranges: Dict[str, List]) -> Dict[str, Any]:
        """랜덤 파라미터 생성"""
        params = {}
        for key, values in param_ranges.items():
            if isinstance(values, list):
                if all(isinstance(v, (int, float)) for v in values):
                    # 숫자 범위면 랜덤 선택
                    params[key] = random.choice(values)
                else:
                    params[key] = random.choice(values)
            else:
                params[key] = values
        return params

    def generate_population(self, size: int = 10) -> List[GeneratedStrategy]:
        """전략 집단 생성"""
        population = []

        for _ in range(size):
            strategy = self.generate_strategy()
            population.append(strategy)

        logger.info(f"Generated population of {size} strategies")
        return population

    def test_strategy(self, strategy: GeneratedStrategy,
                     symbol: str = "BTC-USD",
                     start_date: Optional[str] = None,
                     end_date: Optional[str] = None) -> Optional[Dict]:
        """
        전략 백테스트

        Args:
            strategy: 테스트할 전략
            symbol: 테스트 종목
            start_date: 시작일
            end_date: 종료일
        """
        if not self._backtest_engine:
            logger.error("Backtest engine not available")
            return None

        try:
            # 데이터 로드
            data = self._backtest_engine.load_data(symbol, start_date, end_date)
            if data is None:
                return None

            # 전략 함수 생성
            strategy_func = self._create_strategy_function(strategy)

            # 백테스트 실행
            result = self._backtest_engine.run_backtest(
                strategy_func, data
            )

            if result:
                # 결과 저장
                strategy.backtest_result = {
                    'total_return': result.total_return_pct,
                    'sharpe_ratio': result.sharpe_ratio,
                    'max_drawdown': result.max_drawdown_pct,
                    'win_rate': result.win_rate,
                    'profit_factor': result.profit_factor,
                    'total_trades': result.total_trades
                }

                # 점수 계산
                strategy.score = self._calculate_score(strategy.backtest_result)
                strategy.status = "tested"

                logger.info(f"Strategy {strategy.name} tested. Score: {strategy.score:.2f}")
                return strategy.backtest_result

        except Exception as e:
            logger.error(f"Strategy test error: {e}")
            strategy.status = "error"

        return None

    def _create_strategy_function(self, strategy: GeneratedStrategy) -> Callable:
        """전략 함수 생성"""
        params = strategy.parameters
        template_name = strategy.template

        def strategy_func(bt):
            """백테스트용 전략 함수"""
            if template_name == "momentum_breakout":
                # 모멘텀 돌파 로직
                lookback = params.get('lookback', 20)
                vol_threshold = params.get('volume_threshold', 1.5)

                if len(bt.data) > lookback:
                    recent_high = max(bt.data.High[-lookback-1:-1])
                    recent_vol_avg = sum(bt.data.Volume[-lookback-1:-1]) / lookback

                    if bt.data.Close[-1] > recent_high and \
                       bt.data.Volume[-1] > recent_vol_avg * vol_threshold:
                        bt.buy()

            elif template_name == "mean_reversion":
                # 평균회귀 로직
                rsi_period = params.get('rsi_period', 14)
                rsi_oversold = params.get('rsi_oversold', 30)

                if len(bt.data) > rsi_period:
                    close_prices = bt.data.Close[-rsi_period:]
                    gains = [close_prices[i] - close_prices[i-1]
                            for i in range(1, len(close_prices)) if close_prices[i] > close_prices[i-1]]
                    losses = [close_prices[i-1] - close_prices[i]
                             for i in range(1, len(close_prices)) if close_prices[i] < close_prices[i-1]]

                    avg_gain = sum(gains) / len(gains) if gains else 0
                    avg_loss = sum(losses) / len(losses) if losses else 1

                    rs = avg_gain / avg_loss if avg_loss != 0 else 0
                    rsi = 100 - (100 / (1 + rs))

                    if rsi < rsi_oversold:
                        bt.buy()

            elif template_name == "trend_following":
                # 추세추종 로직
                fast_ma = params.get('fast_ma', 10)
                slow_ma = params.get('slow_ma', 30)

                if len(bt.data) > slow_ma:
                    fast = sum(bt.data.Close[-fast_ma:]) / fast_ma
                    slow = sum(bt.data.Close[-slow_ma:]) / slow_ma

                    prev_fast = sum(bt.data.Close[-fast_ma-1:-1]) / fast_ma
                    prev_slow = sum(bt.data.Close[-slow_ma-1:-1]) / slow_ma

                    if fast > slow and prev_fast <= prev_slow:
                        bt.buy()
                    elif fast < slow and prev_fast >= prev_slow:
                        bt.sell()

            else:
                # 기본 전략
                if bt.data.Close[-1] > bt.data.Close[-2] * 1.02:
                    bt.buy()

        return strategy_func

    def _calculate_score(self, result: Dict) -> float:
        """전략 종합 점수 계산"""
        if not result:
            return 0.0

        # 가중치
        w_return = 0.3
        w_sharpe = 0.25
        w_drawdown = 0.2
        w_winrate = 0.15
        w_pf = 0.1

        # 정규화된 점수
        return_score = min(result.get('total_return', 0) / 100, 2.0)
        sharpe_score = min(result.get('sharpe_ratio', 0) / 3, 1.0)
        dd_score = max(0, 1 - abs(result.get('max_drawdown', 0)) / 50)
        wr_score = result.get('win_rate', 0)
        pf_score = min(result.get('profit_factor', 0) / 3, 1.0)

        total_score = (return_score * w_return +
                      sharpe_score * w_sharpe +
                      dd_score * w_drawdown +
                      wr_score * w_winrate +
                      pf_score * w_pf)

        return total_score * 100

    def evolve_population(self, population: List[GeneratedStrategy],
                         generations: int = 5,
                         mutation_rate: float = 0.1) -> List[GeneratedStrategy]:
        """
        유전 알고리즘으로 전략 진화

        Args:
            population: 초기 집단
            generations: 세대 수
            mutation_rate: 변이율
        """
        best_strategies = []

        for gen in range(generations):
            logger.info(f"Generation {gen + 1}/{generations}")

            # 각 전략 테스트
            for strategy in population:
                if strategy.status == "pending":
                    self.test_strategy(strategy)

            # 선택 (상위 30%)
            population.sort(key=lambda x: x.score, reverse=True)
            elite_size = max(1, len(population) // 3)
            elites = population[:elite_size]

            best_strategies.extend(elites)

            # 교차 및 변이
            new_population = elites.copy()

            while len(new_population) < len(population):
                parent1 = random.choice(elites)
                parent2 = random.choice(elites)

                child = self._crossover(parent1, parent2)

                if random.random() < mutation_rate:
                    child = self._mutate(child)

                new_population.append(child)

            population = new_population

        # 최종 결과 정렬
        best_strategies.sort(key=lambda x: x.score, reverse=True)
        return best_strategies

    def _crossover(self, parent1: GeneratedStrategy,
                  parent2: GeneratedStrategy) -> GeneratedStrategy:
        """교차 연산"""
        self._strategy_counter += 1

        # 파라미터 교차
        child_params = {}
        for key in parent1.parameters:
            if random.random() < 0.5:
                child_params[key] = parent1.parameters[key]
            else:
                child_params[key] = parent2.parameters.get(key, parent1.parameters[key])

        return GeneratedStrategy(
            id=f"STRAT-{datetime.now().strftime('%Y%m%d')}-{self._strategy_counter:04d}",
            name=f"evolved_{parent1.template}_{self._strategy_counter}",
            template=parent1.template,
            parameters=child_params,
            created_at=datetime.now(),
            backtest_result=None,
            status="pending",
            score=0.0
        )

    def _mutate(self, strategy: GeneratedStrategy) -> GeneratedStrategy:
        """변이 연산"""
        template = next((t for t in self.templates if t.name == strategy.template), None)

        if template:
            for key in strategy.parameters:
                if random.random() < 0.3 and key in template.parameters:
                    values = template.parameters[key]
                    if isinstance(values, list):
                        strategy.parameters[key] = random.choice(values)

        return strategy

    def deploy_strategy(self, strategy: GeneratedStrategy,
                       deployment_config: Optional[Dict] = None) -> bool:
        """
        전략 배포

        Args:
            strategy: 배포할 전략
            deployment_config: 배포 설정
        """
        if strategy.score < 50:
            logger.warning(f"Strategy {strategy.name} score too low for deployment")
            strategy.status = "rejected"
            return False

        try:
            strategy.status = "deployed"
            logger.info(f"Strategy {strategy.name} deployed successfully")

            # 배포 설정 저장
            if deployment_config:
                config_path = Path("strategies/deployed") / f"{strategy.id}.json"
                config_path.parent.mkdir(parents=True, exist_ok=True)

                with open(config_path, 'w') as f:
                    json.dump({
                        'strategy': asdict(strategy),
                        'deployment': deployment_config
                    }, f, indent=2, default=str)

            return True

        except Exception as e:
            logger.error(f"Deployment error: {e}")
            return False

    def get_best_strategies(self, n: int = 5,
                           min_score: float = 60.0) -> List[GeneratedStrategy]:
        """최고 성과 전략 조회"""
        tested = [s for s in self._generated_strategies
                 if s.status == "tested" and s.score >= min_score]

        tested.sort(key=lambda x: x.score, reverse=True)
        return tested[:n]

    def export_strategy(self, strategy: GeneratedStrategy,
                       output_path: str) -> bool:
        """전략 내보내기"""
        try:
            with open(output_path, 'w') as f:
                json.dump(asdict(strategy), f, indent=2, default=str)

            logger.info(f"Strategy exported to {output_path}")
            return True

        except Exception as e:
            logger.error(f"Export error: {e}")
            return False

    def get_generation_stats(self) -> Dict[str, Any]:
        """생성 통계"""
        total = len(self._generated_strategies)
        tested = len([s for s in self._generated_strategies if s.status == "tested"])
        deployed = len([s for s in self._generated_strategies if s.status == "deployed"])
        rejected = len([s for s in self._generated_strategies if s.status == "rejected"])

        avg_score = 0.0
        if tested > 0:
            scores = [s.score for s in self._generated_strategies if s.status == "tested"]
            avg_score = sum(scores) / len(scores)

        return {
            'total_generated': total,
            'tested': tested,
            'deployed': deployed,
            'rejected': rejected,
            'pending': total - tested - deployed - rejected,
            'average_score': avg_score,
            'best_score': max([s.score for s in self._generated_strategies] or [0]),
            'templates_used': len(set(s.template for s in self._generated_strategies))
        }


# 싱글톤 인스턴스
_strategy_generator_instance: Optional[StrategyGenerator] = None


def get_strategy_generator() -> StrategyGenerator:
    """StrategyGenerator 싱글톤 인스턴스 가져오기"""
    global _strategy_generator_instance
    if _strategy_generator_instance is None:
        _strategy_generator_instance = StrategyGenerator()
    return _strategy_generator_instance

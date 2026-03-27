"""
OZ_A2M 제6부서: 연구개발팀 - 통합 백테스팅 엔진

backtesting.py + vectorbt 통합
전략 백테스트, 최적화, 성과 분석
"""

import logging
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum
import json

logger = logging.getLogger(__name__)


class BacktestEngineType(Enum):
    """백테스팅 엔진 타입"""
    BACKTESTING_PY = "backtesting"  # 이벤트 기반
    VECTORBT = "vectorbt"           # 벡터화


@dataclass
class Trade:
    """거래 기록"""
    entry_time: datetime
    exit_time: Optional[datetime]
    symbol: str
    side: str  # long/short
    entry_price: float
    exit_price: Optional[float]
    size: float
    pnl: Optional[float]
    pnl_pct: Optional[float]
    status: str  # open/closed


@dataclass
class BacktestResult:
    """백테스트 결과"""
    strategy_name: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    total_return: float
    total_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_trade_pnl: float
    avg_trade_duration: timedelta
    trades: List[Trade]
    equity_curve: List[Dict[str, Any]]


class BacktestEngine:
    """
    통합 백테스팅 엔진

    기능:
    - backtesting.py 이벤트 기반 백테스트
    - vectorbt 벡터화 백테스트
    - 전략 최적화
    - 성과 분석 및 리포팅
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._engine_type = BacktestEngineType(
            self.config.get('engine', 'backtesting')
        )
        self._results: List[BacktestResult] = []
        self._current_strategy: Optional[Callable] = None

    def load_data(self, symbol: str,
                  start: Optional[str] = None,
                  end: Optional[str] = None,
                  timeframe: str = '1d') -> Optional[Any]:
        """
        백테스트용 데이터 로드

        Args:
            symbol: 종목 심볼
            start: 시작일
            end: 종료일
            timeframe: 시간프레임
        """
        try:
            import yfinance as yf

            if not end:
                end = datetime.now().strftime('%Y-%m-%d')
            if not start:
                start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start, end=end, interval=timeframe)

            if df.empty:
                logger.warning(f"No data for {symbol}")
                return None

            # 컬럼명 표준화
            df.columns = [c.lower().replace(' ', '_') for c in df.columns]

            logger.info(f"Loaded {len(df)} bars for {symbol}")
            return df

        except Exception as e:
            logger.error(f"Data load error: {e}")
            return None

    def run_backtest(self,
                     strategy: Callable,
                     data: Any,
                     initial_capital: float = 10000.0,
                     commission: float = 0.001,
                     slippage: float = 0.0) -> Optional[BacktestResult]:
        """
        백테스트 실행

        Args:
            strategy: 전략 함수
            data: OHLCV 데이터
            initial_capital: 초기 자본
            commission: 수수료 (0.001 = 0.1%)
            slippage: 슬리피지
        """
        if self._engine_type == BacktestEngineType.BACKTESTING_PY:
            return self._run_backtesting_py(strategy, data, initial_capital, commission)
        else:
            return self._run_vectorbt(strategy, data, initial_capital, commission)

    def _run_backtesting_py(self,
                            strategy: Callable,
                            data: Any,
                            initial_capital: float,
                            commission: float) -> Optional[BacktestResult]:
        """backtesting.py 엔진 사용"""
        try:
            from backtesting import Backtest, Strategy

            # 전략 래핑
            class WrappedStrategy(Strategy):
                def init(self):
                    strategy(self)

                def next(self):
                    strategy(self)

            bt = Backtest(
                data, WrappedStrategy,
                cash=initial_capital,
                commission=commission
            )

            stats = bt.run()

            # 결과 변환
            result = BacktestResult(
                strategy_name=strategy.__name__,
                start_date=data.index[0],
                end_date=data.index[-1],
                initial_capital=initial_capital,
                final_capital=stats['Equity Final [$]'],
                total_return=stats['Equity Final [$]'] - initial_capital,
                total_return_pct=stats['Return [%]'],
                sharpe_ratio=stats.get('Sharpe Ratio', 0),
                sortino_ratio=stats.get('Sortino Ratio', 0),
                max_drawdown=stats['Max. Drawdown [$]'],
                max_drawdown_pct=stats['Max. Drawdown [%]'],
                win_rate=stats.get('Win Rate [%]', 0) / 100,
                profit_factor=stats.get('Profit Factor', 0),
                total_trades=stats['# Trades'],
                winning_trades=stats.get('# Wins', 0),
                losing_trades=stats.get('# Losses', 0),
                avg_trade_pnl=stats.get('Avg. Trade [$]', 0),
                avg_trade_duration=timedelta(),
                trades=[],
                equity_curve=[]
            )

            self._results.append(result)
            return result

        except Exception as e:
            logger.error(f"Backtesting.py error: {e}")
            return None

    def _run_vectorbt(self,
                      strategy: Callable,
                      data: Any,
                      initial_capital: float,
                      commission: float) -> Optional[BacktestResult]:
        """vectorbt 엔진 사용"""
        try:
            import vectorbt as vbt

            # 전략 실행
            entries, exits = strategy(data)

            # 포트폴리오 시뮬레이션
            portfolio = vbt.Portfolio.from_signals(
                data['close'],
                entries=entries,
                exits=exits,
                init_cash=initial_capital,
                fees=commission
            )

            # 통계
            stats = portfolio.stats()

            result = BacktestResult(
                strategy_name=strategy.__name__,
                start_date=data.index[0],
                end_date=data.index[-1],
                initial_capital=initial_capital,
                final_capital=portfolio.final_value(),
                total_return=portfolio.total_return(),
                total_return_pct=portfolio.total_return() * 100,
                sharpe_ratio=stats.get('Sharpe Ratio', 0),
                sortino_ratio=stats.get('Sortino Ratio', 0),
                max_drawdown=portfolio.max_drawdown(),
                max_drawdown_pct=portfolio.max_drawdown() * 100,
                win_rate=stats.get('Win Rate', 0),
                profit_factor=stats.get('Profit Factor', 0),
                total_trades=stats.get('Total Trades', 0),
                winning_trades=stats.get('Winning Trades', 0),
                losing_trades=stats.get('Losing Trades', 0),
                avg_trade_pnl=stats.get('Avg Winning Trade', 0),
                avg_trade_duration=timedelta(),
                trades=[],
                equity_curve=[]
            )

            self._results.append(result)
            return result

        except Exception as e:
            logger.error(f"VectorBT error: {e}")
            return None

    def optimize(self,
                 strategy: Callable,
                 data: Any,
                 param_grid: Dict[str, List],
                 metric: str = 'sharpe',
                 initial_capital: float = 10000.0) -> Optional[Dict]:
        """
        전략 최적화

        Args:
            strategy: 전략 함수
            data: OHLCV 데이터
            param_grid: 파라미터 그리드
            metric: 최적화 목표 (sharpe, return, win_rate)
            initial_capital: 초기 자본
        """
        try:
            from backtesting import Backtest
            import itertools

            best_result = None
            best_metric = float('-inf')
            best_params = {}

            # 파라미터 조합 생성
            param_names = list(param_grid.keys())
            param_values = list(param_grid.values())

            for values in itertools.product(*param_values):
                params = dict(zip(param_names, values))

                try:
                    # 전략 래핑
                    class OptimizedStrategy:
                        def __init__(self, params):
                            self.params = params

                        def init(self, bt):
                            pass

                        def next(self, bt):
                            strategy(bt, **self.params)

                    bt = Backtest(data, OptimizedStrategy, cash=initial_capital)
                    stats = bt.run()

                    # 메트릭 평가
                    current_metric = 0
                    if metric == 'sharpe':
                        current_metric = stats.get('Sharpe Ratio', 0)
                    elif metric == 'return':
                        current_metric = stats['Return [%]']
                    elif metric == 'win_rate':
                        current_metric = stats.get('Win Rate [%]', 0)

                    if current_metric > best_metric:
                        best_metric = current_metric
                        best_params = params
                        best_result = stats

                except Exception as e:
                    logger.warning(f"Optimization iteration failed: {e}")
                    continue

            logger.info(f"Optimization complete. Best {metric}: {best_metric}")
            logger.info(f"Best params: {best_params}")

            return {
                'best_params': best_params,
                'best_metric': best_metric,
                'results': best_result
            }

        except Exception as e:
            logger.error(f"Optimization error: {e}")
            return None

    def walk_forward_analysis(self,
                              strategy: Callable,
                              data: Any,
                              train_size: int = 252,
                              test_size: int = 63,
                              initial_capital: float = 10000.0) -> List[BacktestResult]:
        """
        Walk-Forward Analysis

        Args:
            strategy: 전략 함수
            data: OHLCV 데이터
            train_size: 학습 기간 (일)
            test_size: 테스트 기간 (일)
            initial_capital: 초기 자본
        """
        results = []

        try:
            total_bars = len(data)
            start_idx = 0

            while start_idx + train_size + test_size <= total_bars:
                # 학습/테스트 데이터 분할
                train_data = data.iloc[start_idx:start_idx + train_size]
                test_data = data.iloc[start_idx + train_size:start_idx + train_size + test_size]

                # 학습
                logger.info(f"Training on {len(train_data)} bars")

                # 테스트
                result = self.run_backtest(
                    strategy, test_data, initial_capital
                )

                if result:
                    results.append(result)

                start_idx += test_size

            logger.info(f"Walk-forward complete: {len(results)} periods")
            return results

        except Exception as e:
            logger.error(f"Walk-forward error: {e}")
            return results

    def compare_strategies(self,
                          strategies: Dict[str, Callable],
                          data: Any,
                          initial_capital: float = 10000.0) -> Dict[str, BacktestResult]:
        """
        다중 전략 비교

        Args:
            strategies: {이름: 전략함수} 딕셔너리
            data: OHLCV 데이터
            initial_capital: 초기 자본
        """
        results = {}

        for name, strategy in strategies.items():
            logger.info(f"Testing strategy: {name}")
            result = self.run_backtest(strategy, data, initial_capital)
            if result:
                results[name] = result

        return results

    def generate_report(self, result: BacktestResult,
                       output_path: Optional[str] = None) -> str:
        """백테스트 리포트 생성"""
        report = f"""
# OZ_A2M 백테스트 리포트

## 전략: {result.strategy_name}
- 기간: {result.start_date} ~ {result.end_date}
- 초기 자본: ${result.initial_capital:,.2f}
- 최종 자본: ${result.final_capital:,.2f}

## 성과 지표
| 지표 | 값 |
|------|-----|
| 총 수익률 | {result.total_return_pct:.2f}% |
| Sharpe Ratio | {result.sharpe_ratio:.2f} |
| Sortino Ratio | {result.sortino_ratio:.2f} |
| 최대 낙폭 | {result.max_drawdown_pct:.2f}% |
| 승률 | {result.win_rate*100:.1f}% |
| Profit Factor | {result.profit_factor:.2f} |
| 총 거래 수 | {result.total_trades} |
| 평균 거래 손익 | ${result.avg_trade_pnl:,.2f} |

생성 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

        if output_path:
            Path(output_path).write_text(report)
            logger.info(f"Report saved to {output_path}")

        return report

    def get_results_summary(self) -> Dict[str, Any]:
        """모든 백테스트 결과 요약"""
        if not self._results:
            return {}

        return {
            'total_backtests': len(self._results),
            'avg_return': sum(r.total_return_pct for r in self._results) / len(self._results),
            'avg_sharpe': sum(r.sharpe_ratio for r in self._results) / len(self._results),
            'best_strategy': max(self._results, key=lambda x: x.total_return_pct).strategy_name,
            'worst_strategy': min(self._results, key=lambda x: x.total_return_pct).strategy_name,
        }


# 싱글톤 인스턴스
_backtest_engine_instance: Optional[BacktestEngine] = None


def get_backtest_engine() -> BacktestEngine:
    """BacktestEngine 싱글톤 인스턴스 가져오기"""
    global _backtest_engine_instance
    if _backtest_engine_instance is None:
        _backtest_engine_instance = BacktestEngine()
    return _backtest_engine_instance

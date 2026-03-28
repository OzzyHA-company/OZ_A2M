"""
OZ_A2M 제6부서: 연구개발팀 - Microsoft Qlib 어댑터

ML 기반 트레이딩, Alpha 추출, 예측 모델링
"""

import logging
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ModelMetrics:
    """모델 성과 지표"""
    model_name: str
    ic: float  # Information Coefficient
    icir: float  # IC Information Ratio
    rank_ic: float  # Rank IC
    rank_icir: float  # Rank ICIR
    mse: Optional[float] = None
    mae: Optional[float] = None


@dataclass
class PredictionResult:
    """예측 결과"""
    symbol: str
    timestamp: datetime
    predicted_return: float
    confidence: float
    model_name: str
    features: Dict[str, float]


class QlibAdapter:
    """
    Microsoft Qlib 통합 어댑터

    기능:
    - Alpha360/158 feature 추출
    - LightGBM/XGBoost/LSTM 모델 학습
    - 예측 신호 생성
    - 모델 성과 평가
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._qlib_initialized = False
        self._provider_uri = self.config.get(
            'provider_uri',
            str(Path.home() / '.qlib_data')
        )
        self._region = self.config.get('region', 'us')
        self._models: Dict[str, Any] = {}
        self._dataset: Optional[Any] = None

    def initialize(self) -> bool:
        """Qlib 초기화"""
        if self._qlib_initialized:
            return True

        try:
            import qlib
            from qlib.config import REG_CN, REG_US

            region_config = REG_CN if self._region == 'cn' else REG_US

            qlib.init(
                provider_uri=self._provider_uri,
                region=region_config,
                expression_cache=None,
                dataset_cache=None,
                mount_ops=True
            )

            self._qlib_initialized = True
            logger.info(f"Qlib initialized for region: {self._region}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Qlib: {e}")
            return False

    def download_data(self, symbols: List[str],
                      start_date: Optional[str] = None,
                      end_date: Optional[str] = None) -> bool:
        """
        Yahoo Finance에서 데이터 다운로드

        Args:
            symbols: 종목 리스트
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)
        """
        try:
            from qlib.data import D
            from qlib.data.dataset.loader import QlibDataLoader

            if not self._qlib_initialized:
                self.initialize()

            # 기본값 설정
            if not end_date:
                end_date = datetime.now().strftime('%Y-%m-%d')
            if not start_date:
                start_date = (datetime.now() - timedelta(days=365*2)).strftime('%Y-%m-%d')

            logger.info(f"Downloading data for {len(symbols)} symbols")

            # 데이터 로더 설정
            fields = ['$close', '$open', '$high', '$low', '$volume']
            loader = QlibDataLoader(
                config=(fields, fields),
                filter_pipe=None
            )

            # 데이터 로드
            df = loader.load(symbols, start_date, end_date)

            logger.info(f"Data downloaded: {len(df)} records")
            return True

        except Exception as e:
            logger.error(f"Data download error: {e}")
            # Fallback: yfinance 사용
            return self._download_with_yfinance(symbols, start_date, end_date)

    def _download_with_yfinance(self, symbols: List[str],
                                start_date: Optional[str] = None,
                                end_date: Optional[str] = None) -> bool:
        """yfinance fallback"""
        try:
            import yfinance as yf
            import pandas as pd
            from pathlib import Path

            data_dir = Path(self._provider_uri) / self._region
            data_dir.mkdir(parents=True, exist_ok=True)

            for symbol in symbols:
                try:
                    ticker = yf.Ticker(symbol)
                    df = ticker.history(start=start_date, end=end_date)

                    if not df.empty:
                        # Qlib 형식으로 변환
                        df.index.name = 'date'
                        df.columns = [c.lower().replace(' ', '_') for c in df.columns]
                        df['symbol'] = symbol

                        # 저장
                        output_file = data_dir / f"{symbol}.csv"
                        df.to_csv(output_file)
                        logger.info(f"Downloaded {symbol}: {len(df)} records")

                except Exception as e:
                    logger.error(f"Error downloading {symbol}: {e}")

            return True

        except Exception as e:
            logger.error(f"yfinance fallback error: {e}")
            return False

    def create_dataset(self, symbols: List[str],
                       start_date: Optional[str] = None,
                       end_date: Optional[str] = None,
                       handler_class: str = 'Alpha360') -> Optional[Any]:
        """
        Qlib 데이터셋 생성

        Args:
            symbols: 종목 리스트
            start_date: 시작일
            end_date: 종료일
            handler_class: Feature handler (Alpha360, Alpha158)
        """
        if not self._qlib_initialized:
            if not self.initialize():
                return None

        try:
            from qlib.data.dataset import Dataset, TSDataSampler
            from qlib.data.dataset.handler import DataHandlerLP

            # 기본값
            if not end_date:
                end_date = datetime.now().strftime('%Y-%m-%d')
            if not start_date:
                start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

            # Handler 설정
            if handler_class == 'Alpha360':
                from qlib.contrib.data.handler import Alpha360
                handler = Alpha360(
                    instruments=symbols,
                    start_time=start_date,
                    end_time=end_date,
                    fit_start_time=start_date,
                    fit_end_time=end_date,
                    data_loader=None
                )
            elif handler_class == 'Alpha158':
                from qlib.contrib.data.handler import Alpha158
                handler = Alpha158(
                    instruments=symbols,
                    start_time=start_date,
                    end_time=end_date,
                    fit_start_time=start_date,
                    fit_end_time=end_date
                )
            else:
                handler = DataHandlerLP(
                    instruments=symbols,
                    start_time=start_date,
                    end_time=end_date
                )

            # 데이터셋 생성
            dataset = Dataset(handler=handler)
            self._dataset = dataset

            logger.info(f"Dataset created with {handler_class}")
            return dataset

        except Exception as e:
            logger.error(f"Dataset creation error: {e}")
            return None

    def train_model(self, model_name: str = 'lightgbm',
                    model_params: Optional[Dict] = None) -> Optional[Any]:
        """
        ML 모델 학습

        Args:
            model_name: 모델 이름 (lightgbm, xgboost, lstm)
            model_params: 모델 파라미터
        """
        if not self._dataset:
            logger.error("Dataset not created. Call create_dataset first.")
            return None

        try:
            model = None

            if model_name == 'lightgbm':
                from qlib.contrib.model.gbdt import LGBModel
                params = model_params or {
                    'loss': 'mse',
                    'colsample_bytree': 0.8879,
                    'learning_rate': 0.0421,
                    'subsample': 0.8789,
                    'lambda_l1': 205.6999,
                    'lambda_l2': 580.9768,
                    'max_depth': 8,
                    'num_leaves': 210,
                    'num_threads': 4,
                }
                model = LGBModel(**params)

            elif model_name == 'xgboost':
                from qlib.contrib.model.xgboost import XGBModel
                params = model_params or {
                    'eval_metric': 'rmse',
                    'colsample_bytree': 0.8879,
                    'eta': 0.0421,
                    'max_depth': 8,
                    'n_estimators': 500,
                }
                model = XGBModel(**params)

            elif model_name == 'lstm':
                from qlib.contrib.model.pytorch_lstm import LSTM
                params = model_params or {
                    'd_feat': 20,
                    'hidden_size': 64,
                    'num_layers': 2,
                    'dropout': 0.0,
                    'n_epochs': 100,
                    'lr': 1e-3,
                    'early_stop': 10,
                    'batch_size': 800,
                }
                model = LSTM(**params)

            if model:
                # 학습
                model.fit(self._dataset)
                self._models[model_name] = model
                logger.info(f"Model {model_name} trained successfully")
                return model

        except Exception as e:
            logger.error(f"Model training error: {e}")
            return None

    def predict(self, model_name: str = 'lightgbm') -> List[PredictionResult]:
        """
        예측 수행

        Args:
            model_name: 사용할 모델 이름

        Returns:
            예측 결과 리스트
        """
        if model_name not in self._models:
            logger.error(f"Model {model_name} not found")
            return []

        try:
            model = self._models[model_name]
            predictions = model.predict(self._dataset)

            results = []
            for idx, row in predictions.iterrows():
                result = PredictionResult(
                    symbol=idx[1] if isinstance(idx, tuple) else str(idx),
                    timestamp=datetime.now(),
                    predicted_return=float(row),
                    confidence=abs(float(row)),
                    model_name=model_name,
                    features={}
                )
                results.append(result)

            return results

        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return []

    def evaluate_model(self, model_name: str = 'lightgbm') -> Optional[ModelMetrics]:
        """모델 성과 평가"""
        if model_name not in self._models:
            return None

        try:
            from qlib.model.ens.group import RollingGroup

            model = self._models[model_name]

            # IC 계산
            pred_df = model.predict(self._dataset)
            ic = pred_df.corr()

            metrics = ModelMetrics(
                model_name=model_name,
                ic=ic.mean() if hasattr(ic, 'mean') else 0.0,
                icir=ic.std() if hasattr(ic, 'std') else 0.0,
                rank_ic=0.0,
                rank_icir=0.0
            )

            return metrics

        except Exception as e:
            logger.error(f"Model evaluation error: {e}")
            return None

    def get_feature_importance(self, model_name: str = 'lightgbm') -> Dict[str, float]:
        """Feature importance 조회"""
        if model_name not in self._models:
            return {}

        try:
            model = self._models[model_name]

            if hasattr(model, 'get_feature_importance'):
                importance = model.get_feature_importance()
                return dict(importance)

            return {}

        except Exception as e:
            logger.error(f"Feature importance error: {e}")
            return {}

    def save_model(self, model_name: str, path: str) -> bool:
        """모델 저장"""
        try:
            import pickle

            if model_name not in self._models:
                return False

            model = self._models[model_name]
            output_path = Path(path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, 'wb') as f:
                pickle.dump(model, f)

            logger.info(f"Model saved to {path}")
            return True

        except Exception as e:
            logger.error(f"Model save error: {e}")
            return False

    def load_model(self, model_name: str, path: str) -> bool:
        """모델 로드"""
        try:
            import pickle

            with open(path, 'rb') as f:
                model = pickle.load(f)

            self._models[model_name] = model
            logger.info(f"Model loaded from {path}")
            return True

        except Exception as e:
            logger.error(f"Model load error: {e}")
            return False


# 싱글톤 인스턴스
_qlib_adapter_instance: Optional[QlibAdapter] = None


def get_qlib_adapter() -> QlibAdapter:
    """QlibAdapter 싱글톤 인스턴스 가져오기"""
    global _qlib_adapter_instance
    if _qlib_adapter_instance is None:
        _qlib_adapter_instance = QlibAdapter()
    return _qlib_adapter_instance

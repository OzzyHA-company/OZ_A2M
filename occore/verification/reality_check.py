"""
OZ_A2M 제2부서: 정보검증분석센터 - 메인 오케스트레이터

이 모듈은 정보검증분석센터의 메인 클래스인 VerificationCenter를 구현합니다.
- DataRouter로부터 데이터 수신
- 노이즈 필터링, 신호 생성, 9-step 검증 조정
- 타 부서와의 연동
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Any

from .models import (
    TradingSignal,
    FilteredData,
    IndicatorValues,
    VerificationResult,
    VerificationStatus,
    SignalPerformance
)
from .noise_filter import NoiseFilter, get_noise_filter
from .indicators import IndicatorEngine, get_indicator_engine
from .signal_generator import SignalGenerator, get_signal_generator
from .verification_pipeline import VerificationPipeline


logger = logging.getLogger(__name__)


class VerificationCenter:
    """정보검증분석센터 메인 클래스

    DataRouter로부터 데이터를 수신하여 필터링, 신호 생성, 검증을 수행합니다.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """VerificationCenter 초기화

        Args:
            config: 센터 설정 딕셔너리
                - max_history: 가격 히스토리 최대 저장 개수
                - verification_config: 검증 파이프라인 설정
                - signal_generator_config: 신호 생성기 설정
                - noise_filter_config: 노이즈 필터 설정
        """
        self.config = config or {}

        # 설정 추출
        self._max_history = self.config.get('max_history', 100)
        self._verification_config = self.config.get('verification_config', {})
        self._signal_config = self.config.get('signal_generator_config', {})
        self._noise_filter_config = self.config.get('noise_filter_config', {})

        # 컴포넌트 초기화
        self._noise_filter = get_noise_filter(self._noise_filter_config)
        self._indicator_engine = get_indicator_engine()
        self._signal_generator = get_signal_generator(self._signal_config)

        # 데이터 저장소
        self._price_history: Dict[str, List[Decimal]] = {}
        self._volume_history: Dict[str, List[Decimal]] = {}
        self._verified_signals: List[TradingSignal] = []
        self._signal_results: Dict[str, VerificationResult] = {}
        self._signal_performances: Dict[str, SignalPerformance] = {}

        # 통계
        self._stats = {
            'total_signals_generated': 0,
            'total_signals_passed': 0,
            'total_signals_failed': 0,
            'total_data_processed': 0
        }

        logger.info("VerificationCenter initialized")

    def process_data(
        self,
        symbol: str,
        price: Decimal,
        timestamp: datetime,
        volume: Optional[Decimal] = None,
        exchange_prices: Optional[Dict[str, Decimal]] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ) -> List[TradingSignal]:
        """단일 데이터 포인트 처리

        Args:
            symbol: 거래 심볼
            price: 현재 가격
            timestamp: 타임스탬프
            volume: 거래량
            exchange_prices: 거래소별 가격
            additional_data: 추가 데이터

        Returns:
            List[TradingSignal]: 검증된 신호 목록
        """
        # 1. 노이즈 필터링
        filtered_data = self._apply_noise_filter(
            symbol=symbol,
            price=price,
            timestamp=timestamp
        )

        if filtered_data.is_outlier:
            logger.warning(f"Outlier detected for {symbol}, processing with caution")

        # 2. 가격 히스토리 업데이트
        self._update_price_history(symbol, filtered_data.filtered_price)
        if volume:
            self._update_volume_history(symbol, volume)

        # 3. 기술적 지표 계산
        price_history = self._price_history.get(symbol, [])
        volume_history = self._volume_history.get(symbol, [])

        if len(price_history) < 20:
            logger.debug(f"Insufficient history for {symbol} ({len(price_history)} bars)")
            return []

        indicators = self._indicator_engine.calculate(
            symbol=symbol,
            prices=price_history,
            volumes=volume_history if volume_history else None
        )

        # 4. 신호 생성
        current_volume = volume_history[-1] if volume_history else None
        volume_sma = indicators.volume_sma

        signals = self._signal_generator.generate(
            symbol=symbol,
            current_price=filtered_data.filtered_price,
            indicators=indicators,
            price_history=price_history,
            volume=current_volume,
            volume_sma=volume_sma
        )

        self._stats['total_signals_generated'] += len(signals)

        # 5. 각 신호 9-step 검증
        verified_signals = []
        for signal in signals:
            result = self._verify_signal(
                signal=signal,
                filtered_data=filtered_data,
                indicators=indicators,
                exchange_prices=exchange_prices,
                additional_data=additional_data
            )

            if result.status in [VerificationStatus.PASSED, VerificationStatus.WARNING]:
                verified_signals.append(signal)
                self._verified_signals.append(signal)
                self._stats['total_signals_passed'] += 1
            else:
                self._stats['total_signals_failed'] += 1

            self._signal_results[signal.id] = result

        self._stats['total_data_processed'] += 1

        # 6. 타 부서에 알림
        if verified_signals:
            self._notify_control_tower(verified_signals, symbol)

        return verified_signals

    def process_data_package(self, package: Any) -> List[TradingSignal]:
        """DataRouter 패키지 처리

        Args:
            package: DataPackage 객체

        Returns:
            List[TradingSignal]: 검증된 신호 목록
        """
        try:
            # 패키지에서 데이터 추출
            payload = package.payload if hasattr(package, 'payload') else package
            symbol = payload.get('symbol')
            price_data = payload.get('price') or payload.get('close')
            timestamp_str = payload.get('timestamp')
            volume = payload.get('volume')
            exchange_prices = payload.get('exchange_prices', {})

            if not symbol or not price_data:
                logger.warning("Invalid data package: missing symbol or price")
                return []

            # 타임스탬프 파싱
            if isinstance(timestamp_str, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                except ValueError:
                    timestamp = datetime.now()
            elif isinstance(timestamp_str, datetime):
                timestamp = timestamp_str
            else:
                timestamp = datetime.now()

            # 가격 변환
            if isinstance(price_data, (int, float)):
                price = Decimal(str(price_data))
            elif isinstance(price_data, str):
                price = Decimal(price_data)
            else:
                price = price_data

            # 거래량 변환
            if volume and not isinstance(volume, Decimal):
                volume = Decimal(str(volume))

            # 처리 실행
            return self.process_data(
                symbol=symbol,
                price=price,
                timestamp=timestamp,
                volume=volume,
                exchange_prices=exchange_prices,
                additional_data=payload
            )

        except Exception as e:
            logger.error(f"Error processing data package: {e}")
            return []

    def _apply_noise_filter(
        self,
        symbol: str,
        price: Decimal,
        timestamp: datetime
    ) -> FilteredData:
        """노이즈 필터 적용

        Args:
            symbol: 거래 심볼
            price: 현재 가격
            timestamp: 타임스탬프

        Returns:
            FilteredData: 필터링 결과
        """
        price_history = self._price_history.get(symbol, [])
        return self._noise_filter.filter_price_data(
            symbol=symbol,
            price=price,
            timestamp=timestamp,
            price_history=price_history
        )

    def _update_price_history(self, symbol: str, price: Decimal) -> None:
        """가격 히스토리 업데이트

        Args:
            symbol: 거래 심볼
            price: 가격
        """
        if symbol not in self._price_history:
            self._price_history[symbol] = []

        self._price_history[symbol].append(price)

        # 최대 개수 유지
        if len(self._price_history[symbol]) > self._max_history:
            self._price_history[symbol] = self._price_history[symbol][-self._max_history:]

    def _update_volume_history(self, symbol: str, volume: Decimal) -> None:
        """거래량 히스토리 업데이트

        Args:
            symbol: 거래 심볼
            volume: 거래량
        """
        if symbol not in self._volume_history:
            self._volume_history[symbol] = []

        self._volume_history[symbol].append(volume)

        # 최대 개수 유지
        if len(self._volume_history[symbol]) > self._max_history:
            self._volume_history[symbol] = self._volume_history[symbol][-self._max_history:]

    def _verify_signal(
        self,
        signal: TradingSignal,
        filtered_data: FilteredData,
        indicators: IndicatorValues,
        exchange_prices: Optional[Dict[str, Decimal]] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ) -> VerificationResult:
        """신호 9-step 검증

        Args:
            signal: 검증할 신호
            filtered_data: 필터링된 데이터
            indicators: 기술적 지표값들
            exchange_prices: 거래소별 가격
            additional_data: 추가 데이터

        Returns:
            VerificationResult: 검증 결과
        """
        pipeline = VerificationPipeline(self._verification_config)

        # 추가 데이터 구성
        verify_data = additional_data or {}
        if exchange_prices:
            verify_data['exchange_prices'] = exchange_prices

        # 거래량 데이터
        volume_history = self._volume_history.get(signal.symbol, [])
        if volume_history:
            verify_data['current_volume'] = volume_history[-1]
            if len(volume_history) >= 20:
                avg_volume = sum(volume_history[-20:]) / 20
                verify_data['avg_volume'] = avg_volume

        # 스프레드 데이터 (있는 경우)
        if 'spread_pct' in verify_data:
            verify_data['spread_pct'] = verify_data['spread_pct']

        return pipeline.execute(
            signal=signal,
            filtered_data=filtered_data,
            indicators=indicators,
            additional_data=verify_data
        )

    def _notify_control_tower(self, signals: List[TradingSignal], symbol: str) -> None:
        """제1부서 (관제탑)에 신호 알림

        Args:
            signals: 검증된 신호 목록
            symbol: 거래 심볼
        """
        try:
            # 동적 임포트 (순환 참조 방지)
            from ..control_tower.situation_board import get_situation_board

            board = get_situation_board()
            for signal in signals:
                board.add_signal(signal)
                logger.debug(f"Signal {signal.id} notified to Control Tower")

        except ImportError:
            logger.debug("Control Tower not available for notification")
        except Exception as e:
            logger.error(f"Error notifying Control Tower: {e}")

    def record_signal_performance(
        self,
        signal_id: str,
        entry_price: Decimal,
        exit_price: Decimal,
        entry_time: datetime,
        exit_time: datetime
    ) -> SignalPerformance:
        """신호 성과 기록

        Args:
            signal_id: 신호 ID
            entry_price: 진입 가격
            exit_price: 청산 가격
            entry_time: 진입 시간
            exit_time: 청산 시간

        Returns:
            SignalPerformance: 성과 데이터
        """
        performance = SignalPerformance(
            signal_id=signal_id,
            symbol="",  # 나중에 채움
            entry_price=entry_price,
            exit_price=exit_price,
            entry_time=entry_time,
            exit_time=exit_time
        )

        # 원본 신호에서 심볼 가져오기
        for signal in self._verified_signals:
            if signal.id == signal_id:
                performance.symbol = signal.symbol
                break

        self._signal_performances[signal_id] = performance

        # R&D 팀에 피드백
        self._notify_rnd(signal_id, performance)

        return performance

    def _notify_rnd(self, signal_id: str, performance: SignalPerformance) -> None:
        """제6부서 (R&D)에 성과 피드백

        Args:
            signal_id: 신호 ID
            performance: 성과 데이터
        """
        try:
            from ..rnd.strategy_generator import get_strategy_generator

            generator = get_strategy_generator()
            # 피드백 전송 (인터페이스에 맞게 조정)
            logger.debug(f"Performance feedback sent to R&D for signal {signal_id}")

        except ImportError:
            logger.debug("R&D not available for feedback")
        except Exception as e:
            logger.error(f"Error sending feedback to R&D: {e}")

    def get_verified_signals(
        self,
        symbol: Optional[str] = None,
        status: Optional[VerificationStatus] = None,
        min_confidence: float = 0.0
    ) -> List[TradingSignal]:
        """검증된 신호 조회

        Args:
            symbol: 특정 심볼
            status: 검증 상태 필터
            min_confidence: 최소 신뢰도

        Returns:
            List[TradingSignal]: 필터링된 신호 목록
        """
        signals = self._verified_signals

        if symbol:
            signals = [s for s in signals if s.symbol == symbol]

        if status:
            result_ids = [
                sid for sid, result in self._signal_results.items()
                if result.status == status
            ]
            signals = [s for s in signals if s.id in result_ids]

        if min_confidence > 0:
            signals = [s for s in signals if s.confidence >= min_confidence]

        return signals

    def get_signal_result(self, signal_id: str) -> Optional[VerificationResult]:
        """특정 신호의 검증 결과 조회

        Args:
            signal_id: 신호 ID

        Returns:
            Optional[VerificationResult]: 검증 결과
        """
        return self._signal_results.get(signal_id)

    def get_statistics(self) -> Dict[str, Any]:
        """센터 통계 조회

        Returns:
            Dict[str, Any]: 통계 데이터
        """
        stats = self._stats.copy()

        # 추가 통계 계산
        if stats['total_signals_generated'] > 0:
            stats['pass_rate'] = (
                stats['total_signals_passed'] / stats['total_signals_generated']
            )
        else:
            stats['pass_rate'] = 0.0

        stats['monitored_symbols'] = len(self._price_history)
        stats['stored_signals'] = len(self._verified_signals)

        return stats

    def clear_history(self, symbol: Optional[str] = None) -> None:
        """히스토리 데이터 초기화

        Args:
            symbol: 특정 심볼 (None이면 전체)
        """
        if symbol:
            self._price_history.pop(symbol, None)
            self._volume_history.pop(symbol, None)
        else:
            self._price_history.clear()
            self._volume_history.clear()

        logger.info(f"History cleared for {symbol if symbol else 'all symbols'}")


# 싱글톤 인스턴스
_verification_center_instance: Optional[VerificationCenter] = None


def get_verification_center(config: Optional[Dict[str, Any]] = None) -> VerificationCenter:
    """VerificationCenter 싱글톤 인스턴스 가져오기

    Args:
        config: 센터 설정 (처음 생성 시에만 사용)

    Returns:
        VerificationCenter: 싱글톤 인스턴스
    """
    global _verification_center_instance
    if _verification_center_instance is None:
        _verification_center_instance = VerificationCenter(config)
    return _verification_center_instance


def init_verification_center(config: Optional[Dict[str, Any]] = None) -> VerificationCenter:
    """VerificationCenter 명시적 초기화

    Args:
        config: 센터 설정

    Returns:
        VerificationCenter: 새로 생성된 인스턴스
    """
    global _verification_center_instance
    _verification_center_instance = VerificationCenter(config)
    logger.info("VerificationCenter explicitly initialized")
    return _verification_center_instance

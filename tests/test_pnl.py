#!/usr/bin/env python3
"""
제5부서: 일일 성과분석팀 (PnL Center) - 테스트

PnL 계산 및 성과 분석 기능을 테스트합니다.
"""

import sys
import os
import unittest
from datetime import datetime, date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from occore.pnl import (
    # Models
    TradeRecord, DailyPnL, PerformanceMetrics,
    PnLType, TradeStatus, PositionSide,
    # Exceptions
    PnLError, TradeNotFoundError, InvalidTradeError,
    # Classes
    ProfitCalculator, PerformanceAnalyzer, ReportGenerator,
    # Singleton getters
    get_calculator, init_calculator,
    get_analyzer, init_analyzer,
    get_report_generator, init_report_generator,
)


class TestPnLModels(unittest.TestCase):
    """모델 테스트"""

    def test_trade_record_creation(self):
        """거래 레코드 생성 테스트"""
        trade = TradeRecord(
            trade_id="test-001",
            symbol="BTC-USDT",
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            entry_time=datetime(2026, 3, 27, 10, 0, 0),
        )
        self.assertEqual(trade.trade_id, "test-001")
        self.assertEqual(trade.symbol, "BTC-USDT")
        self.assertEqual(trade.status, TradeStatus.OPEN)
        self.assertEqual(trade.pnl, Decimal('0'))

    def test_trade_record_close(self):
        """거래 종료 및 PnL 계산 테스트"""
        trade = TradeRecord(
            trade_id="test-002",
            symbol="BTC-USDT",
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            entry_time=datetime(2026, 3, 27, 10, 0, 0),
            fees=Decimal('5'),
        )
        trade.update_exit(
            exit_price=Decimal('55000'),
            exit_time=datetime(2026, 3, 27, 14, 0, 0),
            fees=Decimal('5'),
        )

        # PnL = (55000 - 50000) * 0.1 - 10 = 500 - 10 = 490
        expected_pnl = Decimal('490')
        self.assertEqual(trade.pnl, expected_pnl)
        self.assertEqual(trade.status, TradeStatus.CLOSED)
        self.assertAlmostEqual(trade.pnl_percent, 9.8, places=1)

    def test_short_trade_pnl(self):
        """숏 포지션 PnL 계산 테스트"""
        trade = TradeRecord(
            trade_id="test-003",
            symbol="BTC-USDT",
            side=PositionSide.SHORT,
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            entry_time=datetime(2026, 3, 27, 10, 0, 0),
        )
        trade.update_exit(
            exit_price=Decimal('48000'),
            exit_time=datetime(2026, 3, 27, 14, 0, 0),
        )

        # PnL = (50000 - 48000) * 0.1 = 200
        expected_pnl = Decimal('200')
        self.assertEqual(trade.pnl, expected_pnl)

    def test_daily_pnl_aggregation(self):
        """일일 PnL 집계 테스트"""
        daily = DailyPnL(date=date(2026, 3, 27))

        # 수익 거래
        win_trade = TradeRecord(
            trade_id="win-001",
            symbol="BTC-USDT",
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            entry_time=datetime(2026, 3, 27, 10, 0, 0),
        )
        win_trade.update_exit(
            exit_price=Decimal('55000'),
            exit_time=datetime(2026, 3, 27, 11, 0, 0),
        )

        # 손실 거래
        loss_trade = TradeRecord(
            trade_id="loss-001",
            symbol="ETH-USDT",
            side=PositionSide.LONG,
            entry_price=Decimal('3000'),
            quantity=Decimal('1'),
            entry_time=datetime(2026, 3, 27, 10, 0, 0),
        )
        loss_trade.update_exit(
            exit_price=Decimal('2900'),
            exit_time=datetime(2026, 3, 27, 11, 0, 0),
        )

        daily.add_trade(win_trade)
        daily.add_trade(loss_trade)

        self.assertEqual(daily.trade_count, 2)
        self.assertEqual(daily.win_count, 1)
        self.assertEqual(daily.loss_count, 1)
        self.assertEqual(daily.win_rate, 50.0)


class TestProfitCalculator(unittest.TestCase):
    """수익 계산기 테스트"""

    def setUp(self):
        """각 테스트 전 초기화"""
        init_calculator()
        self.calculator = get_calculator()
        self.calculator.clear_history()

    def test_singleton(self):
        """싱글톤 패턴 테스트"""
        calc2 = get_calculator()
        self.assertIs(self.calculator, calc2)

    def test_add_and_close_trade(self):
        """거래 추가 및 종료 테스트"""
        trade = self.calculator.add_trade(
            trade_id="calc-001",
            symbol="BTC-USDT",
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
        )

        self.assertEqual(trade.status, TradeStatus.OPEN)
        self.assertEqual(len(self.calculator.get_open_trades()), 1)

        closed = self.calculator.close_trade(
            trade_id="calc-001",
            exit_price=Decimal('55000'),
        )

        self.assertEqual(closed.status, TradeStatus.CLOSED)
        self.assertEqual(len(self.calculator.get_open_trades()), 0)
        self.assertEqual(len(self.calculator.get_closed_trades()), 1)

    def test_invalid_trade(self):
        """잘못된 거래 데이터 테스트"""
        with self.assertRaises(InvalidTradeError):
            self.calculator.add_trade(
                trade_id="invalid",
                symbol="BTC-USDT",
                side=PositionSide.LONG,
                entry_price=Decimal('0'),  # 잘못된 가격
                quantity=Decimal('0.1'),
            )

    def test_trade_not_found(self):
        """존재하지 않는 거래 조회 테스트"""
        with self.assertRaises(TradeNotFoundError):
            self.calculator.get_trade("non-existent")

    def test_daily_pnl_accumulation(self):
        """일일 PnL 누적 테스트"""
        today = date(2026, 3, 27)

        # 거래 3개 추가
        for i in range(3):
            trade_id = f"batch-{i}"
            self.calculator.add_trade(
                trade_id=trade_id,
                symbol="BTC-USDT",
                side=PositionSide.LONG,
                entry_price=Decimal('50000'),
                quantity=Decimal('0.1'),
                entry_time=datetime(2026, 3, 27, 10 + i, 0, 0),
            )
            self.calculator.close_trade(
                trade_id=trade_id,
                exit_price=Decimal('51000'),
                exit_time=datetime(2026, 3, 27, 11 + i, 0, 0),
            )

        daily = self.calculator.get_daily_pnl(today)
        self.assertIsNotNone(daily)
        self.assertEqual(daily.trade_count, 3)
        self.assertEqual(daily.win_count, 3)


class TestPerformanceAnalyzer(unittest.TestCase):
    """성과 분석기 테스트"""

    def setUp(self):
        """각 테스트 전 초기화"""
        init_analyzer()
        self.analyzer = get_analyzer()

    def test_singleton(self):
        """싱글톤 패턴 테스트"""
        analyzer2 = get_analyzer()
        self.assertIs(self.analyzer, analyzer2)

    def test_sharpe_ratio(self):
        """샤프 비율 계산 테스트"""
        # 일간 수익률 1%, 변동성 2% 가정
        returns = [0.01, -0.005, 0.015, 0.008, -0.002, 0.012, 0.005]
        sharpe = self.analyzer.calculate_sharpe_ratio(returns)
        self.assertGreater(sharpe, 0)  # 양수 수익률이므로 샤프 비율 > 0

    def test_sharpe_insufficient_data(self):
        """샤프 비율 데이터 부족 테스트"""
        with self.assertRaises(Exception):  # InsufficientDataError
            self.analyzer.calculate_sharpe_ratio([0.01])  # 1개 데이터

    def test_max_drawdown(self):
        """최대 낙폭 계산 테스트"""
        equity_curve = [
            Decimal('10000'),
            Decimal('10500'),  # +5%
            Decimal('10200'),  # -2.86% from peak
            Decimal('10800'),  # new peak
            Decimal('10300'),  # -4.63% from peak (MDD)
            Decimal('10600'),  # recovery
        ]

        mdd_percent, mdd_amount = self.analyzer.calculate_max_drawdown(equity_curve)
        self.assertAlmostEqual(mdd_percent, 4.63, places=1)
        self.assertEqual(mdd_amount, Decimal('500'))

    def test_win_rate(self):
        """승률 계산 테스트"""
        trades = [
            TradeRecord("t1", "BTC", PositionSide.LONG, Decimal('50000'), Decimal('0.1'), datetime.now()),
            TradeRecord("t2", "BTC", PositionSide.LONG, Decimal('50000'), Decimal('0.1'), datetime.now()),
            TradeRecord("t3", "BTC", PositionSide.LONG, Decimal('50000'), Decimal('0.1'), datetime.now()),
        ]
        # 2승 1패 설정
        trades[0].update_exit(Decimal('55000'), datetime.now())  # 승
        trades[1].update_exit(Decimal('48000'), datetime.now())  # 패
        trades[2].update_exit(Decimal('53000'), datetime.now())  # 승

        win_rate = self.analyzer.calculate_win_rate(trades)
        self.assertAlmostEqual(win_rate, 66.67, places=1)

    def test_profit_factor(self):
        """수익 팩터 계산 테스트"""
        trades = [
            TradeRecord("t1", "BTC", PositionSide.LONG, Decimal('50000'), Decimal('0.1'), datetime.now()),
            TradeRecord("t2", "BTC", PositionSide.LONG, Decimal('50000'), Decimal('0.1'), datetime.now()),
        ]
        # 수익 500, 손실 200
        trades[0].update_exit(Decimal('55000'), datetime.now())
        trades[1].update_exit(Decimal('48000'), datetime.now())

        pf = self.analyzer.calculate_profit_factor(trades)
        self.assertAlmostEqual(pf, 2.5, places=1)  # 500 / 200 = 2.5


class TestReportGenerator(unittest.TestCase):
    """리포트 생성기 테스트"""

    def setUp(self):
        """각 테스트 전 초기화"""
        init_calculator()
        init_report_generator()
        self.calculator = get_calculator()
        self.report = get_report_generator()
        self.calculator.clear_history()

    def test_singleton(self):
        """싱글톤 패턴 테스트"""
        report2 = get_report_generator()
        self.assertIs(self.report, report2)

    def test_daily_report_format(self):
        """일일 리포트 포맷 테스트"""
        today = date(2026, 3, 27)

        # 거래 추가
        self.calculator.add_trade(
            trade_id="rpt-001",
            symbol="BTC-USDT",
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
            entry_time=datetime(2026, 3, 27, 10, 0, 0),
        )
        self.calculator.close_trade(
            trade_id="rpt-001",
            exit_price=Decimal('55000'),
            exit_time=datetime(2026, 3, 27, 14, 0, 0),
        )

        report_str = self.report.generate_daily_report(today)
        self.assertIn("OZ_A2M", report_str)
        self.assertIn("2026-03-27", report_str)
        self.assertIn("500.00", report_str)  # 수익 내용 포함

    def test_empty_report(self):
        """빈 리포트 테스트"""
        empty_date = date(2020, 1, 1)
        report_str = self.report.generate_daily_report(empty_date)
        self.assertIn("거래 데이터 없음", report_str)


class TestPnLIntegration(unittest.TestCase):
    """통합 테스트"""

    def setUp(self):
        """전체 초기화"""
        init_calculator()
        init_analyzer()
        self.calculator = get_calculator()
        self.analyzer = get_analyzer()
        self.calculator.clear_history()

    def test_full_workflow(self):
        """전체 워크플로우 테스트"""
        # 1. 거래 추가
        self.calculator.add_trade(
            trade_id="flow-001",
            symbol="BTC-USDT",
            side=PositionSide.LONG,
            entry_price=Decimal('50000'),
            quantity=Decimal('0.1'),
        )

        # 2. 거래 종료
        self.calculator.close_trade(
            trade_id="flow-001",
            exit_price=Decimal('55000'),
        )

        # 3. 거래 조회
        trade = self.calculator.get_trade("flow-001")
        self.assertEqual(trade.status, TradeStatus.CLOSED)
        self.assertGreater(trade.pnl, Decimal('0'))

        # 4. 일일 PnL 조회
        today = datetime.utcnow().date()
        daily = self.calculator.get_daily_pnl(today)
        self.assertIsNotNone(daily)

        # 5. 성과 분석
        closed_trades = self.calculator.get_closed_trades()
        metrics = self.analyzer.analyze_trades(closed_trades)
        self.assertGreater(metrics.total_trades, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

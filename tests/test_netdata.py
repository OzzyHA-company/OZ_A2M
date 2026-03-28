#!/usr/bin/env python3
"""
제4부서 유지보수관리센터: Netdata 통합 테스트

Netdata 실시간 모니터링 기능을 테스트합니다.
Note: 실제 Netdata 인스턴스가 필요한 테스트는 skip 처리됩니다.
"""

import sys
import os
import unittest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from occore.devops import (
    NetdataAdapter,
    HealthChecker,
    get_netdata_adapter,
    init_netdata_adapter,
    get_health_checker,
    init_health_checker,
)
from occore.devops.models import HealthStatus, ResourceMetrics


class TestNetdataAdapter(unittest.TestCase):
    """Netdata Adapter 단위 테스트"""

    def setUp(self):
        """각 테스트 전 초기화"""
        self.adapter = NetdataAdapter(host="localhost:19999")

    def test_init(self):
        """초기화 테스트"""
        self.assertEqual(self.adapter.host, "localhost:19999")
        self.assertEqual(self.adapter.base_url, "http://localhost:19999/api/v1")
        self.assertFalse(self.adapter.is_connected())

    def test_risk_to_severity_mapping(self):
        """위험 점수 계산 메서드 (남아있는 경우)"""
        # _calculate_cpu_usage는 private 메서드지만 낮은 수준의 로직 테스트
        test_data = {
            'data': [
                [1609459200, 10.5, 5.2, 0, 0, 0, 0, 0, 0]  # time, user, system, ...
            ],
            'labels': ['time', 'user', 'system', 'nice', 'iowait', 'irq', 'softirq', 'steal', 'guest']
        }
        result = self.adapter._calculate_cpu_usage(test_data)
        self.assertEqual(result, 15.7)  # 10.5 + 5.2

    def test_calculate_memory_usage(self):
        """메모리 사용률 계산 테스트"""
        test_data = {
            'data': [
                [1609459200, 2000, 6000, 1500, 500]  # time, free, used, cached, buffers
            ],
            'labels': ['time', 'free', 'used', 'cached', 'buffers']
        }
        result = self.adapter._calculate_memory_usage(test_data)
        # used / total = 6000 / (2000 + 6000 + 1500 + 500) = 6000 / 10000 = 60%
        self.assertEqual(result, 60.0)

    @patch('requests.get')
    def test_connect_success(self, mock_get):
        """연결 성공 테스트"""
        mock_get.return_value.status_code = 200
        result = self.adapter.connect()
        self.assertTrue(result)
        self.assertTrue(self.adapter.is_connected())

    @patch('requests.get')
    def test_connect_failure(self, mock_get):
        """연결 실패 테스트"""
        mock_get.side_effect = Exception("Connection refused")
        result = self.adapter.connect()
        self.assertFalse(result)
        self.assertFalse(self.adapter.is_connected())

    @patch('requests.get')
    def test_get_chart_data(self, mock_get):
        """차트 데이터 조회 테스트"""
        mock_response = Mock()
        mock_response.json.return_value = {'data': [[1609459200, 50.0]]}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # 연결 상태 설정
        self.adapter._connected = True

        result = self.adapter._get_chart_data("system.cpu", points=1)
        self.assertIsNotNone(result)
        self.assertEqual(result['data'][0][1], 50.0)

    def test_parse_alarms(self):
        """알림 파싱 테스트"""
        test_alarms = {
            'alarms': [
                {
                    'id': 1,
                    'name': 'high_cpu',
                    'chart': 'system.cpu',
                    'status': 'WARNING',
                    'old_status': 'CLEAR',
                    'value': 85.5,
                    'configured': True,
                    'last_updated': '2026-03-27T10:00:00Z'
                },
                {
                    'id': 2,
                    'name': 'low_ram',
                    'chart': 'system.ram',
                    'status': 'CRITICAL',
                    'old_status': 'WARNING',
                    'value': 95.0,
                    'configured': True,
                    'last_updated': '2026-03-27T10:05:00Z'
                }
            ]
        }

        parsed = self.adapter._parse_alarms(test_alarms)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]['name'], 'high_cpu')
        self.assertEqual(parsed[0]['status'], 'WARNING')
        self.assertEqual(parsed[1]['status'], 'CRITICAL')


class TestHealthCheckerNetdata(unittest.TestCase):
    """HealthChecker Netdata 통합 테스트"""

    def setUp(self):
        """각 테스트 전 초기화 (Netdata 없이)"""
        self.checker = HealthChecker(use_netdata=False)

    def test_init_without_netdata(self):
        """Netdata 없이 초기화 테스트"""
        self.assertFalse(self.checker.is_netdata_enabled())

    @patch('occore.devops.netdata_adapter.requests.get')
    def test_init_with_netdata(self, mock_get):
        """Netdata 사용 초기화 테스트"""
        mock_get.return_value.status_code = 200

        checker = HealthChecker(use_netdata=True, netdata_host="localhost:19999")
        # 연결 시도 후 상태 확인
        self.assertTrue(checker.is_netdata_enabled())

    def test_get_netdata_metrics_disabled(self):
        """Netdata 비활성화 시 메트릭 조회"""
        result = self.checker.get_netdata_metrics()
        self.assertIsNone(result)  # None 반환

    def test_get_netdata_alarms_disabled(self):
        """Netdata 비활성화 시 알림 조회"""
        result = self.checker.get_netdata_alarms()
        self.assertEqual(result, [])  # 빈 리스트 반환

    def test_check_netdata_health_disabled(self):
        """Netdata 비활성화 시 헬스 체크"""
        status, message = self.checker.check_netdata_health()
        self.assertEqual(status, HealthStatus.WARNING)
        self.assertIn("not enabled", message)


@unittest.skipUnless(
    os.environ.get('NETDATA_TEST_ENABLED') == '1',
    'Netdata integration tests disabled (set NETDATA_TEST_ENABLED=1 to enable)'
)
class TestNetdataIntegration(unittest.TestCase):
    """Netdata 통합 테스트 (실제 인스턴스 필요)"""

    @classmethod
    def setUpClass(cls):
        """테스트 클래스 초기화"""
        cls.adapter = init_netdata_adapter("localhost:19999")
        if not cls.adapter.connect():
            raise unittest.SkipTest('Netdata not available')

    def test_connection(self):
        """연결 테스트"""
        self.assertTrue(self.adapter.is_connected())

    def test_get_system_metrics(self):
        """시스템 메트릭 조회 테스트"""
        metrics = self.adapter.get_system_metrics()
        self.assertIsNotNone(metrics)
        self.assertIn('cpu_percent', metrics)
        self.assertIn('memory_percent', metrics)

    def test_get_resource_metrics(self):
        """ResourceMetrics 변환 테스트"""
        metrics = self.adapter.get_resource_metrics()
        self.assertIsInstance(metrics, ResourceMetrics)
        self.assertIsNotNone(metrics.timestamp)

    def test_get_alarm_log(self):
        """알림 로그 조회 테스트"""
        alarms = self.adapter.get_alarm_log(last_alarms=10)
        self.assertIsInstance(alarms, list)

    def test_get_active_alarms(self):
        """활성 알림 조회 테스트"""
        alarms = self.adapter.get_active_alarms()
        self.assertIsInstance(alarms, list)

    def test_get_all_charts(self):
        """차트 목록 조회 테스트"""
        charts = self.adapter.get_all_charts()
        self.assertIsInstance(charts, list)
        if charts:
            self.assertIn('id', charts[0])
            self.assertIn('name', charts[0])

    def test_get_trading_metrics(self):
        """트레이딩 메트릭 조회 테스트"""
        metrics = self.adapter.get_trading_metrics()
        self.assertIsInstance(metrics, dict)
        self.assertIn('timestamp', metrics)
        self.assertIn('system', metrics)
        self.assertIn('network', metrics)

    def test_check_health(self):
        """헬스 체크 테스트"""
        status, message = self.adapter.check_health()
        self.assertIn(status, [HealthStatus.HEALTHY, HealthStatus.WARNING, HealthStatus.CRITICAL])
        self.assertIsInstance(message, str)


class TestNetdataSingleton(unittest.TestCase):
    """싱글톤 패턴 테스트"""

    def test_adapter_singleton(self):
        """NetdataAdapter 싱글톤 테스트"""
        adapter1 = NetdataAdapter()
        adapter2 = NetdataAdapter()

        # 별도 인스턴스 (설계상 싱글톤이 아님)
        self.assertIsNot(adapter1, adapter2)

    def test_get_netdata_adapter(self):
        """get_netdata_adapter 싱글톤 테스트"""
        from occore.devops import get_netdata_adapter

        adapter1 = get_netdata_adapter()
        adapter2 = get_netdata_adapter()

        self.assertIs(adapter1, adapter2)


if __name__ == '__main__':
    unittest.main(verbosity=2)

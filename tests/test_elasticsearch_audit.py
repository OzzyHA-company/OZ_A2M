#!/usr/bin/env python3
"""
제3부서 보안팀: Elasticsearch 감사 로그 통합 테스트

Elasticsearch 연동 기능을 테스트합니다.
Note: 실제 Elasticsearch 인스턴스가 필요한 테스트는 skip 처리됩니다.
"""

import sys
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from occore.security import (
    AuditLogger,
    ElasticsearchAuditAdapter,
    get_audit_logger,
    init_audit_logger,
    init_elasticsearch_adapter,
)


class TestElasticsearchAuditAdapter(unittest.TestCase):
    """Elasticsearch Audit Adapter 테스트"""

    def setUp(self):
        """각 테스트 전 초기화"""
        self.adapter = ElasticsearchAuditAdapter(hosts=['localhost:9200'])

    def test_init(self):
        """초기화 테스트"""
        self.assertEqual(self.adapter.hosts, ['localhost:9200'])
        self.assertEqual(self.adapter.index_prefix, 'oz_a2m_audit')
        self.assertFalse(self.adapter.is_connected())

    def test_risk_to_severity(self):
        """위험 점수 -> 심각도 변환 테스트"""
        self.assertEqual(self.adapter._risk_to_severity(90), 'critical')
        self.assertEqual(self.adapter._risk_to_severity(70), 'high')
        self.assertEqual(self.adapter._risk_to_severity(50), 'medium')
        self.assertEqual(self.adapter._risk_to_severity(30), 'low')
        self.assertEqual(self.adapter._risk_to_severity(0), 'low')


class TestAuditLoggerElasticsearch(unittest.TestCase):
    """AuditLogger 하이브리드 모드 테스트"""

    def setUp(self):
        """각 테스트 전 초기화 (SQLite만 사용)"""
        # 임시 DB 사용
        import tempfile
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / 'test_audit.db'

        # Elasticsearch 없이 초기화
        self.audit = AuditLogger(
            db_path=self.db_path,
            use_elasticsearch=False
        )

    def tearDown(self):
        """테스트 후 정리"""
        import shutil
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_sqlite_fallback(self):
        """SQLite fallback 테스트 (Elasticsearch 비활성화)"""
        # 로그 기록
        log_id = self.audit.log_command(
            user_id='test_user',
            ip_address='192.168.1.1',
            command='test_command',
            result='success'
        )

        self.assertIsNotNone(log_id)
        self.assertGreater(log_id, 0)

        # 로그 조회
        logs = self.audit.get_recent_logs(hours=1)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['command'], 'test_command')

    def test_stats_structure(self):
        """통계 구조 테스트"""
        stats = self.audit.get_stats()

        # SQLite 통계 확인
        self.assertIn('sqlite', stats)
        self.assertIn('total_logs', stats['sqlite'])
        self.assertIn('today_logs', stats['sqlite'])
        self.assertIn('unresolved_alerts', stats['sqlite'])

        # Elasticsearch 통계는 None 또는 dict
        self.assertIn('elasticsearch', stats)

    def test_aggregate_event_types_fallback(self):
        """이벤트 유형 집계 fallback 테스트"""
        # 로그 생성
        self.audit.log_command(
            user_id='user1',
            ip_address='192.168.1.1',
            command='cmd1',
            result='success'
        )
        self.audit.log_command(
            user_id='user2',
            ip_address='192.168.1.2',
            command='cmd2',
            result='success'
        )

        # 집계 (SQLite fallback)
        agg = self.audit.aggregate_event_types(hours=1)
        self.assertIn('command', agg)
        self.assertGreaterEqual(agg['command'], 2)

    def test_failed_attempts_aggregation(self):
        """실패 시도 집계 테스트"""
        # 실패 시도 기록
        for i in range(5):
            self.audit.log_access_attempt(
                ip_address='192.168.1.100',
                attempt_type='login',
                success=False,
                reason='Invalid password'
            )

        # 집계
        failed = self.audit.get_failed_attempts_aggregated(
            hours=1,
            min_attempts=3
        )

        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]['ip'], '192.168.1.100')
        self.assertGreaterEqual(failed[0]['count'], 5)


@unittest.skipUnless(
    os.environ.get('ES_TEST_ENABLED') == '1',
    'Elasticsearch integration tests disabled (set ES_TEST_ENABLED=1 to enable)'
)
class TestElasticsearchIntegration(unittest.TestCase):
    """Elasticsearch 통합 테스트 (실제 인스턴스 필요)"""

    @classmethod
    def setUpClass(cls):
        """테스트 클래스 초기화"""
        cls.adapter = init_elasticsearch_adapter(['localhost:9200'])
        if not cls.adapter.connect():
            raise unittest.SkipTest('Elasticsearch not available')

    def test_connection(self):
        """연결 테스트"""
        self.assertTrue(self.adapter.is_connected())

    def test_index_log(self):
        """로그 인덱싱 테스트"""
        doc_id = self.adapter.index_log({
            'event_type': 'test',
            'user_id': 'test_user',
            'message': 'Test log entry'
        })
        self.assertIsNotNone(doc_id)

    def test_index_command_log(self):
        """명령어 로그 인덱싱 테스트"""
        doc_id = self.adapter.index_command_log(
            user_id='test_user',
            ip_address='192.168.1.1',
            command='test_command',
            result='success',
            risk_score=10
        )
        self.assertIsNotNone(doc_id)

    def test_search_logs(self):
        """로그 검색 테스트"""
        # 검색 (최근 1시간)
        results = self.adapter.search_logs(
            query='test',
            hours=1,
            limit=10
        )
        self.assertIsInstance(results, list)

    def test_aggregate_by_event_type(self):
        """이벤트 유형 집계 테스트"""
        agg = self.adapter.aggregate_by_event_type(hours=1)
        self.assertIsInstance(agg, dict)


class TestElasticsearchSingleton(unittest.TestCase):
    """싱글톤 패턴 테스트"""

    def test_adapter_singleton(self):
        """ElasticsearchAdapter 싱글톤 테스트"""
        adapter1 = ElasticsearchAuditAdapter()
        adapter2 = ElasticsearchAuditAdapter()

        # 별도 인스턴스 (설계상 싱글톤이 아님)
        self.assertIsNot(adapter1, adapter2)

    def test_get_elasticsearch_adapter(self):
        """get_elasticsearch_adapter 싱글톤 테스트"""
        from occore.security import get_elasticsearch_adapter

        adapter1 = get_elasticsearch_adapter()
        adapter2 = get_elasticsearch_adapter()

        self.assertIs(adapter1, adapter2)


if __name__ == '__main__':
    unittest.main(verbosity=2)

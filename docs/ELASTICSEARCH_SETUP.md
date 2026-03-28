# Elasticsearch 설정 가이드

OZ_A2M 보안팀의 감사 로그 중앙 집중 저장소 설정 방법입니다.

## 개요

- **목적**: SQLite + Elasticsearch 하이브리드 모드로 감사 로그 저장
- **SQLite**: 빠른 로컬 캐싱, 오프라인 지원
- **Elasticsearch**: 중앙 집중 저장소, 전문 검색, 장기 보관

## 빠른 시작

### 1. Docker로 Elasticsearch 실행

```bash
cd /home/ozzy-claw/OZ_A2M_new
docker-compose -f docker-compose.elasticsearch.yml up -d
```

### 2. 상태 확인

```bash
# Elasticsearch 상태 확인
curl http://localhost:9200/_cluster/health

# Kibana 접속 (http://localhost:5601)
```

### 3. Python 클라이언트 설치

```bash
pip install elasticsearch
```

## OZ_A2M 통합

### 하이브리드 모드 활성화

```python
from occore.security import init_audit_logger

# Elasticsearch 연동 활성화
audit = init_audit_logger(
    use_elasticsearch=True,
    es_hosts=['localhost:9200']
)

# 로그 기록 (SQLite + Elasticsearch 동시 저장)
audit.log_command(
    user_id='admin',
    ip_address='192.168.1.1',
    command='deploy_strategy',
    result='success',
    risk_score=10
)
```

### Elasticsearch 전용 검색

```python
# 고급 검색 (Elasticsearch)
results = audit.search_logs_elasticsearch(
    query='deploy_strategy',
    hours=24,
    event_type='command'
)

# 이벤트 유형 집계
agg = audit.aggregate_event_types(hours=24)
print(agg)  # {'command': 150, 'access_attempt': 20, ...}

# 브루트 포스 탐지
failed = audit.get_failed_attempts_aggregated(
    hours=1,
    min_attempts=5
)
```

### 통계 확인

```python
stats = audit.get_stats()
print(stats)
# {
#   'sqlite': {'total_logs': 1000, 'today_logs': 50, ...},
#   'elasticsearch': {'connected': True, 'total_documents': 1000, ...}
# }
```

## Kibana 설정

### 1. 인덱스 패턴 생성

1. Kibana 접속: http://localhost:5601
2. Stack Management → Index Patterns
3. Create index pattern
4. Index pattern name: `oz_a2m_audit-*`
5. Timestamp field: `timestamp`

### 2. 대시보드 import

```bash
# 사전 정의된 대시보드 (준비중)
# curl -X POST http://localhost:5601/api/kibana/dashboards/import \
#   -H 'Content-Type: application/json' \
#   -d @docs/kibana/oz_a2m_dashboard.json
```

## 고급 설정

### 커스텀 호스트

```python
# 다중 노드 클러스터
audit = init_audit_logger(
    use_elasticsearch=True,
    es_hosts=[
        'es-node1:9200',
        'es-node2:9200',
        'es-node3:9200'
    ]
)
```

### 인증 설정 (X-Pack)

```python
from elasticsearch import Elasticsearch

es = Elasticsearch(
    ['localhost:9200'],
    basic_auth=('username', 'password')
)
```

## 문제 해결

### 연결 실패

```python
from occore.security import ElasticsearchAuditAdapter

adapter = ElasticsearchAuditAdapter()
if not adapter.connect():
    print("연결 실패 - 다음 확인:")
    print("1. Docker 컨테이너 실행 중: docker ps")
    print("2. 포트 개방: curl http://localhost:9200")
    print("3. pip install elasticsearch 설치됨")
```

### 인덱스 확인

```bash
# 인덱스 목록
curl http://localhost:9200/_cat/indices?v

# 문서 수 확인
curl http://localhost:9200/oz_a2m_audit-*/_count
```

## 성능 최적화

### 인덱스 라이프사이클

```bash
# 30일 후 자동 삭제 설정
curl -X PUT http://localhost:9200/_ilm/policy/oz_a2m_policy \
  -H 'Content-Type: application/json' \
  -d '{
    "policy": {
      "phases": {
        "delete": {
          "min_age": "30d",
          "actions": {
            "delete": {}
          }
        }
      }
    }
  }'
```

### 메모리 설정

```yaml
# docker-compose.elasticsearch.yml
environment:
  - "ES_JAVA_OPTS=-Xms2g -Xmx2g"  # 2GB 힙 메모리
```

## 보안 고려사항

1. **프로덕션 환경**: X-Pack 보안 활성화
2. **TLS/SSL**: 인증서 설정
3. **방화벽**: 9200, 5601 포트 제한
4. **백업**: 스냅샷 정기 저장

## 참고

- [Elasticsearch Python Client](https://elasticsearch-py.readthedocs.io/)
- [Kibana Guide](https://www.elastic.co/guide/en/kibana/current/index.html)
- [OZ_A2M 보안팀 문서](./SECURITY.md)

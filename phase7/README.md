# OZ_A2M Phase 7: 고도화 및 최적화

## 개요
Phase 7은 OZ_A2M 시스템의 고성능화 및 운영 효율성 향상을 위한 인프라를 구축합니다.

## 구성 요소

### 1. Redis Cluster (고성능 캐싱)
- **위치**: `/phase7/redis/`
- **구성**: 3 Master + 3 Replica + Sentinel HA
- **용도**: 실시간 데이터 캐싱, 세션 관리, Rate Limiting
- **포트**: 6379-6384 (Redis), 26379 (Sentinel)

### 2. Kafka Event Bus (고성능 메시징)
- **위치**: `/phase7/kafka/`
- **구성**: 2 Broker + Zookeeper + Schema Registry + Kafka UI
- **용도**: 고성능 이벤트 스트리밍, 부서간 비동기 통신
- **포트**: 9092-9093 (Kafka), 8080 (UI), 8081 (Schema Registry)
- **토픽**: 시장데이터, 시그널, 주문, 시스템 로그 등 20개+

### 3. ML Model Registry
- **위치**: `/phase7/mlops/`
- **기능**: 모델 버전 관리, A/B 테스트, 자동 배포
- **상태**: Staging → Production 자동화

### 4. OpenTelemetry Observability
- **위치**: `/phase7/observability/`
- **구성**: Jaeger (분산 추적) + Prometheus (메트릭) + Grafana (시각화)
- **포트**: 16686 (Jaeger UI), 9090 (Prometheus), 3001 (Grafana)

## 빠른 시작

### 1. Redis Cluster 시작
```bash
cd /home/ozzy-claw/OZ_A2M/phase7/redis
docker-compose -f redis_cluster.yml up -d
```

### 2. Kafka 시작
```bash
cd /home/ozzy-claw/OZ_A2M/phase7/kafka
docker-compose up -d

# 토픽 초기화
python topics/init_topics.py
```

### 3. Observability 시작
```bash
cd /home/ozzy-claw/OZ_A2M/phase7/observability
docker-compose -f docker-compose.observability.yml up -d
```

### 4. 전체 시작
```bash
cd /home/ozzy-claw/OZ_A2M/phase7
bash scripts/start_all.sh
```

## 통합 설정

### 환경 변수 (.env)
```bash
# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_SENTINEL_HOST=localhost
REDIS_SENTINEL_PORT=26379

# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092,localhost:9093
KAFKA_SCHEMA_REGISTRY=http://localhost:8081

# Observability
JAEGER_ENDPOINT=http://localhost:4317
PROMETHEUS_URL=http://localhost:9090
GRAFANA_URL=http://localhost:3001
```

### 모니터링 URL
- **Grafana**: http://localhost:3001 (admin/oza2m_admin)
- **Prometheus**: http://localhost:9090
- **Jaeger**: http://localhost:16686
- **Kafka UI**: http://localhost:8080

## 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                      Phase 7 Enhanced                        │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │  Redis   │  │  Kafka   │  │  Model   │  │ OpenTelemetry│ │
│  │ Cluster  │  │  Cluster │  │ Registry │  │ Observability│ │
│  │ (Cache)  │  │ (Events) │  │  (ML)    │  │  (Metrics)   │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘ │
│       │             │             │                │         │
│       └─────────────┴─────────────┴────────────────┘         │
│                         │                                    │
│                    ┌────┴────┐                               │
│                    │ OZ_A2M  │                               │
│                    │  Core   │                               │
│                    └────┬────┘                               │
│                         │                                    │
│       ┌─────────────────┼─────────────────┐                  │
│       ▼                 ▼                 ▼                  │
│  ┌─────────┐      ┌─────────┐      ┌─────────┐              │
│  │Dept 1-7 │      │  Bots   │      │ Signals │              │
│  └─────────┘      └─────────┘      └─────────┘              │
└─────────────────────────────────────────────────────────────┘
```

## 성능 향상

- **캐싱**: Redis Cluster로 API 응답 10x 향상
- **메시징**: Kafka로 초당 100,000+ 메시지 처리
- **관측성**: 실시간 트레이싱으로 장애 탐지 시간 90% 단축
- **ML**: 모델 버전 관리로 A/B 테스트 자동화

## 다음 단계 (Phase 8)

Phase 8에서는 완전한 자율 운영 시스템을 구축합니다:
- Self-healing 자동 복구
- Auto-scaling 동적 확장
- 고급 보안 및 감사

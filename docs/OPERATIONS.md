# OZ_A2M 운영 가이드

> **버전:** 1.0
> **최종 업데이트:** 2026-03-29

---

## 목차

1. [시스템 개요](#시스템-개요)
2. [시작하기](#시작하기)
3. [일상 운영](#일상-운영)
4. [모니터링](#모니터링)
5. [장애 대응](#장애-대응)
6. [백업 및 복구](#백업-및-복구)

---

## 시스템 개요

### 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                        CEO 대시보드                          │
│                    (Presentation Layer)                      │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐   ┌──────────────────┐   ┌──────────────┐
│  MQTT Broker │   │   Temporal       │   │   Kafka      │
│  (mosquitto) │   │   (Workflow)     │   │  (Events)    │
└──────────────┘   └──────────────────┘   └──────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      7부서 아키텍처                          │
├──────┬──────┬──────┬──────┬──────┬──────┬──────────────────┤
│ D1   │ D2   │ D3   │ D4   │ D5   │ D6   │ D7 (Trading)     │
│관제탑 │검증  │보안  │DevOps│성과  │R&D   │ Trend/MM/Arb    │
└──────┴──────┴──────┴──────┴──────┴──────┴──────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐   ┌──────────────────┐   ┌──────────────┐
│   Ray        │   │   Redis Cluster  │   │Elasticsearch │
│  (RLlib)     │   │  (3M+3R+Sentinel)│   │  (Logs)      │
└──────────────┘   └──────────────────┘   └──────────────┘
```

### 주요 구성 요소

| 구성 요소 | 포트 | 설명 |
|-----------|------|------|
| MQTT | 1883 | 부서 간 메시징 |
| Temporal | 7233 | 워크플로우 오케스트레이션 |
| Kafka | 9092 | 고우선순위 이벤트 |
| Redis Cluster | 6379-6384 | 캐싱 및 상태 관리 |
| Elasticsearch | 9200 | 로그 수집 |
| Ray | 6379 | 분산 컴퓨팅 |

---

## 시작하기

### 1. 전체 시스템 시작

```bash
# 모든 부서 시작
./scripts/start_all_departments.sh

# 특정 부서만 시작
cd department_1 && python3 -m src.main &
cd department_7 && python3 -m src.bot_manager &
```

### 2. Docker 인프라 시작

```bash
# Redis Cluster
cd phase7/redis && docker-compose -f redis_cluster.yml up -d

# 모니터링
docker-compose -f phase4/monitoring/docker-compose.yml up -d
```

### 3. Ray 클러스터 시작

```bash
# 로컬 모드 (개발)
python3 -c "from occore.research.ray_engine import RayEngine; RayEngine().initialize()"

# 분산 클러스터 (운영)
ray start --head --port=6379
ray start --address="<head-node-ip>:6379"
```

---

## 일상 운영

### 봇 관리

```bash
# 봇 상태 확인
python3 -c "from department_7.src.bot_manager import UnifiedBotManager; m = UnifiedBotManager(); print(m.get_all_stats())"

# 특정 봇 시작/중지
curl -X POST http://localhost:8000/bots/trend_following/start
curl -X POST http://localhost:8000/bots/trend_following/stop
```

### RPA 작업 관리

```bash
# RPA 작업 등록
python3 -c "
from occore.operations.rpa import RPAAutomation, AutomationTask
rpa = RPAAutomation()
task = AutomationTask(
    task_id='daily_pnl',
    name='Daily PnL Report',
    task_type='report_download',
    schedule='daily',
    params={'report_type': 'daily_pnl'}
)
rpa.add_task(task)
"

# 즉시 실행
python3 -c "
from occore.operations.rpa import RPAAutomation
rpa = RPAAutomation()
import asyncio
asyncio.run(rpa.execute_task('daily_pnl'))
"
```

### 백테스트 실행

```bash
# 병렬 백테스트
python3 occore/research/ray_engine.py

# 파라미터 최적화
python3 -c "
from occore.research.ray_engine import RayEngine
from ray import tune

engine = RayEngine(num_workers=4)
engine.initialize()

result = engine.optimize_parameters(
    strategy_name='trend_following',
    param_space={
        'ema_fast': tune.choice([5, 10, 15]),
        'ema_slow': tune.choice([30, 50, 100]),
    },
    num_samples=12
)
print(result)
"
```

---

## 모니터링

### 로그 확인

```bash
# 실시간 로그
 tail -f logs/department_*.log

# 특정 부서 로그
 tail -f department_7/logs/bot_manager.log

# Elasticsearch 쿼리
curl -X GET "localhost:9200/oz_a2m/_search?q=level:error"
```

### 메트릭 확인

```bash
# Redis 모니터링
redis-cli -p 6379 info stats

# Ray 클러스터 상태
ray status

# 시스템 리소스
htop  # 또는 docker stats
```

### 알림 설정

```python
# department_4/src/main.py 설정
alert_rules = {
    "cpu_threshold": 80.0,      # CPU 80% 초과 시 알림
    "memory_threshold": 85.0,   # 메모리 85% 초과 시 알림
    "disk_threshold": 90.0,     # 디스크 90% 초과 시 알림
}
```

---

## 장애 대응

### 증상별 대응

| 증상 | 원인 | 조치 |
|------|------|------|
| 봇 응답 없음 | 프로세스 종료 | `./scripts/start_all_departments.sh` |
| Redis 연결 실패 | 클러스터 장애 | `docker-compose -f phase7/redis/redis_cluster.yml restart` |
| Ray 워커 disconnected | 네트워크 문제 | `ray start --address=<head>` 재실행 |
| MQTT 메시지 누락 | 브로커 과부하 | 메시지 큐 크기 확인 및 재시작 |
| 높은 지연시간 | 리소스 부족 | 워커 수 감소 또는 서버 증설 |

### 긴급 중지

```bash
# 모든 봇 긴급 중지
./scripts/stop_all_departments.sh

# Docker 인프라 중지
docker-compose -f phase7/redis/redis_cluster.yml down
docker-compose -f phase4/monitoring/docker-compose.yml down

# Ray 클러스터 중지
ray stop
```

---

## 백업 및 복구

### Redis 백업

```bash
# RDB 백업
redis-cli -p 6379 BGSAVE

# 백업 파일 복사
cp /var/lib/redis/dump.rdb /backup/redis/$(date +%Y%m%d).rdb
```

### 설정 백업

```bash
# 전체 설정 백업
tar -czf backup_$(date +%Y%m%d).tar.gz \
  config/ \
  .env \
  */config/ \
  phase7/redis/config/
```

### 복구 절차

1. Docker 인프라 시작
2. Redis Cluster 복구 (백업 파일 로드)
3. 부서 서비스 순차 시작 (D1 → D7)
4. 봇 상태 확인 및 재시작
5. Ray 클러스터 초기화

---

## 참고 자료

- [BUILD_PROMPTS.md](BUILD_PROMPTS.md) - 구축 단계별 프롬프트
- [CLAUDE.md](../CLAUDE.md) - 개발 가이드
- [API 문서](http://localhost:8000/docs) - FastAPI 자동 생성 문서

# Netdata 설정 가이드

OZ_A2M 유지보수관리센터의 실시간 시스템 모니터링 설정 방법입니다.

## 개요

- **목적**: psutil + Netdata 하이브리드 모드로 실시간 시스템 모니터링
- **psutil**: 로컬 기본 모니터링, 오프라인 지원
- **Netdata**: 실시간 고해상도 모니터링, 알림, 웹 대시보드

## 빠른 시작

### 1. Docker로 Netdata 실행

```bash
cd /home/ozzy-claw/OZ_A2M_new

# Elasticsearch + Netdata 함께 실행
docker-compose -f docker-compose.monitoring.yml up -d

# Netdata만 실행
docker run -d --name=oz_a2m_netdata \
  --pid=host \
  --network=host \
  -v netdata_config:/etc/netdata \
  -v netdata_lib:/var/lib/netdata \
  -v netdata_cache:/var/cache/netdata \
  -v /etc/passwd:/host/etc/passwd:ro \
  -v /etc/group:/host/etc/group:ro \
  -v /proc:/host/proc:ro \
  -v /sys:/host/sys:ro \
  -v /etc/os-release:/host/etc/os-release:ro \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  --cap-add SYS_PTRACE \
  --cap-add SYS_ADMIN \
  --security-opt apparmor=unconfined \
  netdata/netdata:latest
```

### 2. 상태 확인

```bash
# Netdata API 확인
curl http://localhost:19999/api/v1/info

# 웹 대시보드 접속
open http://localhost:19999
```

## OZ_A2M 통합

### HealthChecker에 Netdata 활성화

```python
from occore.devops import init_health_checker

# Netdata 연동 활성화
checker = init_health_checker(
    use_netdata=True,
    netdata_host="localhost:19999"
)

# 시스템 리소스 체크 (Netdata 우선, fallback psutil)
metrics = checker.check_system_resources()
print(f"CPU: {metrics.cpu_percent}%")
print(f"Memory: {metrics.memory_percent}%")

# Netdata 전용 메트릭
netdata_metrics = checker.get_netdata_metrics()
print(netdata_metrics)

# 활성 알림 조회
alarms = checker.get_netdata_alarms()
for alarm in alarms:
    print(f"[{alarm['status']}] {alarm['name']}: {alarm['value']}")

# Netdata 기반 헬스 체크
status, message = checker.check_netdata_health()
print(f"Status: {status}, Message: {message}")
```

### NetdataAdapter 직접 사용

```python
from occore.devops import init_netdata_adapter

# 어댑터 초기화
netdata = init_netdata_adapter("localhost:19999")

# 시스템 메트릭 조회
metrics = netdata.get_system_metrics()
print(f"Load Average: {metrics.get('load_average', 0)}")

# 트레이딩 관련 메트릭
trading = netdata.get_trading_metrics()
print(f"TCP Connections: {trading['network']['tcp_connections']}")
print(f"I/O Wait: {trading['system']['io_wait']}")

# 모든 차트 목록
charts = netdata.get_all_charts()
for chart in charts[:10]:  # 처음 10개만
    print(f"{chart['id']}: {chart['title']}")
```

## 알림 설정

### 1. 기본 알림 활성화

Netdata는 기본적으로 다음 알림을 제공합니다:

- **CPU**: 80% (warning), 90% (critical)
- **Memory**: 80% (warning), 90% (critical)
- **Disk**: 80% (warning), 90% (critical)
- **Network**: 연결 끊김 감지
- **Load**: 5분 평균 기준

### 2. 커스텀 알림 (선택적)

```bash
# 설정 파일 편집
docker exec -it oz_a2m_netdata bash

# /etc/netdata/health.d/ 디렉토리에 알림 규칙 추가
# 예: 트레이딩 지연 알림

cat > /etc/netdata/health.d/oz_a2m_trading.conf << 'EOF'
# OZ_A2M 트레이딩 알림

# API 응답 시간 알림 (사용자 정의 차트 필요)
alarm: oz_a2m_api_latency_high
    on: oz_a2m.api_latency
every: 10s
  calc: $latency
 units: ms
  warn: $this > 100
  crit: $this > 500
  info: OZ_A2M API response time is high
EOF

# Netdata 재시작
docker restart oz_a2m_netdata
```

## 고급 설정

### 원격 Netdata 연결

```python
# 원격 서버의 Netdata 연결
netdata = init_netdata_adapter("remote-server:19999")
```

### 클라우드 연동 (Netdata Cloud)

```bash
# 토큰 설정 후 docker-compose 실행
export NETDATA_CLAIM_TOKEN=your-token
export NETDATA_CLAIM_URL=https://app.netdata.cloud
export NETDATA_CLAIM_ROOMS=your-room-id

docker-compose -f docker-compose.monitoring.yml up -d
```

### 성능 트러블슈팅

```bash
# Netdata 성능 확인
curl http://localhost:19999/api/v1/info | jq ."hosts"."localhost"."mc"

# 메트리커스 수집 간격 조정 (기본: 1초)
# /etc/netdata/netdata.conf에서 [global] 섹션 수정
# update every = 2
```

## 문제 해결

### 연결 실패

```python
from occore.devops import NetdataAdapter

adapter = NetdataAdapter()
if not adapter.connect():
    print("연결 실패 - 다음 확인:")
    print("1. Docker 컨테이너 실행 중: docker ps | grep netdata")
    print("2. 포트 개방: curl http://localhost:19999/api/v1/info")
    print("3. 방화벽 설정: sudo ufw allow 19999/tcp")
```

### 차트 데이터 확인

```bash
# 특정 차트 데이터 조회
curl "http://localhost:19999/api/v1/data?chart=system.cpu&points=10"

# 알림 로그 조회
curl "http://localhost:19999/api/v1/alarm_log?after=-100"
```

## 참고

- [Netdata Documentation](https://learn.netdata.cloud/)
- [Netdata API](https://learn.netdata.cloud/docs/agent/web/api)
- [OZ_A2M DevOps 문서](./DEVOPS.md)

## 모니터링 스택 전체 실행

```bash
# Elasticsearch + Kibana + Netdata 한번에 실행
docker-compose -f docker-compose.monitoring.yml up -d

# 상태 확인
echo "=== Elasticsearch ==="
curl -s http://localhost:9200/_cluster/health | jq .status

echo "=== Kibana ==="
curl -s http://localhost:5601/api/status | jq .status.overall.state

echo "=== Netdata ==="
curl -s http://localhost:19999/api/v1/info | jq ."hosts"."localhost"."hostname"
```

## 대시보드 접속

| 서비스 | URL | 설명 |
|--------|-----|------|
| Netdata | http://localhost:19999 | 실시간 시스템 모니터링 |
| Kibana | http://localhost:5601 | 감사 로그 분석 |
| Elasticsearch | http://localhost:9200 | 검색 API |

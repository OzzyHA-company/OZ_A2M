# Ant-Colony Nest 설정 가이드

## 포트 설정

| 서비스 | 포트 | 설명 |
|--------|------|------|
| Ant-Colony Nest API | 8084 | 봇 등록, 거래 저장, PnL 집계 |
| CEO Dashboard | 8086 | 실시간 대시보드 (원래 8080/8083 사용 중 충돌로 변경) |

## 환경변수

```bash
# Redis (Nest 서버용)
export REDIS_HOST=localhost
export REDIS_PORT=6379

# MQTT
export MQTT_HOST=localhost
export MQTT_PORT=1883

# Nest API URL (대시보드용)
export NEST_API_URL=http://localhost:8084
```

## 실행 순서

```bash
# 1. Redis 실행
redis-server

# 2. MQTT Broker (mosquitto) 실행
mosquitto -c /etc/mosquitto/mosquitto.conf

# 3. Ant-Colony Nest 서버 실행
cd ~/.openclaw/skills/oz-a2m-ant-colony-nest/scripts
python3 nest_core.py

# 4. 봇 실행
cd /home/ozzy-claw/OZ_A2M/department_7/src/bot
python3 run_all_bots.py

# 5. CEO Dashboard 실행
cd /home/ozzy-claw/OZ_A2M/department_1/src
python3 ceo_dashboard_server.py
```

## API 엔드포인트

### Nest API (8084)
- `GET /api/bots` - 모든 봇 상태 조회
- `GET /api/bots/{bot_id}` - 특정 봇 상세 조회
- `GET /api/bots/{bot_id}/trades` - 봇 거래 내역 조회
- `GET /api/aggregate/pnl` - 전체 PnL 집계
- `POST /api/bots/{bot_id}/trade` - 거래 기록
- `POST /api/bots/{bot_id}/status` - 봇 상태 업데이트

### Dashboard API (8086)
- `GET /api/bots` - 봇 목록 (Nest API 우선)
- `GET /api/profit` - 수익 현황 (Nest API 우선)
- `GET /` - 대시보드 HTML

## 연동 현황

| 봇 | 연동 상태 | 파일 |
|---|---|---|
| grid_bot | ✅ 완료 | `department_7/src/bot/grid_bot.py` |
| dca_bot | ✅ 완료 | `department_7/src/bot/dca_bot.py` |
| scalper | ✅ 완료 | `department_7/src/bot/scalper.py` |
| triarb | ❌ 미완료 | - |
| funding | ❌ 미완료 | - |
| hyperliquid | ❌ 미완료 | - |
| polymarket | ❌ 미완료 | - |
| pump_sniper | ❌ 미완료 | - |
| gmgn_copy | ❌ 미완료 | - |
| ibkr_forecast | ❌ 미완료 | - |
| arbitrage | ❌ 미완료 | - |

## 문제 해결

### 포트 충돌
```bash
# 8080/8083 사용 중일 때
lsof -i:8080
fuser -k 8080/tcp

# 또는 대시보드 포트 변경 (ceo_dashboard_server.py)
port=8086  # 변경
```

### Redis 오류
```bash
# Redis 연결 확인
redis-cli ping

# Nest 서버 Redis 에러 시
# - decode_responses=True 확인
# - boolean 값은 str로 변환 필요
```

## 최종 커밋

```
feat: Ant-Colony Nest integration for real-time trading dashboard

- Add Ant-Colony Nest server (port 8084) for centralized bot data aggregation
- Integrate Grid/DCA/Scalper bots with Nest (registration + trade publishing)
- Update CEO dashboard to fetch data from Nest API (port 8086)
```

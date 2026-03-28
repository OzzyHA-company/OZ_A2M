# OZ_A2M 단계별 구축 프롬프트

재부팅 후 각 STEP의 프롬프트를 Claude에 붙여넣기하여 사용한다.
각 단계는 순서대로 진행한다.

---

## 공통 선행 체크 (모든 STEP 시작 전 자동 실행)

```bash
cd /home/ozzy-claw/OZ_A2M
pwd
git status
git log --oneline -5
docker ps -a | grep oz_a2m
df -h / | tail -1
free -h | grep Mem
python3 -m pytest tests/ -v --tb=short -p no:anchorpy 2>&1 | tail -5
```

---

## 공통 완료 체크리스트 (모든 STEP 완료 후 자동 실행)

```bash
# 1. 테스트 전체 통과 확인
python3 -m pytest tests/ -v --tb=short -p no:anchorpy 2>&1 | tail -10

# 2. import 오류 스캔
grep -rn "occore\.logger\|occore\.messaging" --include="*.py" . 2>/dev/null

# 3. Docker 서비스 상태
docker ps --filter "name=oz_a2m" --format "table {{.Names}}\t{{.Status}}"

# 4. Git 저장
git add -A
git status
git commit -m "[STEPX] 완료: <내용 요약>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git push origin main
```

---

---

# STEP 1 — Kafka 가동 + EventBus 실연동

> **붙여넣기용 프롬프트:**

```
OZ_A2M STEP 1을 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]
- git status, docker ps, 테스트 상태 확인

[목표]
1. Phase7 Kafka 컨테이너 가동
   - cd phase7/kafka && docker-compose up -d
   - 브로커 2개 + Zookeeper + Schema Registry 확인

2. lib/messaging/event_bus.py 의 Kafka 연동 실활성화
   - 현재 Kafka import는 되어있지만 실제 미연결 상태
   - Kafka 브로커 연결 테스트 코드 작성 및 실행

3. 토픽 생성 확인
   - market_data, signals, orders, system_logs 토픽 존재 여부 확인
   - 없으면 생성

4. EventBus 통합 테스트 작성
   - tests/test_kafka_eventbus.py 생성
   - HIGH/CRITICAL 이벤트 Kafka 전송 검증

[승인 불필요 — 전부 자동 진행]

[완료 후]
- 공통 완료 체크리스트 실행
- git commit "[STEP 1] Kafka 가동 + EventBus 실연동 완료"
- 완료 보고
```

---

# STEP 2 — 전략 성과 DB + GitHub Actions CI

> **붙여넣기용 프롬프트:**

```
OZ_A2M STEP 2를 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표]
1. 전략 성과 DB 구축 (제6부서 R&D 피드백 루프 핵심)
   - occore/rnd/strategy_db.py 생성
   - 스키마: strategy_id, date, pnl, sharpe, mdd, win_rate, parameters
   - SQLite 기반 (나중에 PostgreSQL 전환 가능하도록 추상화)
   - 일일 분석 루프: 전날 전략 결과 → DB 저장 → 개선 신호 생성

2. occore/rnd/ 에 성과 분석기 연동
   - strategy_evaluator.py: 전략별 성과 순위 계산
   - 최하위 전략 → 폐기 플래그, 최상위 → 강화 플래그

3. GitHub Actions CI 구축
   - .github/workflows/ci.yml 생성
   - 트리거: push to main, PR
   - 스텝: python3 -m pytest tests/ -p no:anchorpy
   - 배지: README.md 에 CI 상태 배지 추가

4. 테스트 작성
   - tests/test_strategy_db.py

[승인 불필요 — 전부 자동 진행]

[완료 후]
- 공통 완료 체크리스트 실행
- git commit "[STEP 2] 전략 성과 DB + GitHub Actions CI 완료"
- 완료 보고
```

---

# STEP 3 — Trend Following 봇 + WebSocket 브릿지

> **붙여넣기용 프롬프트:**

```
OZ_A2M STEP 3을 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표]
1. Trend Following 봇 구현
   - department_7/src/bot/trend_follower.py 생성
   - 전략: EMA 교차 (EMA20 / EMA50), MACD 확인
   - scalper.py 구조 참고하여 동일 BotState 패턴 사용
   - UnifiedBotManager 에 자동 등록

2. WebSocket 브릿지 구현
   - lib/messaging/websocket_bridge.py 생성
   - MQTT 토픽 → WebSocket 실시간 전달
   - FastAPI WebSocket 엔드포인트: /ws/market, /ws/signals, /ws/orders
   - department_1/src/gateway/ 에 통합

3. 봇 관리 API 엔드포인트 추가
   - GET  /bots         - 전체 봇 목록 + 상태
   - POST /bots/{id}/start
   - POST /bots/{id}/stop
   - GET  /bots/{id}/status

4. 테스트 작성
   - tests/test_trend_follower.py
   - tests/test_websocket_bridge.py

[승인 불필요 — 전부 자동 진행]
[주의] 실거래 연동 코드 작성 시 sandbox=True 고정, 실계좌 설정은 .env.example 에만 명시

[완료 후]
- 공통 완료 체크리스트 실행
- git commit "[STEP 3] Trend Following 봇 + WebSocket 브릿지 완료"
- 완료 보고
```

---

# STEP 4 — OpenTelemetry 완전 연동 + Temporal DAG

> **붙여넣기용 프롬프트:**

```
OZ_A2M STEP 4를 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표]
1. OpenTelemetry 패키지 등록 및 연동
   - pyproject.toml 에 opentelemetry-api, opentelemetry-sdk, opentelemetry-exporter-otlp 추가
   - pip install 실행
   - phase7/observability/opentelemetry_setup.py 의 하드코딩 절대경로 제거
   - temporal-dev-grafana-tempo Exited(1) 원인 분석 및 재시작

2. 분산 추적 연동
   - lib/core/ 에 tracer.py 생성
   - FastAPI 요청, MQTT 발행, Kafka 이벤트에 span 추가
   - Jaeger UI (포트 16686) 연동 확인

3. Temporal 워크플로우 OZ_A2M 연동
   - occore/orchestration/ 디렉토리 생성
   - 워크플로우 1개 구현: market_data_pipeline
     - 시장 데이터 수집 → 신호 생성 → 봇 전달 → 결과 저장
   - Temporal Worker 실행 스크립트 생성

4. 테스트 작성
   - tests/test_opentelemetry.py (mock 기반)
   - tests/test_temporal_workflow.py

[승인 불필요 — 전부 자동 진행]

[완료 후]
- 공통 완료 체크리스트 실행
- git commit "[STEP 4] OpenTelemetry 연동 + Temporal DAG 완료"
- 완료 보고
```

---

# STEP 5 — PM4Py 프로세스 마이닝 + LLM 라우팅 고도화

> **붙여넣기용 프롬프트:**

```
OZ_A2M STEP 5를 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표]
1. PM4Py 설치 및 프로세스 마이닝 모듈 구축
   - pip install pm4py
   - occore/analytics/process_mining.py 생성
   - Elasticsearch 이벤트 로그 → PM4Py 변환
   - 병목 탐지: 부서간 평균 처리 시간 측정
   - 일일 리포트 자동 생성 (JSON + 콘솔 출력)

2. 이벤트 로그 수집기 구현
   - occore/analytics/event_logger.py 생성
   - 수집 항목: 작업 시작/완료, API 응답 시간, 오류 발생 시점
   - Elasticsearch 인덱스: oz_a2m_events_YYYY-MM-DD

3. LLM 역할 기반 라우팅 고도화
   - department_1/src/llm_gateway.py 의 라우팅 로직 확장
   - 역할 매핑:
     market_analysis  → [Gemini, Ollama]
     complex_reasoning → [Claude, OpenAI] ← 승인 필요 (키 설정 시)
     quick_response   → [Ollama]
     cost_sensitive   → [Ollama, Gemini]
   - TTLCache 히트율 메트릭 추가

4. 테스트 작성
   - tests/test_process_mining.py
   - tests/test_llm_routing.py

[자동 진행] PM4Py 설치, 코드 구현, Ollama/Gemini 기본 라우팅
[승인 필요] OpenAI/Claude/Gemini 실제 API 키 입력 — 키 입력 단계에서 멈추고 보고

[완료 후]
- 공통 완료 체크리스트 실행
- git commit "[STEP 5] PM4Py 프로세스 마이닝 + LLM 라우팅 고도화 완료"
- 완료 보고
```

---

# STEP 6 — Department 2~6 독립 코드 구현

> **붙여넣기용 프롬프트:**

```
OZ_A2M STEP 6을 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표] 각 부서 디렉토리에 독립 실행 가능한 Python 코드 구현

1. 제2부서 (정보검증분석센터) — department_2/src/
   - verification_pipeline.py: 신호 수신 → 노이즈 필터 → 검증 결과 발행
   - noise_filter.py: RSI/볼린저밴드 기반 이상 신호 제거
   - MQTT 구독: signals/raw → 처리 → signals/verified 발행

2. 제3부서 (보안팀) — department_3/src/
   - main.py: occore/security 모듈을 부서 독립 서비스로 래핑
   - 실행: 위협 모니터 + 감사 로거를 데몬으로 실행

3. 제4부서 (유지보수관리) — department_4/src/
   - main.py: occore/devops 모듈을 부서 독립 서비스로 래핑
   - Netdata + 헬스체커 + 워치독 통합 실행

4. 제5부서 (성과분석팀) — department_5/src/
   - main.py: occore/pnl 모듈을 부서 독립 서비스로 래핑
   - 일일 PnL 계산 + 리포트 생성 스케줄러

5. 제6부서 (연구개발팀) — department_6/src/
   - main.py: occore/rnd + strategy_db 연동
   - 일일 분석 루프: 전략 평가 → 성과 DB 저장 → 개선 신호 생성

6. 통합 실행 스크립트
   - scripts/start_all_departments.sh 생성
   - scripts/stop_all_departments.sh 생성

7. 테스트 작성 (각 부서별)
   - tests/test_dept2_verification.py
   - tests/test_dept6_rnd.py

[승인 불필요 — 전부 자동 진행]

[완료 후]
- 공통 완료 체크리스트 실행
- git commit "[STEP 6] Department 2~6 독립 코드 구현 완료"
- 완료 보고
```

---

# STEP 7 — Market Making + Arbitrage 봇

> **붙여넣기용 프롬프트:**

```
OZ_A2M STEP 7을 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표]
1. Market Making 봇 구현
   - department_7/src/bot/market_maker.py 생성
   - 전략: 오더북 분석 → 양방향 호가 제출
   - 스프레드 계산, 재고 관리 로직
   - sandbox=True 고정

2. Arbitrage 봇 구현
   - department_7/src/bot/arbitrage.py 생성
   - 전략: 거래소 간 가격 차이 탐지
   - ccxt 멀티 거래소 지원
   - sandbox=True 고정

3. UnifiedBotManager 에 두 봇 등록
   - department_7/manager.py 봇 레지스트리에 추가
   - 봇 3종 동시 실행 테스트

4. 봇 성과 추적 연동
   - 각 봇의 PnL → occore/pnl → 전략 성과 DB 자동 기록

5. 테스트 작성
   - tests/test_market_maker.py
   - tests/test_arbitrage.py

[자동 진행] 코드 구현, sandbox 테스트
[승인 필요] 실계좌 API 키 (.env 실제 값) 입력 — 이 단계에서 반드시 멈추고 보고

[완료 후]
- 공통 완료 체크리스트 실행
- git commit "[STEP 7] Market Making + Arbitrage 봇 완료"
- 완료 보고
```

---

# STEP 8 — Ray RLlib 강화학습 + OpenRPA + Redis Cluster

> **붙여넣기용 프롬프트:**

```
OZ_A2M STEP 8을 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표]
1. Ray 설치 및 RLlib 백테스트 병렬화
   - pip install ray[rllib]
   - occore/research/ray_engine.py 생성
   - 전략 백테스트 병렬 실행 (GPU 활용)
   - 최적 파라미터 자동 탐색

2. OpenRPA 연동
   - occore/operations/rpa/ 디렉토리 생성
   - 자동화 시나리오:
     - 반복 주문 조정 스크립트
     - 일일 리포트 자동 다운로드

3. Redis Cluster 전환
   - phase7/redis/redis_cluster.yml 기반으로 클러스터 가동
   - 기존 단일 Redis 연결을 클러스터 연결로 마이그레이션
   - lib/data/redis_client.py 클러스터 모드 지원 추가

4. 최종 통합 테스트
   - 전체 8개 부서 동시 실행 확인
   - MQTT → EventBus → Kafka → 봇 전체 흐름 E2E 테스트

5. 최종 문서화
   - README.md 업데이트 (전체 아키텍처 최신화)
   - docs/OPERATIONS.md 생성 (운영 가이드)

[자동 진행] Ray 설치, 코드 구현, Redis Cluster 구성
[승인 필요] 클라우드 Ray 클러스터 사용 시 — 로컬 GPU만 사용하면 승인 불필요

[완료 후]
- 공통 완료 체크리스트 실행
- python3 -m pytest tests/ -v -p no:anchorpy 2>&1 | tail -15
- git commit "[STEP 8] Ray RLlib + OpenRPA + Redis Cluster 완료 — 전체 시스템 완성"
- git push origin main
- 최종 완료 보고
```

---

## 빠른 참조 — 전체 STEP 순서

| STEP | 내용 | 승인 필요 | 예상 소요 |
|------|------|----------|----------|
| STEP 1 | Kafka 가동 + EventBus 실연동 | 없음 | 1~2시간 |
| STEP 2 | 전략 성과 DB + GitHub Actions CI | 없음 | 1~2시간 |
| STEP 3 | Trend Following 봇 + WebSocket 브릿지 | 없음 | 2~3시간 |
| STEP 4 | OpenTelemetry + Temporal DAG | 없음 | 2~3시간 |
| STEP 5 | PM4Py + LLM 라우팅 고도화 | API 키 입력 시 | 2~3시간 |
| STEP 6 | Department 2~6 독립 코드 | 없음 | 3~4시간 |
| STEP 7 | Market Making + Arbitrage 봇 | 실계좌 키 입력 시 | 2~3시간 |
| STEP 8 | Ray RLlib + OpenRPA + Redis Cluster | 클라우드 사용 시 | 3~4시간 |

---

## 재부팅 후 최초 실행 프롬프트

> 재부팅 직후 아무 STEP도 시작하기 전에 이것을 먼저 붙여넣는다:

```
OZ_A2M 시스템 재부팅 후 상태 점검을 진행한다.

1. 시스템 선행 체크:
cd /home/ozzy-claw/OZ_A2M
git log --oneline -5
docker ps -a | grep -E "oz_a2m|temporal|elastic"
python3 -m pytest tests/ -v --tb=short -p no:anchorpy 2>&1 | tail -10
free -h && df -h /

2. 중단된 컨테이너 확인 후 필요한 것만 재시작:
- oz_a2m_mqtt, oz_a2m_gateway, oz_a2m_bot 은 업데이트 완료 후 재시작
- 이상 있는 컨테이너 로그 확인 및 보고

3. 현재 완료 단계 확인 후 다음 STEP 번호 보고
```

# 03. 부서별 상세 분석

## D1: 관제탑센터 (Control Tower Center)

**위치:** `department_1/src/`

### 현재 구현된 파일
```
department_1/src/
├── main.py                 # FastAPI Gateway
├── llm_gateway.py          # LLM 라우터
├── mqtt_redis_bridge.py    # MQTT-Redis 브리지
├── gateway/
│   └── api_server.py       # API 서버
├── routers/
│   ├── agents.py           # 에이전트 관리
│   ├── market.py           # 시장 데이터
│   └── orders.py           # 주문 관리
├── monitoring/
│   ├── api_monitor.py      # API 모니터링
│   └── log_viewer.py       # 로그 뷰어
└── intel/
    └── intel_collector.py  # 인텔 수집
```

### 기능 현황
| 기능 | 구현 | 상태 | 비고 |
|------|------|------|------|
| FastAPI Gateway | ✅ | 작동 중 | Port 8000 |
| MQTT-Redis Bridge | ✅ | 작동 중 | 양방향 동기화 |
| LLM Gateway | ✅ | 작동 중 | Gemini/Groq/Kimi |
| Agent Registry | ✅ | 작동 중 | Redis 기반 |
| 시장 데이터 API | ✅ | 작동 중 | |
| 주문 API | ✅ | 작동 중 | |
| 인텔 수집 | ⚠️ | 부분 | 뉴스/유튜브/온체인 |
| Elasticsearch | ❌ | 미연동 | 로그 저장 안됨 |

### 문제점
1. **외부 탐색팀(Frontline Scout) 연결 없음**
   - SNS/커뮤니티 데이터 미수집
   - D2로 전달할 비정형 데이터 없음

2. **Elasticsearch 미연동**
   - 로그가 파일로만 저장
   - 중앙 집계 불가

---

## D2: 정보검증분석센터 (Verification & Analysis Center)

**위치:** `department_2/src/`

### 현재 구현된 파일
```
department_2/src/
├── main.py                    # D2 서비스
├── verification_pipeline.py   # 검증 파이프라인
└── noise_filter.py            # 노이즈 필터
```

### 기능 현황
| 기능 | 구현 | 상태 | 비고 |
|------|------|------|------|
| MQTT 수신 | ✅ | 작동 중 | D1 데이터 수신 |
| 검증 파이프라인 | ⚠️ | 부분 | 지표 계산 목업 |
| 신호 발행 | ✅ | 작동 중 | `oz/a2m/signals/verified` |
| Multi-LLM 검증 | ❌ | 미구현 | 단일 로직만 |
| 노이즈 필터링 | ⚠️ | 부분 | 단순 임계값만 |

### 심각한 문제: D7과 연결 안됨

```python
# D2: 검증된 신호 발행
topic = "oz/a2m/signals/verified"

# D7: 봇이 구독하는 토픽
topic = "signals/scalping"  # ← ❌ 다름!
```

**결과:** D2가 아무리 신호를 생산핏도 D7 봇들이 받지 못함

---

## D3: 보안팀 (Security Team)

**위치:** `department_3/src/`

### 현재 구현
- 기본 보안 서비스
- 위협 모니터링 (목업)
- 감사 로깅

### 미구현
- IDS (침입 탐지 시스템)
- API 키 유출 방지
- 방화벽 연동

---

## D4: 데브옵스팀 (DevOps Team)

**위치:** `department_4/src/`

### 현재 구현
- 헬스체크 (30초 간격)
- Netdata 모니터링 연동
- 프로세스 감시

### 미구현
- 자동 복구 (Self-healing)
- 장애 발생 시 자동 재시작
- 롤백 메커니즘

---

## D5: 성과분석팀 (Daily PnL & Strategy Team)

**위치:** `department_5/src/`

### 현재 구현된 파일
```
department_5/src/
├── main.py                   # 성과 분석 서비스
└── performance_tracker.py    # 성과 추적
```

### 기능 현황
| 기능 | 구현 | 상태 | 비고 |
|------|------|------|------|
| PnL 계산 | ✅ | 작동 중 | 5분마다 |
| 일일 리포트 | ✅ | 작동 중 | 자정 실행 |
| 거래 데이터 수신 | ❌ | 미작동 | 토픽 불일치 |
| 위험 메트릭 | ⚠️ | 부분 | 샤프 비율 등 |
| 캘린더 뷰 | ❌ | 미구현 | |

### 심각한 문제: 거래 데이터 못받음

```python
# D5가 구독하는 토픽
await client.subscribe("oz/a2m/trades/executed")

# D7 봇이 발행하는 토픽
topic = f"trades/{self.bot_id}"  # ← ❌ 다름!
```

**결과:** 실제 거래 결과를 D5가 수신하지 못해 PnL 분석이 부정확

---

## D6: 연구개발팀 (R&D Team)

**위치:** `department_6/src/`

### 현재 구현된 파일
```
department_6/src/
├── main.py              # R&D 서비스
└── rnd_with_reward.py   # 보상 시스템
```

### 기능 현황
| 기능 | 구현 | 상태 | 비고 |
|------|------|------|------|
| 전략 평가 | ✅ | 작동 중 | StrategyEvaluator |
| 백테스트 | ✅ | 작동 중 | BacktestEngine |
| 전략 DB | ✅ | 작동 중 | SQLite |
| 개선 신호 발행 | ✅ | 작동 중 | MQTT 발행 |
| **Ray RLlib** | ❌ | **미구현** | README만 존재 |
| **강화학습** | ❌ | **미구현** | |
| D5 리포트 수신 | ❌ | 미구현 | 구독 안함 |

### 심각한 문제: 강화학습 미구현

**README 기획:**
```
Ray RLlib 강화학습
- 병렬 백테스트
- 자동 파라미터 최적화
- 분산 학습
```

**현재 구현:**
```python
# Ray RLlib 관련 코드 없음
# 봇들이 학습하거나 진화하는 로직 없음
```

### 또 다른 문제: 개선 신호 아묏도 안받음

```python
# D6이 발행
topic = f"oz/a2m/bots/{bot_id}/improvement_prompt"

# D7 봇들이 이 토픽 구독 안함 ← ❌
```

---

## D7: 전략실행팀 (Execution Team)

**위치:** `department_7/src/`

### 현재 구현된 파일
```
department_7/src/
├── bot/
│   ├── run_all_bots.py           # 전체 봇 실행기
│   ├── unified_bot_manager.py    # 통합 매니저
│   ├── grid_bot.py               # Grid Bot
│   ├── dca_bot.py                # DCA Bot
│   ├── triangular_arb_bot.py     # Triangular Arb
│   ├── funding_rate_bot.py       # Funding Rate
│   ├── scalper.py                # Scalper
│   ├── hyperliquid_bot.py        # Hyperliquid MM
│   ├── polymarket_bot.py         # Polymarket AI
│   ├── pump_sniper_bot.py        # Pump Sniper
│   ├── copy_trade_bot.py         # GMGN Copy
│   ├── ibkr_forecast_bot.py      # IBKR Forecast
│   ├── arbitrage_bot.py          # Arbitrage
│   ├── market_maker_bot.py       # Market Maker
│   └── trend_follower.py         # Trend Follower
├── dashboard/
│   ├── unified_dashboard.py      # 통합 대시보드
│   └── rpg_dashboard.py          # RPG 대시보드 (미사용)
├── signal_generator.py           # 시그널 생성
├── testnet_validator.py          # 테스트넷 검증
└── withdrawal_automation.py      # 출금 자동화
```

### 11개 봇 현황
| 봇 | 상태 | 문제 |
|----|------|------|
| Grid Binance | ⚠️ 작동 | D2 신호 미수신 |
| DCA Binance | ⚠️ 작동 | D2 신호 미수신 |
| Triangular Arb | ⚠️ 작동 | D2 신호 미수신 |
| Funding Rate | ⚠️ 작동 | D2 신호 미수신 |
| Scalper Bybit | ⚠️ 작동 | D2 신호 미수신 |
| Hyperliquid | 🔴 오류 | Solana 주소 사용 (422 에러) |
| Polymarket | ⚠️ 대기 | 기회 대기 중 |
| Pump Sniper | 🔴 오류 | QuickNode rate limit |
| GMGN Copy | 🔴 오류 | Helius DNS 실패 |
| IBKR Forecast | ✅ Mock | 모의 거래 |

### 심각한 문제들

1. **D2 신호 미수신**
   ```python
   # 봇들이 사용하는 신호
   self._generate_signal()  # ← 자체 생성
   
   # D2가 발행하는 신호
   topic = "oz/a2m/signals/verified"  # ← 구독 안함
   ```

2. **거래 결과 D5 미전송**
   ```python
   # 봇이 발행
   topic = f"trades/{self.bot_id}"
   
   # D5가 기대
   topic = "oz/a2m/trades/executed"  # ← 다름!
   ```

3. **D6 개선 신호 미수신**
   ```python
   # improvement_prompt 토픽 구독 안함
   ```

4. **학습/진화 없음**
   - 모든 봇이 고정 파라미터 사용
   - 거래 결과로 파라미터 조정 없음
   - AI 활용 없음 (단순 if/else 로직)

---

## 부서별 구현 완성도

| 부서 | 완성도 | 핵심 문제 |
|------|--------|-----------|
| D1 | 80% | Elasticsearch 미연동 |
| D2 | 60% | D7 연결 안됨 |
| D3 | 40% | IDS/방화벽 없음 |
| D4 | 70% | 자동 복구 없음 |
| D5 | 50% | 거래 데이터 못받음 |
| D6 | 50% | RLlib 미구현, 피드백 안감 |
| D7 | 70% | 독립 실행, 학습 없음 |

---

## 다음 문서

- `04_data_flow_issues.md` - 데이터 흐름 문제 상세

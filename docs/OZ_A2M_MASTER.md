# OZ_A2M 마스터 설계 문서
**최종 업데이트:** 2026-03-30  
**repo:** https://github.com/OzzyHA-company/OZ_A2M  
**서버:** ozzy-claw-PC (Ubuntu, Tailscale: 100.77.207.113)  
**작업 디렉토리:** `/home/ozzy-claw/OZ_A2M`

---

## 시스템 현황

```
Phase 1~7 + STEP 1~8: 전부 완료 (2026-03-29)
테스트: 267 passed / 0 failed
인프라: Redis Cluster + Kafka + OpenTelemetry + Ray RLlib
```

---

## 핵심 아키텍처 원칙

신규 봇은 독립 Docker 컨테이너 새로 만들지 않는다.
기존 UnifiedBotManager + EventBus 구조에 등록하는 방식으로 구축.

```
봇 등록:   department_7/manager.py
            → UnifiedBotManager.create_and_start_bot()

알림:      department_6/src/notifications/telegram_bot.py
리스크:    occore/operations/risk_controller.py
PnL:       occore/pnl/calculator.py
거래소:    occore/operations/exchange_connector.py
신호생성:  occore/verification/signal_generator.py
AI분석:    occore/control_tower/llm_analyzer.py
```

---

## 지갑 구조

```
Phantom (Solana 전용)
  ├── 메인 지갑     → 기존 솔라나 에어드랍봇 전용 (건드리지 않음)
  ├── 신규 지갑 A   → Hyperliquid 봇 전용
  ├── 신규 지갑 B   → Pump.fun 스나이퍼 전용
  └── 신규 지갑 C   → GMGN 카피트레이딩 전용

MetaMask (EVM 전용)
  └── 신규 지갑     → Polymarket 전용 (Polygon 네트워크)
```

---

## API 준비 현황

| API | 상태 | 용도 |
|-----|------|------|
| Binance API Key/Secret | ✅ | Grid봇, DCA봇, 삼각아비트라지 |
| Bybit API Key/Secret | ✅ | Grid봇, 스캘핑봇, Funding Rate |
| Helius RPC API | ✅ | Pump.fun 스나이퍼, Solana 온체인 |
| IBKR TWS API | ✅ | ForecastTrader MM봇 |
| Gemini API | ✅ | LLM 분석 레이어 |
| Groq API | ✅ | LLM 빠른 추론 |
| Telegram Bot Token | ✅ | 알림 시스템 |
| DART API | ❌ | KIS 공시봇 (나중에) |
| KIS API | ❌ | 한국주식봇 (나중에) |

---

## IBKR Trading Permissions

```
✅ Currency/Forex          → 활성화됨
✅ Forecast and Event Contracts → 활성화됨 (봇-08 즉시 가능)
⏳ Stocks                  → Pending Approval
⏳ Cryptocurrencies        → Pending Approval
```

---

## 자금 배분 계획

### 현재 이동 중인 자금
```
빗썸 → Bybit:   0.361 SOL 전송 중
업비트 → Binance: $65 USDT 전송 중
```

### Bybit 도착 후 배분
```
0.2 SOL  → USDT 스왑 → Bybit 봇 자금
  $10    → Bybit Grid봇 (SOL/USDT)
  $20    → Bybit 스캘핑봇

0.1 SOL  → Phantom B로 출금 (Pump.fun봇)
0.061 SOL → Phantom C로 출금 (GMGN봇)
```

### Binance 도착 후 배분
```
$11  → Grid봇 (BTC/USDT)
$20  → Funding Rate 아비트라지봇
$20  → 삼각 아비트라지봇
$14  → DCA봇
```

---

## 전체 봇 구성 (12개)

---

### 🟢 안정봇 (10개)

---

#### 봇-01: Binance Grid봇
```
전략:   BTC/USDT 그리드 자동 매수·매도
자본:   $11
거래소: Binance
구현:   department_7/config/config.json 수정
        exchange.key/secret 입력
        strategy: "OZGridStrategy" 추가
        dry_run: false 로 변경
운영:   24/7
준비:   ✅ API 있음, 자금 도착 후 즉시
```

#### 봇-02: Binance DCA봇
```
전략:   하락 시 자동 분할매수 → 반등 익절
자본:   $14
거래소: Binance
구현:   occore/operations/templates/trend_following_bot.py 참조
        DCA 로직 추가 후 UnifiedBotManager 등록
운영:   24/7
준비:   ✅ API 있음
```

#### 봇-03: Binance 삼각 아비트라지봇
```
전략:   BTC→ETH→BNB→BTC 가격 불일치 포착
자본:   $20
거래소: Binance
구현:   department_7/src/bot/arbitrage_bot.py 확장
        단일 거래소 삼각 아비트라지 로직 추가
운영:   24/7
준비:   ✅ API 있음
```

#### 봇-04: Funding Rate 아비트라지봇
```
전략:   현물매수 + 선물공매도 → 8시간마다 펀딩비 수취
자본:   $20 (Binance $10 + Bybit $10)
거래소: Binance + Bybit 동시
구현:   department_7/src/bot/arbitrage_bot.py 확장
        펀딩레이트 수집 + 헤지 로직 추가
운영:   24/7
준비:   ✅ 두 거래소 API 모두 있음
```

#### 봇-05: Bybit Grid봇
```
전략:   SOL/USDT 그리드
자본:   $10
거래소: Bybit
구현:   봇-01과 동일 구조, exchange: bybit
운영:   24/7
준비:   ✅ API 있음
```

#### 봇-06: Bybit 스캘핑봇
```
전략:   RSI + MACD 1분봉 0.2~0.5% 반복
자본:   $20
거래소: Bybit
구현:   department_7/src/bot/scalper.py (이미 완성)
        exchange_id = "bybit" 로만 변경
운영:   24/7
준비:   ✅ 코드 완성 + API 있음 → 가장 먼저 가동
```

#### 봇-07: Hyperliquid Market Making봇
```
전략:   DEX 오더북 양방향 호가 → 스프레드 수취
자본:   $20
플랫폼: Hyperliquid (DEX, maker fee 0%)
지갑:   Phantom 신규 지갑 A
구현:   department_7/src/bot/market_maker_bot.py (이미 완성)
        Hyperliquid API 어댑터 추가
운영:   24/7
준비:   🟡 지갑 A에 자금 입금 필요
```

#### 봇-08: IBKR ForecastTrader MM봇
```
전략:   예측시장 양방향 호가 + 연 APY 3.14%
자본:   $10
플랫폼: IBKR ForecastTrader
구현:   department_7/src/bot/market_maker_bot.py 확장
        IBKR TWS API 어댑터 추가
운영:   24/6
준비:   ✅ ForecastTrader 권한 활성화됨
```

#### 봇-09: Polymarket AI 방향성봇
```
전략:   AI 확률 오판 감지 → 역방향 베팅
자본:   $20 USDC
플랫폼: Polymarket (Polygon)
지갑:   MetaMask
구현:   py-clob-client + occore/control_tower/llm_analyzer.py
운영:   24/7
준비:   🟡 USDC 입금 필요 (Binance → MetaMask Polygon)
```

#### 봇-10: KIS + NXT DART 공시봇
```
전략:   호재공시 0.5초 자동매수
자본:   10만원
거래소: 한국투자증권
구현:   DART WebSocket + KIS API 신규 구현
운영:   평일 07:00~20:00
준비:   ❌ KIS 계좌 개설 필요
```

---

### 🔴 도파민봇 (2개)

#### 봇-11: Pump.fun 스나이퍼봇
```
전략:   밈코인 런칭 즉시 자동 스나이핑
자본:   0.1 SOL
체인:   Solana
지갑:   Phantom 신규 지갑 B
구현:   Helius WebSocket + Jito 번들 신규 구현
운영:   24/7
준비:   🟡 지갑 B에 0.1 SOL 입금 필요
```

#### 봇-12: GMGN 스마트머니 카피봇
```
전략:   고수 지갑 자동 복사매매
자본:   0.1 SOL
체인:   Solana
지갑:   Phantom 신규 지갑 C
구현:   Solscan API + GMGN.ai 연동
운영:   24/7
준비:   🟡 지갑 C에 0.1 SOL 입금 필요
```

---

### 💤 패시브 수입 (추가 검토)

```
Binance Earn:        USDT 자동 스테이킹 (연 3~5%)
Bybit Copy Trading:  상위 트레이더 자동 복사
Solana Staking:      jitoSOL 자동 전환 (연 7~10%)
Jupiter DCA:         SOL/USDC 자동 분할매수
Raydium LP봇:        유동성 공급 → 수수료 수취
CEX-DEX 크로스:      Binance vs Solana DEX 가격차 포착
```

---

## .env 입력 항목

```bash
# ─── 거래소 ───────────────────────────────
BINANCE_API_KEY=
BINANCE_API_SECRET=

BYBIT_API_KEY=
BYBIT_API_SECRET=

# ─── Solana ───────────────────────────────
HELIUS_API_KEY=
PHANTOM_WALLET_MAIN=        # 메인 (에어드랍봇용)
PHANTOM_WALLET_A=           # Hyperliquid용
PHANTOM_WALLET_B=           # Pump.fun용
PHANTOM_WALLET_C=           # GMGN용

# ─── 예측시장 ─────────────────────────────
METAMASK_ADDRESS=           # Polymarket용 Polygon
IBKR_ACCOUNT_ID=
IBKR_PORT=7497

# ─── LLM ──────────────────────────────────
GEMINI_API_KEY=
GROQ_API_KEY=
ANTHROPIC_API_KEY=

# ─── 알림 ─────────────────────────────────
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# ─── 인프라 (기존 유지) ───────────────────
MQTT_HOST=localhost
MQTT_PORT=1883
REDIS_HOST=localhost
REDIS_PORT=6379
KAFKA_BOOTSTRAP_SERVERS=localhost:9092,localhost:9093

# ─── 거래 설정 ────────────────────────────
DRY_RUN=false
MAX_POSITION_PCT=0.1
STOP_LOSS_PCT=0.02
TAKE_PROFIT_PCT=0.04
```

---

## 봇 가동 우선순위

```
1순위 (자금 도착 즉시):
  봇-06 Bybit 스캘핑봇     ← ScalpingBot 코드 완성됨
  봇-05 Bybit Grid봇
  봇-01 Binance Grid봇

2순위 (내일):
  봇-04 Funding Rate봇
  봇-03 삼각 아비트라지봇
  봇-02 DCA봇

3순위 (이번 주):
  봇-07 Hyperliquid MM봇
  봇-08 IBKR Forecast봇
  봇-09 Polymarket봇

4순위 (SOL 준비 후):
  봇-11 Pump.fun봇
  봇-12 GMGN봇

5순위 (KIS 계좌 후):
  봇-10 DART 공시봇
```

---

## Claude Code 프롬프트 모음

---

### STEP 9 — Bybit 스캘핑봇 실거래 가동

```
OZ_A2M STEP 9를 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표] Bybit 스캘핑봇 실거래 연동 및 가동

1. .env 파일 확인
   - BYBIT_API_KEY, BYBIT_API_SECRET 입력 확인
   - DRY_RUN=false 확인

2. department_7/src/bot/scalper.py 수정
   - exchange_id = "bybit" 확인
   - sandbox = False 로 변경
   - API 키 .env에서 로드하도록 수정

3. department_7/config/config.json 수정
   - "exchange": {"name": "bybit", "key": "", "secret": ""} 
     → 환경변수에서 로드하도록 수정
   - "dry_run": false
   - "stake_amount": 20 (USDT)
   - "pair_whitelist": ["SOL/USDT", "BTC/USDT"]

4. UnifiedBotManager로 봇 등록 및 가동
   - bot_id: "scalper_bybit_001"
   - bot_type: "scalper"
   - exchange: "bybit"
   - capital: 20.0 USDT

5. Telegram 알림 연동 확인
   - 봇 시작 알림
   - 거래 체결 알림
   - 일일 PnL 알림

6. 테스트
   - 소액($1) 테스트 주문 확인
   - 포지션 진입/청산 로그 확인

[승인 필요] 실거래 API 키 입력, 실제 주문 실행 전 확인

[완료 후]
- git commit "[STEP 9] Bybit 스캘핑봇 실거래 가동"
- 완료 보고
```

---

### STEP 10 — Binance Grid봇 + DCA봇 가동

```
OZ_A2M STEP 10을 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표] Binance Grid봇 + DCA봇 구현 및 가동

1. Grid봇 구현
   - department_7/strategies/ 에 OZGridStrategy.py 생성
   - Freqtrade 기반 그리드 전략
   - BTC/USDT, 그리드 간격 0.5%, 총 20개 주문
   - 자본: $11

2. DCA봇 구현
   - department_7/src/bot/ 에 dca_bot.py 생성
   - 하락 시 자동 분할매수 로직
   - 트리거: 가격 -2% 마다 추가 매수
   - 자본: $14

3. 두 봇 UnifiedBotManager 등록
   - bot_type: "grid", "dca" 추가

4. config.json
   - BINANCE_API_KEY/SECRET 환경변수 로드
   - dry_run: false

[승인 필요] 실거래 API 키, 실제 주문 전 확인

[완료 후]
- git commit "[STEP 10] Binance Grid봇 + DCA봇 가동"
- 완료 보고
```

---

### STEP 11 — Funding Rate + 삼각 아비트라지봇

```
OZ_A2M STEP 11을 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표] Funding Rate 아비트라지봇 + 삼각 아비트라지봇 구현

1. Funding Rate봇 구현
   - department_7/src/bot/arbitrage_bot.py 확장
   - funding_rate_bot.py 신규 생성
   - Binance 선물 + Bybit 선물 펀딩레이트 수집
   - 양수 펀딩레이트: 현물 매수 + 선물 공매도
   - 음수 펀딩레이트: 현물 공매도 + 선물 매수
   - 8시간마다 펀딩비 수취 확인
   - 자본: $20 (Binance $10 + Bybit $10)

2. 삼각 아비트라지봇 구현
   - triangular_arb_bot.py 신규 생성
   - Binance 내 BTC→ETH→BNB→BTC 경로
   - 수익률 0.1% 이상일 때만 실행
   - 수수료 계산 포함
   - 자본: $20

3. 두 봇 UnifiedBotManager 등록

[승인 필요] 실거래 API 키, 레버리지 설정 확인

[완료 후]
- git commit "[STEP 11] Funding Rate + 삼각 아비트라지봇"
- 완료 보고
```

---

### STEP 12 — Hyperliquid MM봇 + IBKR ForecastTrader봇

```
OZ_A2M STEP 12를 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표] Hyperliquid MM봇 + IBKR ForecastTrader봇 구현

1. Hyperliquid 어댑터 구현
   - occore/operations/ 에 hyperliquid_adapter.py 생성
   - Phantom 지갑 A 연동
   - hyperliquid-python-sdk 설치
   - MarketMakerBot에 Hyperliquid 거래소 옵션 추가
   - 자본: $20
   - maker fee 0% 확인

2. IBKR ForecastTrader 어댑터 구현
   - occore/operations/ 에 ibkr_forecast_adapter.py 생성
   - ib_insync 라이브러리 활용
   - TWS API 포트 7497 연결
   - ForecastTrader 마켓 데이터 수집
   - 양방향 호가 제출 로직
   - 자본: $10

3. 두 봇 UnifiedBotManager 등록

[승인 필요] IBKR 실계좌 연결, Phantom 지갑 프라이빗 키 입력

[완료 후]
- git commit "[STEP 12] Hyperliquid MM봇 + IBKR ForecastTrader봇"
- 완료 보고
```

---

### STEP 13 — Polymarket AI봇

```
OZ_A2M STEP 13을 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표] Polymarket AI 방향성봇 구현

1. py-clob-client 설치
   - pip3 install py-clob-client --break-system-packages

2. Polymarket 봇 구현
   - department_7/src/bot/polymarket_bot.py 생성
   - MetaMask 지갑 연동 (Polygon)
   - 마켓 데이터 수집 → Gemini/Groq 분석
   - AI 예측 확률 vs 시장 가격 괴리 탐지
   - 괴리 5% 이상 시 자동 베팅
   - Kelly Criterion 포지션 사이징
   - 자본: $20 USDC

3. occore/control_tower/llm_analyzer.py 연동
   - 기존 LLM 분석 파이프라인 활용

4. UnifiedBotManager 등록

[승인 필요] MetaMask 프라이빗 키, USDC 입금 확인

[완료 후]
- git commit "[STEP 13] Polymarket AI봇 구현"
- 완료 보고
```

---

### STEP 14 — Pump.fun 스나이퍼 + GMGN 카피봇

```
OZ_A2M STEP 14를 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표] Pump.fun 스나이퍼봇 + GMGN 카피트레이딩봇 구현

1. Pump.fun 스나이퍼봇
   - department_7/src/bot/pump_sniper_bot.py 생성
   - Helius WebSocket으로 신규 토큰 런칭 감지
   - Jito 번들로 빠른 트랜잭션
   - Phantom 지갑 B 연동
   - 자본: 0.1 SOL
   - 자동 익절: 2~5배
   - 자동 손절: -50%

2. GMGN 카피트레이딩봇
   - department_7/src/bot/copy_trade_bot.py 생성
   - Solscan API로 스마트머니 지갑 추적
   - 지갑 트랜잭션 감지 → 자동 복사
   - Phantom 지갑 C 연동
   - 자본: 0.1 SOL

3. 두 봇 UnifiedBotManager 등록
4. Telegram 알림: 스나이핑 성공/실패, 복사 거래 알림

[승인 필요] Phantom 프라이빗 키 입력, SOL 입금 확인

[완료 후]
- git commit "[STEP 14] Pump.fun 스나이퍼 + GMGN 카피봇"
- 완료 보고
```

---

### STEP 15 — TradingAgents 멀티LLM 신호 레이어

```
OZ_A2M STEP 15를 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표] TradingAgents 프레임워크를 제2부서 신호 생성기에 연결

1. TradingAgents 설치
   - pip3 install tradingagents --break-system-packages
   - 또는 git clone TauricResearch/TradingAgents

2. 멀티LLM 신호 생성기 구현
   - occore/verification/signal_generator.py 확장
   - TradingAgents 7개 에이전트 파이프라인 연결:
     기본분석가 → 감성분석가 → 뉴스분석가
     → 기술분석가 → 연구원 → 트레이더 → 리스크매니저
   - 기존 단순 Groq 판단 → TradingAgents 앙상블로 업그레이드
   - 결과 신호 → 제7부서 봇들에게 전달

3. LLM 설정
   - GEMINI_API_KEY → Gemini 2.5 Flash (분석)
   - GROQ_API_KEY → Llama (빠른 추론)
   - ANTHROPIC_API_KEY → Claude (복잡한 판단)

4. 적용 봇: 스캘핑봇, DCA봇, ForecastTrader봇

[완료 후]
- git commit "[STEP 15] TradingAgents 멀티LLM 신호 레이어"
- 완료 보고
```

---

### STEP 16 — Ray RLlib 전략 자동 진화 루프

```
OZ_A2M STEP 16을 진행한다. /home/ozzy-claw/OZ_A2M 에서 작업한다.

[공통 선행 체크 실행]

[목표] Freqtrade + Ray RLlib 연결 → 봇이 매일 밤 스스로 진화

1. 자동 진화 파이프라인 구현
   - Freqtrade 백테스트 결과 수집
   - occore/research/ray_engine.py (이미 있음) 연동
   - GPU 병렬 파라미터 최적화
   - 최적 전략 자동 배포 (Freqtrade live)
   - 제5부서 PnL → 다시 Ray에 피드백

2. 스케줄링
   - 매일 새벽 2시 자동 실행
   - cron 또는 Airflow 스케줄러

3. 결과 리포트
   - 최적 파라미터 변경사항 Telegram 알림
   - 전략 성과 DB 자동 업데이트

[완료 후]
- git commit "[STEP 16] Ray RLlib 전략 자동 진화 루프"
- 완료 보고
```

---

## 알려진 이슈

```
python → python3 사용
pytest → python3 -m pytest tests/ -v -p no:anchorpy
pip    → pip3 install --break-system-packages
import occore.logger → lib.core.logger 로 수정
import occore.messaging → lib.messaging 으로 수정
Gateway unhealthy → Docker exec 격리 이슈, 외부 접근은 정상
```

---

## 재부팅 후 최초 실행 프롬프트

```
OZ_A2M 시스템 재부팅 후 상태 점검을 진행한다.

1. 선행 체크:
cd /home/ozzy-claw/OZ_A2M
git log --oneline -5
docker ps -a | grep -E "oz_a2m|temporal|elastic|kafka|redis"
python3 -m pytest tests/ -v --tb=short -p no:anchorpy 2>&1 | tail -10
free -h && df -h /

2. 가동 중인 봇 상태 확인:
- UnifiedBotManager 봇 목록 조회
- 각 봇 PnL 확인
- Telegram 알림 정상 작동 확인

3. 현재 완료 단계 확인 후 다음 STEP 보고
```

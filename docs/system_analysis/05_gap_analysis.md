# 05. 기획 의도 vs 현재 구현 차이점

## README.md 기획 의도

### 7부서 아키텍처 기획
```
D1 관제탑센터 (Control Tower Center)
└── 목적: 모든 정형/비정형 데이터 중앙 수집, 단일 통합 전황판 정제

D2 정보검증분석센터 (Verification & Analysis Center)
└── 목적: 관제탑 데이터 분석, 노이즈 필터링, '명확한 매매 지시서(Signal)' 생산

D3 보안팀 (Security Team)
└── 목적: 외부 해킹 방어, API/키 유출 방지, 승인되지 않은 접속 방어

D4 유지보수관리센터 (DevOps & Monitoring Center)
└── 목적: AI 에이전트 및 API 상태 실시간 감시, 오류/업데이트 관리

D5 일일 성과분석 대책개선팀 (Daily PnL & Strategy Team)
└── 목적: 에이전트별 수익률(PnL) 팩트 기반 분석 및 진단

D6 연구개발팀 (R&D & Evolution Team)
└── 목적: 성과분석팀 피드백 기반 신규 시장 로직 설계, 시스템 통합 업데이트

D7 전략실행팀 (Execution Team)
└── 목적: Market Maker, Arbitrage Bot 실행, Unified Bot Manager
```

### Ray RLlib 강화학습 기획
```
Ray RLlib 강화학습
├── 병렬 백테스트 - GPU 활용 다중 전략 동시 테스트
├── 자동 파라미터 최적화 - Grid Search, Random Search, Ray Tune 통합
└── 분산 학습 - Ray Cluster 기반 확장 가능한 학습 인프라
```

---

## 현재 구현 vs 기획 비교

### 데이터 흐름

| 단계 | 기획 의도 | 현재 구현 | 상태 |
|------|-----------|-----------|------|
| 1. D1 수집 | 모든 데이터 중앙 수집 | 일부 시장 데이터만 수집 | ⚠️ 부분 |
| 2. D1→D2 | 검증을 위해 데이터 전달 | MQTT로 전달됨 | ✅ 정상 |
| 3. D2 검증 | 노이즈 필터링, Signal 생산 | 검증 로직 목업 | ⚠️ 부분 |
| 4. D2→D7 | 검증된 Signal 전달 | **토픽 불일치로 전달 안됨** | 🔴 **심각** |
| 5. D7 실행 | Signal 기반 매매 실행 | **자체 신호만 사용** | 🔴 **심각** |
| 6. D7→D5 | 거래 결과 전달 | **토픽 불일치로 전달 안됨** | 🔴 **심각** |
| 7. D5 분석 | PnL 분석 | 목업 데이터로 분석 | 🔴 **심각** |
| 8. D5→D6 | 분석 결과 전달 | **D6가 구독 안함** | 🔴 **심각** |
| 9. D6 개선 | 전략 개선, 신규 로직 설계 | 분석만 하고 피드백 안감 | 🔴 **심각** |
| 10. D6→D1/D7 | 개선사항 적용 | **수신 로직 없음** | 🔴 **심각** |
| 11. 외부탐색 | SNS/커뮤니티 데이터 수집 | **미구현** | 🟡 누락 |
| 12. 강화학습 | Ray RLlib 연동 | **코드 없음** | 🔴 **심각** |

### 핵심 누락 기능

| 기능 | 기획 | 현재 | 위치 |
|------|------|------|------|
| **AI 트레이닝 자동화** | ✅ 필수 | ❌ 없음 | 전체 |
| **봇 학습/진화** | ✅ 필수 | ❌ 없음 | D7 |
| **강화학습 (Ray RLlib)** | ✅ 명시 | ❌ 없음 | D6 |
| **D2 검증 Signal 사용** | ✅ 설계 | ❌ 안씀 | D2→D7 |
| **거래 결과 피드백** | ✅ 설계 | ❌ 안감 | D7→D5→D6 |
| **외부 탐색팀 연결** | ✅ 설계 | ❌ 없음 | D1 |
| **자동 파라미터 최적화** | ✅ 명시 | ❌ 없음 | D6 |
| **Multi-LLM 앙상블 검증** | ✅ 암시 | ❌ 단일 | D2 |

---

## 뇌없는 깡통 거래 봇 문제

### 현재 봇 동작 방식
```python
# department_7/src/bot/grid_bot.py
async def run(self):
    while self.running:
        # 1. 현재가 조회 (거래소 API)
        ticker = await self.exchange.fetch_ticker(self.symbol)
        current_price = ticker['last']
        
        # 2. 고정된 그리드 로직
        for level in self.grid_levels:
            if current_price <= level.price and not level.filled:
                # 3. 매수 주문
                await self._place_buy_order(level)
            elif current_price >= level.price and level.filled:
                # 4. 매도 주문
                await self._place_sell_order(level)
        
        # 5. 대기 (학습/개선 없음)
        await asyncio.sleep(1)
```

### 기획 의도 방식 (뇌있는 봇)
```python
# 기획되었으나 구현 안됨
async def run(self):
    while self.running:
        # 1. D2의 검증된 Signal 수신
        signal = await self._receive_verified_signal()
        
        # 2. LLM 기반 의사결정
        decision = await self._llm_decide(signal)
        
        # 3. 거래 실행
        if decision.should_trade:
            await self._execute_trade(decision)
        
        # 4. 거래 결과로 학습
        await self._learn_from_result()
        
        # 5. D6 피드백 수신 및 적용
        feedback = await self._receive_feedback()
        await self._apply_improvement(feedback)
```

---

## 차이점 요약

| 항목 | 기획 | 현재 | 결과 |
|------|------|------|------|
| **아키텍처** | 7부서 순환 구조 | D7만 독립 실행 | 파이프라인 없음 |
| **AI 활용** | LLM 의사결정 | 고정 if/else | 뇌 없음 |
| **학습** | 거래 결과로 개선 | 학습 없음 | 정첩 |
| **데이터 흐름** | D1→D2→D7→D5→D6→D1 | 각자 놈 | 연결 끊어짐 |
| **강화학습** | Ray RLlib | 미구현 | AI 미활용 |

---

## 다음 문서

- `06_recommendations.md` - 수정 권장사항

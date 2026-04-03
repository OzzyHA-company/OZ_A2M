# 06. 수정 권장사항

## 사용자 검토용

**이 문서는 사용자가 직접 검토하고 수정 방향을 결정하기 위한 것입니다.**

---

## 핵심 질문 (사용자 결정 필요)

### Q1. AI 트레이닝 자동화를 구현할 것인가?

**현재:** 봇들이 고정 전략만 사용 (뇌없음)  
**선택지:**
- **A.** Ray RLlib 강화학습 구현 (복잡, 시간 소요)
- **B.** LLM 기반 의사결정 연동 (중간)
- **C.** D2 검증 Signal만 연결 (간단)
- **D.** 현재 상태 유지 (수정 안함)

### Q2. D2→D7 연결을 어떻게 할 것인가?

**현재:** 토픽 불일치로 연결 안됨  
**선택지:**
- **A.** D7 봇들이 D2 토픽 구독하도록 수정
- **B.** D2가 D7 토픽 형식으로 발행하도록 수정
- **C.** 새로운 표준 토픽 정의하고 양쪽 모두 수정

### Q3. D7→D5→D6→D1 피드백 루프를 구현할 것인가?

**현재:** 끊어져 있음  
**선택지:**
- **A.** 전체 피드백 루프 구현 (복잡)
- **B.** D7→D5만 연결 (PnL 분석용)
- **C.** 구현하지 않음

### Q4. 11개 봇 중 어떤 봇을 유지할 것인가?

**현재:** 11개 모두 실행 중 (일부는 오류)  
**선택지:**
- **A.** 모두 유지하고 문제만 수정
- **B.** 핵심 봇만 남기고 나머지 제거
- **C.** 전부 폐기하고 새로 설계

---

## 기술적 수정안 (참고용)

### 수정 우선순위 (제안)

| 우선순위 | 항목 | 예상 시간 | 영향 |
|----------|------|-----------|------|
| P0 | MQTT 토픽 표준화 | 2시간 | 모든 부서 |
| P0 | D2→D7 연결 | 2시간 | 봇 Signal 수신 |
| P1 | D7→D5 연결 | 1시간 | PnL 분석 |
| P1 | Hyperliquid 주소 수정 | 30분 | 봇 1개 |
| P2 | D5→D6 연결 | 1시간 | R&D 피드백 |
| P2 | D6→D7 피드백 | 2시간 | 봇 개선 |
| P3 | Ray RLlib 구현 | 1주일 | AI 학습 |
| P3 | 외부 탐색팀 연결 | 3일 | 데이터 다양성 |

### 파일 수정 목록 (예상)

```
# P0: MQTT 토픽 표준화
lib/messaging/mqtt_topics.py (신규)
department_2/src/main.py (수정)
department_7/src/bot/grid_bot.py (수정)
department_7/src/bot/dca_bot.py (수정)
department_7/src/bot/scalper.py (수정)
# ... 모든 봇

# P0: D2→D7 연결
department_7/src/bot/base_bot.py (신규 - 공통 Signal 수신)
department_7/src/bot/grid_bot.py (수정)
# ... 모든 봇

# P1: D7→D5 연결
department_7/src/bot/base_bot.py (수정 - 표준 토픽 발행)
department_5/src/main.py (수정 - 표준 토픽 수신)

# P1: Hyperliquid 수정
department_7/src/bot/hyperliquid_bot.py (수정)
  - PHANTOM_WALLET_A → METAMASK_ADDRESS

# P2: D5→D6 연결
department_6/src/main.py (수정)

# P2: D6→D7 피드백
department_7/src/bot/base_bot.py (수정)
# ... 모든 봇

# P3: Ray RLlib
department_6/src/rl_training.py (신규)
department_7/src/bot/base_bot.py (수정 - 학습 로직)
```

---

## 대안 시나리오

### 시나리오 A: 최소 수정 (빠른 결과)

**수정:**
1. MQTT 토픽만 표준화 (D2→D7 연결)
2. Hyperliquid 주소 수정

**결과:**
- 봇들이 D2 Signal 수신 가능
- 기본적인 데이터 흐름 복원
- AI 학습 없음 (깡통 봇 유지)

**소요:** 4시간

---

### 시나리오 B: 중간 수정 (권장)

**수정:**
1. MQTT 토픽 표준화
2. D2→D7 연결
3. D7→D5 연결
4. D5→D6 연결
5. D6→D7 피드백
6. Hyperliquid 주소 수정

**결과:**
- 7부서 연결 완료
- 피드백 루프 작동
- 봇이 거래 결과로 개선 가능
- AI 강화학습 없음

**소요:** 2일

---

### 시나리오 C: 전면 수정 (완전한 AI 시스템)

**수정:**
1. 시나리오 B 전체
2. Ray RLlib 강화학습 구현
3. LLM 기반 의사결정 연동
4. 외부 탐색팀 연결
5. Multi-LLM 앙상블 검증

**결과:**
- 진정한 AI 트레이닝 자동화
- 봇이 스스로 학습하고 진화
- 기획 의도 100% 달성

**소요:** 2주

---

## 사용자 결정 요청

**사용자님, 다음을 결정해주세요:**

1. **어떤 시나리오**를 선택하시겠습니까? (A/B/C/직접)
2. **어떤 봇**을 유지/폐기할까요?
3. **AI 학습**은 구현할까요?

**결정 후 즉시 수정 시작하겠습니다.**

---

## 문서 목록

1. `01_executive_summary.md` - 핵심 결론
2. `02_architecture_current.md` - 현재 아키텍처
3. `03_department_analysis.md` - 부서별 분석
4. `04_data_flow_issues.md` - 데이터 흐름 문제
5. `05_gap_analysis.md` - 기획 vs 현재 차이
6. `06_recommendations.md` - 본 문서

**모든 문서 작성 완료. GitHub 푸시 준비됨.**

# OZ_A2M

![CI](https://github.com/veveenv/OZ_A2M/actions/workflows/ci.yml/badge.svg)

# [Project] OZ_A2M (AI Agent to Market) Core Architecture
**소속:** OzzyHA_company (Human + AI)
**총괄 최고경영자(CEO):** Ozzy
**목표:** 주식, 코인, 비표준/신흥 시장의 데이터 수집, 검증, 매매, 피드백을 100% 자동화하는 퀀트 AI 에이전트 생태계 구축.

## 🖥️ 통합 프론트엔드: CEO 중앙 대시보드 (Presentation Layer)
* **역할:** 아래 7개 백엔드 부서가 생산하는 모든 데이터와 로그를 시각화하고, CEO의 수동 통제(전체재시동, 시스템최적화, 긴급 킬 스위치, 손실 한도 설정)를 각 부서로 전달하는 웹 기반 GUI.
* **아키텍처 원칙:** 모든 7개 부서 에이전트는 독립적으로 백그라운드에서 가동되며, 대시보드(프론트엔드)와는 철저히 API 또는 웹소켓으로만 데이터를 주고받는다 (Decoupled Architecture).

## ⚙️ 파이프라인 및 부서별 핵심 지침 (Backend Departments)

### 1. 제1부서: 관제탑센터 (Control Tower Center)
* **목적:** 모든 정형 데이터(금융 API, 호가창)와 외부 탐색 에이전트가 물어온 비정형 데이터를 중앙으로 수집하여, 단일 통합 전황판으로 정제함. (대시보드에 실시간 데이터 수집 상태 보고)

### 2. 제2부서: 정보검증분석센터 (Verification & Analysis Center)
* **목적:** 관제탑이 넘겨준 상황판(가동 활용에 필요한 데이터)을 분석하여 노이즈를 필터링하고, 각 실전 매매 에이전트가 실행할 '명확한 매매 지시서(Signal)'를 생산함.

### 3. 제3부서: 보안팀 (Security & Gatekeeper Team)
* **목적:** 전체 시스템에 대한 외부 해킹 방어(API, 각 종 key, 비밀번호 외부 유출 방지), 외부 접속 시도, 승인 나지 않은 접속 방어 및 보안유지 관리.

### 4. 제4부서: 유지보수관리센터 (DevOps & Monitoring Center)
* **목적:** 전체 AI 에이전트와 API의 물리적/소프트웨어적 상태를 실시간 감시. (대시보드의 '시스템 탭'에 서버 리소스 및 프로세스 상태 전송), 각 센터와 부서의 상태, 현황, 가동봇에 대한 오류, 이상, 업데이트 유지보수. 

### 5. 제5부서: 일일 성과분석 대책개선팀 (Daily PnL & Strategy Team)
* **목적:** 하루 장 마감 후 에이전트별 수익률(PnL)을 팩트 기반으로 분석 및 진단. (대시보드의 '캘린더/수익 탭'에 시각화 데이터 전송)

### 6. 제6부서: 연구개발팀 (R&D & Evolution Team)
* **목적:** 성과분석팀의 피드백을 기반으로 신규 시장 로직 설계 및 기존 시스템 통합 업데이트 패치 배포.

### * 부록: 외부 탐색팀 (Frontline Scout)
* **목적:** 외부 커뮤니티, SNS 등의 언더그라운드 이슈를 능동 수집하여 2번 정보검증분석센터 단방향 주입함.

---

## 7부서 아키텍처 완성 (STEP 8)

### 제7부서: 전략실행팀 (Execution Team)
* **Market Maker Bot** - 오더북 기반 동적 호가 조정, 인벤토리 스큐 관리
* **Arbitrage Bot** - 거래소 간 가격 차이 실시간 탐지 및 실행
* **Unified Bot Manager** - 3종 봇 동시 실행 및 모니터링

### Ray RLlib 강화학습
* **병렬 백테스트** - GPU 활용 다중 전략 동시 테스트
* **자동 파라미터 최적화** - Grid Search, Random Search, Ray Tune 통합
* **분산 학습** - Ray Cluster 기반 확장 가능한 학습 인프라

### OpenRPA 자동화
* **반복 주문 조정** - 스프레드 벗어난 주문 자동 재배치
* **일일 리포트 다운로드** - PnL 리포트 자동 생성 및 저장
* **스케줄 기반 실행** - cron 스타일 작업 스케줄링

### Redis Cluster
* **고가용성 캐싱** - 3 Master + 3 Replica + Sentinel 구성
* **자동 페일오버** - Sentinel 기반 장애 감지 및 복구
* **Prometheus 모니터링** - Redis Exporter 메트릭 수집

---

## External Libraries (skills/libs/)

### Trading Engines
- **Freqtrade** - 암호화폐 트레이딩 봇
- **Hummingbot** - 암호화폐 트레이딩 엔진
- **QLib** - 퀀트 연구 플랫폼 (Microsoft)
- **VectorBT** - 백테스팅 및 분석

### Workflow & Orchestration
- **Temporal** - 워크플로우 오케스트레이션
- **CrewAI** - 멀티 에이전트 시스템
- **Ray** - 분산 컴퓨팅 + RLlib 강화학습
- **Airflow** - 워크플로우 스케줄링

### Data & AI
- **yFinance** - 금융 데이터 수집
- **VADER** - 감성 분석
- **PM4Py** - 프로세스 마이닝

### Monitoring & Observability
- **Netdata** - 시스템 모니터링
- **Grafana** - 시각화 대시보드
- **Sentry** - 에러 모니터링
- **OpenTelemetry** - 관측성 플랫폼

### Integration
- **OpenClaw** - 52개 스킬 라이브러리
- **Pi-Mono** - 7개 패키지 개발 플랫폼
- **OpenRPA** - 업무 자동화

### Security & Testing
- **Nuclei** - 보안 스캐닝
- **Hey** - HTTP 부하 테스트
- **TradingAgents** - AI 트레이딩 에이전트

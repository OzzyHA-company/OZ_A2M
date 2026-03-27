---
name: oz-a2m
description: OZ_A2M (AI Agent to Market) 프로젝트 개발 가이드. 7부서 아키텍처(관제탑, 검증분석, 보안, 유지보수, 성과분석, R&D, 데이터소스)를 활용한 자동화 트레이딩 시스템 구축 시 사용. OZ_A2M, 트레이딩 봇, 퀀트 시스템, 7부서 아키텍처 언급 시 필수 참조.
---

# OZ_A2M (AI Agent to Market) 개발 스킬

## 프로젝트 개요

**OZ_A2M**은 주식, 코인, 비표준/신흥 시장의 데이터 수집, 검증, 매매, 피드백을 100% 자동화하는 퀀트 AI 에이전트 생태계입니다.

- **소속**: OzzyHA_company (Human + AI)
- **총괄**: Ozzy
- **목표**: 완전 자동화된 트레이딩 시스템 구축

---

## 7부서 아키텍처

### 제1부서: 관제탑센터 (Control Tower Center)
**경로**: `occore/control_tower/`

**역할**: 모든 정형/비정형 데이터 중앙 수집 및 통합 전황판 생성

**주요 컴포넌트**:
- `collector.py` - 데이터 수집 엔진
- `situation_board.py` - 통합 전황판
- `exchange_adapter.py` - 거래소 API 어댑터
- `normalizer.py` - 데이터 정규화
- `alert_manager.py` - 알림 관리
- `llm_analyzer.py` - LLM 기반 데이터 분석

**개발 가이드라인**:
- 모든 데이터는 단일 통합 형식으로 정규화
- 실시간 스트리밍 데이터 처리 지원
- 외부 데이터소스는 단방향 주입만 허용

---

### 제2부서: 정보검증분석센터 (Verification & Analysis Center)
**경로**: `occore/verification/`

**역할**: 데이터 분석, 노이즈 필터링, 명확한 매매 신호 생성

**주요 컴포넌트**:
- `verification_pipeline.py` - 검증 파이프라인
- `signal_generator.py` - 매매 신호 생성
- `noise_filter.py` - 노이즈 필터링
- `reality_check.py` - 현실성 검증
- `indicators.py` - 기술적 지표
- `models.py` - 데이터 모델

**개발 가이드라인**:
- 모든 신호는 reality check 통과 필요
- 다중 timeframe 분석 지원
- 가짜 신호 필터링 우선순위 최상위

---

### 제3부서: 보안팀 (Security & Gatekeeper Team)
**경로**: `occore/security/`

**역할**: 외부 해킹 방어, API 키 보호, 접근 통제, 감사 로깅

**주요 컴포넌트**:
- `threat_monitor.py` - 위협 모니터링
- `vault.py` - 보안 자격증명 관리
- `acl.py` - 접근 제어 목록
- `audit.py` - 감사 로깅
- `elasticsearch_adapter.py` - Elasticsearch 연동

**개발 가이드라인**:
- 모든 API 키는 vault를 통해서만 접근
- 모든 보안 이벤트는 Elasticsearch에 로깅
- 비인가 접근 시도는 자동 차단 및 알림

---

### 제4부서: 유지보수관리센터 (DevOps & Monitoring Center)
**경로**: `occore/devops/`

**역할**: 시스템 상태 실시간 감시, 자동 복구, 성능 모니터링

**주요 컴포넌트**:
- `health_checker.py` - 헬스 체크
- `watchdog.py` - 와치독 모니터링
- `diagnoser.py` - 자동 진단
- `healer.py` - 자동 복구
- `netdata_adapter.py` - Netdata 연동
- `repair_log.py` - 수리 로그

**개발 가이드라인**:
- 모든 서비스는 주기적 헬스 체크 필수
- 장애 발생 시 자동 복구 우선 시도
- 복구 불가 시 알림 및 로깅

---

### 제5부서: 일일 성과분석 대책개선팀 (Daily PnL & Strategy Team)
**경로**: `occore/pnl/`

**역할**: 에이전트별 수익률 분석, 전략 개선 제안

**주요 컴포넌트**:
- `calculator.py` - PnL 계산기
- `report.py` - 리포트 생성
- `performance.py` - 성과 분석
- `models.py` - 데이터 모델

**개발 가이드라인**:
- 매일 장 마감 후 자동 분석 실행
- 팩트 기반 분석 (감정 배제)
- 개선점은 구체적이고 실행 가능해야 함

---

### 제6부서: 연구개발팀 (R&D & Evolution Team)
**경로**: `occore/rnd/`

**역할**: 신규 전략 설계, 백테스팅, 시스템 통합 업데이트

**주요 컴포넌트**:
- `strategy_generator.py` - 전략 생성
- `backtest_engine.py` - 백테스트 엔진
- `qlib_adapter.py` - Qlib 연동

**개발 가이드라인**:
- 모든 전략은 백테스트 통과 필요
- 실제 거래 데이터 기반 피드백 반영
- 버전 관리 및 롤백 기능 필수

---

### 외부 탐색팀 (Frontline Scout)
**경로**: `occore/data_sources/`

**역할**: 외부 커뮤니티, SNS 등 언더그라운드 이슈 수집

**주요 컴포넌트**:
- `news_collector.py` - 뉴스 수집
- `openbb_adapter.py` - OpenBB 연동
- `data_router.py` - 데이터 라우팅

**개발 가이드라인**:
- 검증센터로 단방향 주입만 허용
- 소스별 신뢰도 가중치 적용
- 실시간성과 정확성 균형 유지

---

## 통합 인프라

### Docker Compose 설정

**Elasticsearch** (`docker-compose.elasticsearch.yml`):
- 데이터 저장 및 검색
- 보안 로그 중앙화

**Monitoring** (`docker-compose.monitoring.yml`):
- Netdata 시스템 모니터링
- 실시간 성능 메트릭

### 테스트 구조
**경로**: `tests/`

- `test_control_tower.py`
- `test_verification.py`
- `test_security_team.py`
- `test_devops.py`
- `test_pnl.py`
- `test_elasticsearch_audit.py`
- `test_netdata.py`

---

## 개발 워크플로우

### 새로운 기능 추가 시

1. **해당 부서 폴터에 모듈 생성**
2. **단위 테스트 작성** (`tests/test_*.py`)
3. **통합 테스트 실행**
4. **문서화 업데이트** (`docs/`)

### 코드 스타일

- Python 3.12+
- Type hints 필수
- Docstrings Google 스타일
- 비동기 처리 (`asyncio`) 우선

---

## 참고 리소스 (libs/)

스킬의 `libs/` 폴더에 참고용 레포지토리가 클론되어 있습니다:

| 레포지토리 | 용도 |
|-----------|------|
| `freqtrade/` | 암호화폐 트레이딩 봇 |
| `nuclei/` | 보안 스캐닝 |
| `netdata/` | 시스템 모니터링 |
| `pm4py/` | 프로세스 마이닝 |
| `TradingAgents/` | AI 트레이딩 에이전트 |

---

## 중요 개념

### Decoupled Architecture
- 모든 7개 부서는 독립적으로 백그라운드 실행
- 대시보드와 API/WebSocket으로만 통신
- 부서 간 직접 의존성 금지

### Reality Check
- 모든 거래 신호는 현실성 검증 필요
- 시장 유동성, 슬리피지 고려
- 과거 데이터와 실시간 데이터 차이 인지

### Security First
- 모든 외부 통신은 암호화
- API 키는 환경변수 또는 vault 사용
- 모든 접근은 감사 로그에 기록

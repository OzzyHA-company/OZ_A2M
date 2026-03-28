---
name: OZ_A2M Skills Deployment
description: OZ_A2M 7부서 시스템에 배포된 스킬 구성 및 매핑 정보
type: project
---

# OZ_A2M Phase 5 전 스킬 배포 현황

**배포일**: 2026-03-28
**총 스킬 수**: 12개
**부서 적용**: 7개 부서 전체

---

## 설치된 스킬 목록

### 1. 기존 스킬 (6개)
| 스킬명 | 버전 | 용도 | 안전성 |
|--------|------|------|--------|
| `csrf-protection` | - | CSRF 보호 | High |
| `monitoring-observability` | - | 모니터링/관찰성 | High |
| `redis-best-practices` | - | Redis 모범 사례 | High |
| `security-audit-logging` | - | 보안 감사 로깅 | High |
| `skills-security-check` | - | 스킬 보안 검사 | High |
| `find-skills` | - | 스킬 검색/설치 도우미 | High |

### 2. 신규 설치 스킬 (5개)
| 스킬명 | 소스 | 설치 수 | 용도 | 안전성 |
|--------|------|---------|------|--------|
| `fastapi-python` | mindrally/skills | 4.3K | FastAPI 개발 패턴 | High |
| `sqlalchemy-orm` | bobmatnyc/claude-mpm-skills | 537 | DB ORM 패턴 | High |
| `playwright-testing` | alinaqi/claude-bootstrap | 467 | E2E 테스트 자동화 | High |
| `elasticsearch-esql` | elastic/agent-skills | 279 | ESQL 쿼리 작성 | High |
| `github-workflow-automation` | sickn33/antigravity-awesome-skills | 776 | GitHub Actions 자동화 | High |

### 3. pi-skills (badlogic) - brave-search 제외 (7개)
| 스킬명 | 경로 | 용도 |
|--------|------|------|
| `browser-tools` | ~/pi-skills/browser-tools/ | 브라우저 자동화 (CDP) |
| `gccli` | ~/pi-skills/gccli/ | Google Calendar CLI |
| `gdcli` | ~/pi-skills/gdcli/ | Google Drive CLI |
| `gmcli` | ~/pi-skills/gmcli/ | Gmail CLI |
| `transcribe` | ~/pi-skills/transcribe/ | 음성-텍스트 변환 |
| `vscode` | ~/pi-skills/vscode/ | VSCode 통합 |
| `youtube-transcript` | ~/pi-skills/youtube-transcript/ | 유튜브 자막 추출 |

---

## 7부서 스킬 매핑

### 제1부서: 관제탑센터 (Control Tower Center)
**적용 스킬**:
- `fastapi-python` - API 서버 개발
- `sqlalchemy-orm` - 데이터 모델링
- `elasticsearch-esql` - 데이터 검색/쿼리
- `playwright-testing` - 통합 테스트
- `monitoring-observability` - 시스템 모니터링

**적용 모듈**:
- `collector.py` - fastapi-python, sqlalchemy-orm
- `situation_board.py` - elasticsearch-esql
- `exchange_adapter.py` - playwright-testing (API 테스트)
- `normalizer.py` - sqlalchemy-orm

### 제2부서: 정보검증분석센터 (Verification & Analysis Center)
**적용 스킬**:
- `fastapi-python` - 분석 API 개발
- `sqlalchemy-orm` - 분석 결과 저장
- `playwright-testing` - 신호 검증 테스트
- `browser-tools` - 웹 데이터 수집

**적용 모듈**:
- `verification_pipeline.py` - fastapi-python
- `signal_generator.py` - sqlalchemy-orm
- `noise_filter.py` - playwright-testing
- `reality_check.py` - browser-tools

### 제3부서: 보안팀 (Security & Gatekeeper Team)
**적용 스킬**:
- `security-audit-logging` - 감사 로깅
- `elasticsearch-esql` - 보안 로그 분석
- `csrf-protection` - CSRF 보호
- `skills-security-check` - 스킬 보안 검사

**적용 모듈**:
- `threat_monitor.py` - security-audit-logging, elasticsearch-esql
- `vault.py` - security-audit-logging
- `audit.py` - elasticsearch-esql
- `elasticsearch_adapter.py` - elasticsearch-esql

### 제4부서: 유지보수관리센터 (DevOps & Monitoring Center)
**적용 스킬**:
- `monitoring-observability` - 시스템 모니터링
- `redis-best-practices` - 캐싱/세션 관리
- `github-workflow-automation` - CI/CD 자동화
- `playwright-testing` - 헬스체크 테스트

**적용 모듈**:
- `health_checker.py` - monitoring-observability, playwright-testing
- `watchdog.py` - monitoring-observability
- `diagnoser.py` - redis-best-practices
- `netdata_adapter.py` - monitoring-observability

### 제5부서: 일일 성과분석 대책개선팀 (Daily PnL & Strategy Team)
**적용 스킬**:
- `fastapi-python` - PnL API 개발
- `sqlalchemy-orm` - 성과 데이터 모델링
- `elasticsearch-esql` - 성과 쿼리 분석
- `youtube-transcript` - 교육 자료 수집

**적용 모듈**:
- `calculator.py` - fastapi-python, sqlalchemy-orm
- `report.py` - elasticsearch-esql
- `performance.py` - sqlalchemy-orm

### 제6부서: 연구개발팀 (R&D & Evolution Team)
**적용 스킬**:
- `fastapi-python` - 전략 API 개발
- `playwright-testing` - 전략 검증 테스트
- `github-workflow-automation` - 버전 관리 자동화
- `transcribe` - 음성 회의록 변환
- `browser-tools` - 리서치 데이터 수집

**적용 모듈**:
- `strategy_generator.py` - fastapi-python, browser-tools
- `backtest_engine.py` - playwright-testing
- `qlib_adapter.py` - fastapi-python

### 외부 탐색팀 (Frontline Scout)
**적용 스킬**:
- `browser-tools` - 웹 데이터 수집
- `youtube-transcript` - 유튜브 정보 수집
- `gccli/gmcli/gdcli` - 외부 데이터 연동

**적용 모듈**:
- `news_collector.py` - browser-tools, youtube-transcript
- `openbb_adapter.py` - browser-tools
- `data_router.py` - gccli, gdcli

---

## 외부 도구 통합

### pi-mono (badlogic/pi-mono)
**설치 위치**: `/home/ozzy-claw/pi-mono/`
**패키지**:
- `agent` - @mariozechner/pi-agent-core
- `ai` - @mariozechner/pi-ai
- `coding-agent` - 코딩 에이전트
- `mom` - 메모리/상태 관리
- `pods` - 컨테이너/파드 관리
- `tui` - 터미널 UI
- `web-ui` - 웹 인터페이스

**적용 부서**: 모든 부서 (특히 R&D, DevOps)

### openclaw
**설치 위치**: `/home/ozzy-claw/openclaw/` (VENIDIO-PLUGINS), `/home/ozzy-claw/openclaw-official/` (official)
**스킬**: 52개 내장 (discord, github, notion, obsidian 등)

**적용 부서**:
- `github` - 제4부서 (CI/CD), 제6부서 (R&D)
- `discord` - 제1부서 (알림), 제3부서 (보안 알림)
- `notion/obsidian` - 제5부서 (문서화), 제6부서 (R&D)

### clawhub
**설치 위치**: `/home/ozzy-claw/clawhub/`
**설정**: `~/.config/clawhub/config.json`
**용도**: 스킬 레지스트리 관리

---

## 저장소 연동

### GitHub Repositories
| 저장소 | 위치 | 용도 |
|--------|------|------|
| `badlogic/pi-mono` | /home/ozzy-claw/pi-mono/ | 모노레포 패키지 |
| `badlogic/pi-skills` | /home/ozzy-claw/pi-skills/ | 개인 스킬 |
| `openclaw/openclaw` | /home/ozzy-claw/openclaw-official/ | 공식 openclaw |
| `openclaw/clawhub` | /home/ozzy-claw/clawhub/ | 스킬 레지스트리 |
| `VENIDIO-PLUGINS/openclaw` | /home/ozzy-claw/openclaw/ | 확장 openclaw |

---

## Phase 5 준비 완료 항목

- [x] badlogic/pi-skills 설치 (brave-search 제외)
- [x] badlogic/pi-mono 확인 (이미 설치됨)
- [x] openclaw/openclaw 클론
- [x] openclaw/clawhub 클론
- [x] npx skills 5개 설치
- [x] 7부서 스킬 매핑 완료
- [x] 외부 도구 통합 확인

**다음 단계**: Phase 5 구축 시작

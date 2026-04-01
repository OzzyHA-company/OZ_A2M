# pi-mono Configuration

## Overview
pi-mono + Gemini Pro + Ant-Colony 설정

## Components
- **Gemini Pro**: 메인 LLM (뇌)
- **Ant-Colony**: 다중 에이전트 스웜 인텔리전스
  - Queen: 전략 수립
  - Scouts: 기회 탐색
  - Workers: 병렬 실행
  - Soldiers: 검증/리스크 관리

## Session Management
- 세션 자동 갱신: `~/.openclaw/skills/oz-pi-gemini-saas/`
- 만료일: 7일
- 갱신 스크립트: `scripts/run_with_xvfb.sh`

## Architecture
```
Jito Shredstream → pi-mono (Gemini+Ant-Colony) → Jito Block Engine
```

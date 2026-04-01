---
name: oz-pi-gemini-saas
description: "Gemini Advanced SaaS 세션 자동 갱신 - Google 계정으로 로그인하고 pi-mono 설정에 세션 쿠키를 업데이트합니다"
metadata:
  openclaw:
    emoji: "🔐"
    requires:
      bins: ["python3"]
      env: ["OZ_GEMINI_EMAIL"]
      config: ["pi_mono_config_path"]
    install:
      - id: "playwright"
        kind: "pip"
        package: "playwright"
        bins: ["playwright"]
      - id: "cryptography"
        kind: "pip"
        package: "cryptography"
        bins: []
      - id: "playwright-chromium"
        kind: "script"
        command: "python3 -m playwright install chromium"
---

# OZ-PI Gemini SaaS Re-Authenticator

Gemini Advanced SaaS 세션을 자동으로 갱신하는 OpenClaw 커스텀 스킬입니다.

## 기능

- Google 계정(ozzyclaw9085@gmail.com)으로 Gemini Advanced에 자동 로그인
- 세션 쿠키 추출 및 pi-mono 설정 파일 자동 업데이트
- 암호화된 비밀번호 저장 (AES-256)
- 세션 만료 전 자동 알림

## 사용법

### 기본 실행
```bash
/oz-pi-gemini-saas
```

### 옵션
```bash
# Headless 모드로 실행
/oz-pi-gemini-saas --headless

# 커스텀 설정 경로 지정
/oz-pi-gemini-saas --config-path /custom/path/config.json

# 비밀번호 재설정
/oz-pi-gemini-saas --reset-password
```

## 사전 준비사항

1. **환경변수 설정**
   ```bash
   export OZ_GEMINI_EMAIL="ozzyclaw9085@gmail.com"
   ```

2. **비밀번호 암호화 저장**
   ```bash
   # 최초 1회 실행
   python3 ~/.openclaw/skills/oz-pi-gemini-saas/scripts/setup_password.py
   ```

3. **pi-mono 설정 확인**
   - 기본 경로: `~/.pi-mono/config.json`
   - 스킬이 자동으로 설정 파일을 업데이트합니다

## 동작 흐름

1. Playwright로 Chrome 브라우저 실행
2. Google 로그인 페이지로 이동
3. 이메일/비밀번호 자동 입력
4. Gemini Advanced 페이지로 이동
5. 세션 쿠키 추출 (`__Secure-1PSID`, `__Secure-1PSIDTS`, 등)
6. pi-mono 설정 파일 업데이트
7. 백업 파일 생성

## 추출되는 쿠키

- `__Secure-1PSID` - 메인 세션 ID
- `__Secure-1PSIDTS` - 타임스탬프
- `__Secure-1PSIDCC` - 크로스 사이트 쿠키
- `SID`, `SSID`, `APISID`, `SAPISID` - Google 세션 쿠키

## 세션 유효기간

- Gemini SaaS 세션: 약 7일
- 만료 24시간 전 재인증 권장
- 스킬 실행 시 자동으로 만료 시간 계산 및 표시

## 문제 해결

### 로그인 실패 시
- `--headless=false` 옵션으로 실행하여 브라우저 확인
- `~/.openclaw/skills/oz-pi-gemini-saas/debug/` 디렉토리의 스크린샷 확인

### 2FA 요청 시
- 수동으로 2FA 완료 후 세션 유지
- 다음 실행부터는 2FA 없이 자동 로그인

### 쿠키 추출 실패 시
- Gemini 페이지가 완전히 로드될 때까지 대기 시간 증가
- 네트워크 연결 확인

## 보안

- 비밀번호는 AES-256으로 암호화하여 저장
- 쿠키 파일은 600 권한으로 저장
- 모든 민감 정보는 로그에 기록되지 않음
- 설정 파일 변경 시 자동 백업 생성

## 파일 구조

```
~/.openclaw/skills/oz-pi-gemini-saas/
├── SKILL.md                    # 이 파일
├── scripts/
│   ├── auth_gemini.py         # 메인 인증 스크립트
│   ├── cookie_extractor.py    # 쿠키 추출 유틸리티
│   ├── update_config.py       # 설정 업데이터
│   ├── crypto_utils.py        # 암호화 유틸리티
│   └── setup_password.py      # 비밀번호 설정 스크립트
└── references/
    └── GOOGLE_AUTH_FLOW.md    # Google 인증 플로우 문서
```

## 참고

- 이 스킬은 OpenClaw의 브라우저 자동화 기능을 사용합니다
- Playwright와 Chromium이 필요합니다
- Google 계정의 보안 설정에서 "신뢰할 수 있는 기기"로 등록 권장

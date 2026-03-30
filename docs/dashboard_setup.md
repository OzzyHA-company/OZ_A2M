# OZ_A2M CEO Dashboard Setup Guide

## 개요

OZ_A2M CEO Dashboard는 13개 트레이딩 봇을 실시간으로 모니터링하고 제어하는 웹 기반 대시보드입니다.

## 주요 기능

### 1. 종합현황 (Overview)
- 총 포트폴리오 가치
- 오늘 수익 / 누적 수익
- 출금 가능 금액
- 가동 봇 수
- 14일 수익 추이 차트
- 거래소별 잔액

### 2. 안정봇 (Stable Bots)
- 8개 안정봇 개별 모니터링
- 봇별 수익 추이 차트 (색상 구분)
- 그리드, DCA, 아비트라지, 펀딩비 등

### 3. 도파민봇 (Dopamine Bots)
- 3개 고위험/고수익 봇 모니터링
- 네온 테마 차트
- 스나이핑, 마켓메이킹 등

### 4. 출금/현금화
- 출금 가능 금액 확인
- 거래소별 출금 기능
- 출금 히스토리

### 5. 시스템
- 실시간 시스템 메트릭스 (CPU/RAM/Disk/Docker)
- API 사용량 모니터링
- 시스템 제어 (최적화, Auto 수리)

### 6. AI 분석
- 봇 성과 AI 평가
- 개선 제안
- 시장 감성 지표

## 설치 및 실행

### 1. 환경 변수 설정

```bash
# API Keys
export BINANCE_API_KEY="your_key"
export BINANCE_API_SECRET="your_secret"
export BYBIT_API_KEY="your_key"
export BYBIT_API_SECRET="your_secret"

# Telegram
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# QuickNode (Pump.fun)
export QUICKNODE_HTTP_URL="https://..."
export QUICKNODE_WSS_URL="wss://..."

# MetaMask (Polymarket)
export METAMASK_ADDRESS="0x..."
export METAMASK_PRIVATE_KEY="0x..."
export POLYMARKET_API_KEY="..."
export POLYMARKET_API_SECRET="..."
export POLYMARKET_API_PASSPHRASE="..."
```

### 2. 서버 실행

```bash
cd /home/ozzy-claw/OZ_A2M
python3 -m department_1.src.ceo_dashboard_server
```

서버는 기본적으로 `http://0.0.0.0:8082`에서 실행됩니다.

### 3. 접속

- 로컬: http://localhost:8082
- Tailscale: http://100.77.207.113:8082

## API 엔드포인트

### 봇 관리
- `GET /api/status` - 시스템 전체 상태
- `GET /api/bots` - 모든 봇 상태
- `GET /api/bot/{id}/status` - 특정 봇 상세
- `POST /api/bot/{id}/{action}` - 봇 제어 (start/stop)

### 거래소
- `GET /api/exchange-balances` - 거래소별 잔액
- `POST /api/withdraw` - 출금 요청

### 수익/AI
- `GET /api/profit` - 수익 현황
- `GET /api/ai-analysis` - AI 분석 리포트

### 시스템
- `GET /api/api-usage` - API 사용량
- `POST /api/system/optimize` - 시스템 최적화
- `POST /api/killswitch` - 긴급 킬스위치

### 로그
- `GET /api/logs` - 로그 파일 목록
- `GET /api/logs/{filename}` - 로그 내용
- `POST /api/logs/rotate` - 로그 로테이션
- `GET /api/errors` - 에러 로그

## WebSocket

실시간 업데이트를 위해 WebSocket을 사용합니다.

```javascript
const ws = new WebSocket('ws://localhost:8082/ws');

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    // data.type: 'bot_status', 'system_metrics', 'exchange_balances'
};
```

## TUI 대시보드 (CLI)

터미널에서 실행 가능한 TUI 버전:

```bash
python3 -m department_1.src.tui_dashboard
```

## 문제 해결

### 포트 충돌
```bash
# 사용 중인 포트 확인
sudo lsof -i :8082
# 프로세스 종료
sudo kill -9 <PID>
```

### 봇 연결 실패
- API 키 확인
- 환경 변수 설정 확인
- 로그 확인: `tail -f logs/dashboard.log`

### WebSocket 재연결
자동 재연결되지 않을 경우 페이지 새로고침

## 보안

- 모든 API 키는 환경 변수로 관리
- `.env` 파일은 `.gitignore`에 포함
- 외부 접속 시 Tailscale VPN 사용 권장

## 업데이트 로그

### Phase 1 (2026-03-31)
- 실시간 데이터 연결 구현
- 13개 봇 연동
- WebSocket 브로드캐스트

### Phase 2 (2026-03-31)
- 봇별 차트 구현
- AI 분석 리포트
- 색상 테마 적용

### Phase 3 (2026-03-31)
- API 모니터링
- 로그 뷰어
- 시스템 관리 기능

### Phase 4 (2026-03-31)
- TUI 대시보드 개선
- 문서화
- 통합 테스트

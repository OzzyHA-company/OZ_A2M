# OZ_A2M — Claude 자동화 행동 지침

## 기본 원칙

- 한국어로 보고한다
- 작업 디렉토리는 항상 `/home/ozzy-claw/OZ_A2M`
- 각 단계는 `docs/BUILD_PROMPTS.md` 의 순서를 따른다

---

## 자동 진행 항목 (승인 불필요)

- 코드 작성 / 수정 / 삭제
- Python 패키지 설치 (`pip install`)
- Docker 컨테이너 시작 / 중지 / 재시작
- 테스트 실행 및 오류 수정
- 설정 파일 구조 생성 (`.env.example`, `docker-compose.yml` 등 템플릿)
- `git add / commit / push`
- 로그 확인 및 진단

---

## 승인 필요 항목 (반드시 사용자 확인 후 진행)

- `.env` 파일에 실제 API 키 / 시크릿 값 입력
- 거래소 실계좌 연동 (Binance, Bybit 등 실거래 설정)
- 실 자금 관련 모든 설정 (주문 수량, 레버리지, 리스크 한도)
- Telegram / Discord / 이메일 봇 토큰 입력
- 클라우드 서비스 인증 (AWS, GCP, GitHub Secrets 등)
- 외부 유료 API 연동 (OpenAI, Gemini 등 실제 키 사용)

---

## 시스템 환경 상수

```
python3          # python 명령 없음
pytest 옵션      # python3 -m pytest tests/ -v --tb=short -p no:anchorpy
pip 설치         # pip3 install <패키지> --break-system-packages (필요시)
GPU              # NVIDIA 8GB VRAM
RAM              # 32GB (25GB 여유)
디스크           # 915GB (779GB 여유)
```

---

## 알려진 이슈 (재발 방지)

| 이슈 | 해결책 |
|------|--------|
| `python` 명령 없음 | `python3` 사용 |
| anchorpy pytest 충돌 | `-p no:anchorpy` 옵션 필수 |
| venv pip 없음 | 시스템 pip3 사용 |
| `occore.logger` import 오류 | `lib.core.logger` 로 수정 |
| `occore.messaging` import 오류 | `lib.messaging` 으로 수정 |
| Gateway unhealthy | Docker exec 격리 이슈 — 외부 접근은 정상 |

---

## 단계 진행 규칙

1. 각 단계 시작 전 **공통 선행 체크** 실행
2. 검증 실패 → 자동 수정 → 재검증 (최대 3회)
3. 3회 실패 시 → 원인 보고 후 계속 (블로커가 아닌 경우)
4. **승인 필요 항목 도달 시 → 즉시 멈추고 사용자에게 보고**
5. 단계 완료 조건 → 검증 체크리스트 전항목 통과
6. 단계 완료 후 → `git commit + push` → 완료 보고

---

## 현재 진행 상태 (2026-03-30 기준)

- OZ_A2M Phase 1~6 + STEP 1~17: **전부 완료 🎉**
- **완결판 구축 완료 - 전체 봇 11개 + CEO 대시보드 + TradingAgents 완성**
- 테스트: 267+ passed / 32+ passed (신규 테스트)
- 최신 커밋: 완결판

### 완성된 봇 11개

| 번호 | 봇 이름 | 거래소 | 심볼 | 자본 | 상태 |
|------|---------|--------|------|------|------|
| 봇-01 | Binance Grid | Binance | BTC/USDT | $11 | ✅ |
| 봇-02 | Binance DCA | Binance | BTC/USDT | $14 | ✅ |
| 봇-03 | Triangular Arb | Binance | BTC/ETH/BNB | $20 | ✅ |
| 봇-04 | Funding Rate | Binance+Bybit | Multi | $20 | ✅ |
| 봇-05 | Bybit Scalping | Bybit | SOL/USDT | $20 | ✅ |
| 봇-06 | Hyperliquid MM | Hyperliquid | SOL-PERP | $20 | ✅ |
| 봇-07 | IBKR Forecast | Interactive Brokers | AAPL/MSFT | $10 | ✅ |
| 봇-08 | Polymarket AI | Polymarket | Multi | $20 | ✅ |
| 봇-09 | Pump.fun Sniper | Solana | New Tokens | 0.1 SOL | ✅ |
| 봇-10 | GMGN Copy | Solana | Smart Money | 0.1 SOL | ✅ |

### CEO 대시보드
- 안정봇 패널 (다크 테마)
- 도파민봇 패널 (네온 테마)
- 킬스위치
- 실시간 WebSocket 업데이트
- Tailscale: http://100.77.207.113:8080

### TradingAgents 통합
- 7개 AI 에이전트 앙상블
- Groq → Multi-LLM 업그레이드

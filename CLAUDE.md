# OZ_A2M — Claude 자동화 행동 지침

## 기본 원칙

- 한국어로 보고한다
- 작업 디렉토리는 항상 `/home/ozzy-claw/OZ_A2M`
- 각 단계는 `docs/BUILD_PROMPTS.md` 의 순서를 따른다

---

## 세션 시작 시 필수 확인 (무조건 실행)

**모든 세션 시작 전 (ozkimi, ozcode, cc 등 모두 해당):**

```bash
# 1. 중앙 비밀 저장소 확인
cat ~/.ozzy-secrets/master.env | head -20

# 2. 메모리 파일 확인
read /home/ozzy-claw/.claude/projects/-home-ozzy-claw/memory/SHARED_CONTEXT.md
read /home/ozzy-claw/.claude/projects/-home-ozzy-claw/memory/LAST_SESSION.json

# 3. 환경변수 로드 확인
env | grep -E "(BINANCE|BYBIT|PHANTOM|METAMASK|TELEGRAM)" | wc -l
```

**⚠️ 이 파일들을 읽지 않고는 절대 작업 시작하지 않는다.**

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

## 물리적 시스템 정보

**Ubuntu 컴퓨터 특성:**
- **안정성**: 시스템 이상 없을 시 재부팅 거의 없음
- **접근 방식**: SSH 원격 접속만 사용 (물리적 조작 없음)
- **사용자 접속**: MacBook에서 SSH 연결하여 구축/실행/수리 명령
- **네트워크**: 동일 네트워크 또는 외부에서 SSH 접속

**접속 정보:**
- **낭북 IP**: 192.168.51.28 (고정)
- **외부 접속**: Tailscale VPN 권장 (100.77.207.113)

---

## 중앙 비밀 저장소 (Critical)

**위치:** `~/.ozzy-secrets/master.env`
**권한:** 600 (본인만 읽기)
**설명:** 모든 API 키, 지갑 주소, 비밀키가 저장된 중앙 저장소

**참조 방법:**
```bash
# 직접 확인
cat ~/.ozzy-secrets/master.env | grep -E "(API_KEY|WALLET|SECRET)"

# 환경변수로 로드
export $(cat ~/.ozzy-secrets/master.env | xargs)
```

**주요 섹션:**
- `LLM API Keys`: GEMINI_API_KEY, GROQ_API_KEY, KIMI_API_KEY 등
- `Telegram`: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
- `거래소`: BINANCE_API_KEY, BYBIT_API_KEY, UPBIT_ACCESS_KEY 등
- `지갑`: PHANTOM_WALLET_*, METAMASK_PROFIT_WALLET 등
- `RPC`: HELIUS_API_KEY 등

**⚠️ 중요:** 이 파일 외부에는 민감정보를 저장하지 않는다. 모든 설정은 이 파일을 참조한다.

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

## 재부팅 후 자동 복구 명령어

**세션 재시작 또는 재부팅 후 반드시 실행:**

```bash
# 1. 환경변수 로드
export $(cat ~/.ozzy-secrets/master.env | xargs)

# 2. 봇 시스템 확인
cd /home/ozzy-claw/OZ_A2M
ps aux | grep -E "(run_all_bots|rpg_dashboard)" | grep -v grep

# 3. 대시보드 재시작 (필요시)
pkill -f rpg_dashboard.py 2>/dev/null
sleep 1
cd /home/ozzy-claw/OZ_A2M/department_7/src/dashboard
nohup python3 rpg_dashboard.py > /tmp/rpg_dashboard.log 2>&1 &
sleep 2
echo "Dashboard: http://192.168.51.28:8080 | http://100.77.207.113:8080"
curl -s http://192.168.51.28:8080/api/vault/summary | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Total: ${d['total_profit_usd']:.2f}\")"

# 4. 봇 상태 확인
curl -s http://192.168.51.28:8080/api/bots/status 2>/dev/null || echo "Bot status endpoint not available"
```

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

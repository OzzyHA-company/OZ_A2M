# OZ_A2M 재부팅 후 복구 가이드
**생성일:** 2026-04-01

---

## 1단계: 시스템 시작 (재부팅 후 즉시)

```bash
# 1. OZ_A2M 디렉토리로 이동
cd ~/OZ_A2M

# 2. 가상환경 활성화
source venv/bin/activate

# 3. Docker 서비스 시작 (Elasticsearch, Redis 등)
docker-compose up -d

# 4. 봇 로그 디렉토리 확인
mkdir -p logs
```

---

## 2단계: Binance 자금 정상화 (⚠️ 필수 - 수익 차단 해결)

### 문제 상황
- 설정 자본: $35.35 (Grid $11 + DCA $14 + Triarb $10.35)
- 실제 잔고: USDT $7.92 + SOL 0.324개 (~$26.73)
- SOL 평균단가: $84.65

### 해결 방법 선택 (둘 중 하나)

#### 옵션 A: SOL 전량 매도 (즉시 USDT 확보)
```bash
# Binance에서 SOL/USDT 전량 매도
# - 현재가 $82.50 기준 미실현 손실 -$0.70 감수
# - 매도 후 USDT ≈ $34.6 확보 가능
```

#### 옵션 B: Grid Bot 자본만 축소
```bash
# run_all_bots.py 수정:
# grid_binance_001 capital: $11.0 → $7.0
# 일부 SOL 보유 유지 (가격 상승 대응)
```

### 판단 기준
- **SOL이 $84.65 이상 오를 것 같으면** → 옵션 B
- **즉시 모든 봇 가동이 우선이면** → 옵션 A

---

## 3단계: 크래시 복구 (🔴 필수)

### 봇-02: DCA Binance (NOTIONAL 에러)
```bash
# 문제: 최소 주문금액($11) 미달로 크래시
# 확인:
grep "NOTIONAL\|dca_binance" logs/run_all_bots_*.log | tail -5

# 해결: 이미 수정됨 (dca_bot.py에 MIN_NOTIONAL_USDT = 10.0 설정)
# 재시작하면 정상 작동
```

### 봇-06: Bybit Scalper (API 키 오류)
```bash
# 문제: API key is invalid (retCode:10003)
# 확인:
grep "API key is invalid" logs/run_all_bots_*.log | tail -3

# 해결:
# 1. Bybit API 키 확인 ~/.ozzy-secrets/master.env
# 2. BYBIT_API_KEY, BYBIT_SECRET 값 확인
# 3. 필요시 Bybit 웹사이트에서 새 API 키 생성
```

---

## 4단계: 버그 수정 (🟡 권장)

### 봇-04: Funding Rate (await 오류)
```bash
# 파일: department_7/src/bot/funding_rate_bot.py:383
# 수정 전:
market = await exchange.market(symbol)

# 수정 후:
market = exchange.market(symbol)  # await 제거

# 빠른 수정 명령:
sed -i 's/await exchange.market(symbol)/exchange.market(symbol)/' department_7/src/bot/funding_rate_bot.py
```

---

## 5단계: 봇 전체 재시작

```bash
cd ~/OZ_A2M/department_7/src/bot

# 기존 봇 종료 확인
pkill -f "run_all_bots.py"
pkill -f "department_7.src.bot"
sleep 2

# 새로 시작
nohup python3 run_all_bots.py > ../../logs/run_all_bots_$(date +%Y%m%d_%H%M%S).log 2>&1 &
echo "봇 시작됨, PID: $!"

# 5초 후 상태 확인
sleep 5
ps aux | grep "run_all_bots\|department_7" | grep -v grep
```

---

## 6단계: 상태 모니터링

```bash
# 로그 실시간 확인
tail -f ~/OZ_A2M/logs/run_all_bots_*.log

# 또는 특정 봇 로그만
grep "grid_binance_001" ~/OZ_A2M/logs/run_all_bots_*.log | tail -20
grep "dca_binance_001" ~/OZ_A2M/logs/run_all_bots_*.log | tail -20

# 프로세스 확인
ps aux | grep -E "(grid|dca|triarb|funding|scalper|hyperliquid|polymarket|gmgn|pump)" | grep -v grep
```

---

## 7단계: 수익 확인

```bash
# Redis에서 실시간 PnL 확인
cd ~/OZ_A2M
python3 -c "
import asyncio
from lib.cache.redis_client import get_redis_cache

async def check():
    redis = get_redis_cache()
    await redis.connect()
    for bot_id in ['grid_binance_001', 'dca_binance_001', 'triarb_binance_001',
                   'funding_binance_bybit_001', 'grid_bybit_001', 'scalper_bybit_001']:
        status = await redis.get(f'bot:{bot_id}:status')
        pnl = await redis.get(f'bot:{bot_id}:pnl')
        print(f'{bot_id}: {status} | PnL: {pnl}')
    await redis.close()

asyncio.run(check())
"
```

---

## 빠른 실행 체크리스트

재부팅 후 순서대로 실행:

- [ ] `cd ~/OZ_A2M && source venv/bin/activate`
- [ ] `docker-compose up -d`
- [ ] **(선택)** Binance SOL 매또 또는 Grid 자본 조정
- [ ] **(필요시)** Bybit API 키 갱신
- [ ] `sed -i 's/await exchange.market(symbol)/exchange.market(symbol)/' department_7/src/bot/funding_rate_bot.py`
- [ ] `cd department_7/src/bot && nohup python3 run_all_bots.py > ../../logs/run_all_bots_$(date +%Y%m%d_%H%M%S).log 2>&1 &`
- [ ] `sleep 5 && ps aux | grep run_all_bots`
- [ ] `tail -f ~/OZ_A2M/logs/run_all_bots_*.log`

---

## 문제 발생 시 참조

| 증상 | 원인 | 해결 |
|------|------|------|
| "Insufficient funds" | SOL 보유 중 | SOL 매도 또는 Grid 자본 축소 |
| "NOTIONAL" 에러 | 최소 주문금액 미달 | 이미 수정됨, 재시작만 필요 |
| "API key is invalid" | Bybit 키 만료/오류 | master.env 확인 및 갱신 |
| "await expression" 에러 | 코드 버그 | await 제거 (4단계) |
| 봇 실행 중이나 거래 없음 | 미구현 기능 | Hyperliquid/Polymarket/GMGN은 Phase 2에서 구현 |

---

*이 가이드를 따라 5분 이내에 정상 가동 가능합니다.*

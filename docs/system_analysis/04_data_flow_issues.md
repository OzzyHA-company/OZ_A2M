# 04. 데이터 흐름 문제 상세 분석

## 끊어진 연결 4곳

### 🔴 Issue #1: D2 → D7 (검증된 신호 미전달)

**현상:**
- D2는 검증된 트레이딩 신호를 생산함
- D7 봇들이 이 신호를 수신하지 못함
- 봇들이 자체 신호만 사용

**코드 증거:**

```python
# D2: department_2/src/main.py (Line ~180)
async def _publish_verified_signal(self, signal, filter_result):
    topic = "oz/a2m/signals/verified"
    verified_signal = {
        **signal,
        "verified_at": datetime.utcnow().isoformat(),
        "verification": {
            "quality": filter_result.quality.value,
            "confidence": filter_result.confidence,
            "indicators": filter_result.indicators,
        },
        "department": "dept2",
    }
    await self._mqtt_client.publish(topic, payload, qos=1)
```

```python
# D7: department_7/src/bot/scalper.py (Line ~220)
# 봇이 구독하는 토픽
await self.mqtt.subscribe("signals/scalping", self._on_mqtt_message)
await self.mqtt.subscribe(f"orders/{self.bot_id}/execute", self._on_mqtt_message)

# 참고: "oz/a2m/signals/verified"는 구독 안함!
```

**결과:**
- D2의 검증 로직이 무의미
- 봇들이 검증되지 않은 신호 사용
- 기획 의도인 "검증된 Signal 생산" 미달성

**해결책:**
```python
# D7 봇들이 D2 신호 수신하도록 수정
await self.mqtt.subscribe("oz/a2m/signals/verified", self._on_verified_signal)

async def _on_verified_signal(self, message):
    payload = json.loads(message.payload.decode())
    if payload.get("symbol") == self.symbol:
        await self._execute_signal(payload)
```

---

### 🔴 Issue #2: D7 → D5 (거래 결과 미전달)

**현상:**
- D7 봇들이 거래를 실행함
- D5 성과분석이 거래 결과를 수신하지 못함
- PnL 분석 부정확

**코드 증거:**

```python
# D7: department_7/src/bot/scalper.py (Line ~400)
async def _publish_trade(self, trade: Trade):
    if self.event_bus:
        await self.event_bus.emit_trade(...)
    else:
        # MQTT로 발행
        topic = f"trades/{self.bot_id}"  # ← 개별 봇 토픽
        await self.mqtt.publish(topic, payload)
```

```python
# D5: department_5/src/main.py (Line ~100)
await client.subscribe("oz/a2m/trades/executed")  # ← 표준 토픽 기대

async def _handle_trade_message(self, message):
    # oz/a2m/trades/executed 형식 기대
    trade = {
        "trade_id": payload.get("trade_id"),
        "bot_id": payload.get("bot_id"),
        ...
    }
```

**불일치:**
- D7 발행: `trades/{bot_id}`
- D5 구독: `oz/a2m/trades/executed`

**결과:**
- D5가 실제 거래 데이터 못받음
- 목업 데이터로 분석 중
- 일일 리포트 부정확

**해결책:**
```python
# D7 봇들이 표준 토픽으로 발행
await self.mqtt.publish(
    "oz/a2m/trades/executed",
    json.dumps({
        "trade_id": trade.id,
        "bot_id": self.bot_id,
        "symbol": trade.symbol,
        "side": trade.side,
        "amount": trade.amount,
        "price": trade.price,
        "pnl": trade.pnl,
        "timestamp": datetime.utcnow().isoformat(),
    }),
    qos=1
)
```

---

### 🔴 Issue #3: D5 → D6 (성과 리포트 미수신)

**현상:**
- D5가 일일 리포트를 발행함
- D6 연구개발이 리포트를 구독하지 않음

**코드 증거:**

```python
# D5: department_5/src/main.py (Line ~200)
async def _generate_daily_report(self):
    report = {
        "type": "daily_report",
        "date": yesterday.isoformat(),
        "performance": performance,
        "risk": risk_metrics,
        "pnl": self._daily_pnl,
        "timestamp": datetime.utcnow().isoformat(),
        "department": "dept5",
    }
    await self._mqtt_client.publish(
        "oz/a2m/reports/daily",  # ← 발행
        json.dumps(report),
        qos=2,
    )
```

```python
# D6: department_6/src/main.py (Line ~80)
await client.subscribe("oz/a2m/commands/rnd")  # ← 명령만 구독
# oz/a2m/reports/daily 구독 안함! ← ❌
```

**결과:**
- D6가 D5 분석 결과 못받음
- 전략 개선을 위한 데이터 부족
- 피드백 루프 끊어짐

**해결책:**
```python
# D6가 D5 리포트 구독하도록 수정
await client.subscribe("oz/a2m/reports/daily")
await client.subscribe("oz/a2m/pnl/current")

async def _on_daily_report(self, message):
    report = json.loads(message.payload.decode())
    await self._analyze_and_improve(report)
```

---

### 🔴 Issue #4: D6 → D1/D7 (개선 신호 미적용)

**현상:**
- D6가 개선 프롬프트를 발행함
- D1/D7가 수신하지 않음

**코드 증거:**

```python
# D6: department_6/src/rnd_with_reward.py (Line ~150)
async def _publish_improvement_prompt(self, bot_id: str, prompt: str):
    await self._mqtt_client.publish(
        f"oz/a2m/bots/{bot_id}/improvement_prompt",
        json.dumps({
            'type': 'improvement_prompt',
            'bot_id': bot_id,
            'prompt': prompt,
            'suggestions': suggestions,
        }),
        qos=1,
    )
```

```python
# D7: department_7/src/bot/grid_bot.py
# improvement_prompt 토픽 구독 없음 ← ❌

# D1: department_1/src/main.py  
# improvement_prompt 토픽 구독 없음 ← ❌
```

**결과:**
- D6의 분석 결과 아묏도 반영 안함
- 전략 개선이 실제 시스템에 적용 안됨
- R&D 팀의 분석이 무의미

**해결책:**
```python
# D7 봇들이 개선 신호 수신
await self.mqtt.subscribe(
    f"oz/a2m/bots/{self.bot_id}/improvement_prompt",
    self._on_improvement
)

async def _on_improvement(self, message):
    payload = json.loads(message.payload.decode())
    suggestions = payload.get("suggestions")
    # 봇 파라미터 자동 조정
    await self._apply_suggestions(suggestions)
```

---

## MQTT 토픽 표준화 필요

### 현재 토픽 (혼란)
```
# D2 발행
oz/a2m/signals/verified

# D7 구독
signals/scalping
signals/grid

# D7 발행
trades/{bot_id}

# D5 구독
oz/a2m/trades/executed
```

### 제안 표준 토픽
```
# 데이터 흐름
oz/a2m/market/{symbol}/price        # D1 발행
oz/a2m/market/{symbol}/orderbook    # D1 발행
oz/a2m/signals/verified             # D2 발행 (표준화)
oz/a2m/trades/executed              # D7 발행 (표준화)
oz/a2m/pnl/current                  # D5 발행
oz/a2m/reports/daily                # D5 발행
oz/a2m/bots/{id}/improvement        # D6 발행

# 명령
oz/a2m/commands/{department}/*      # 모든 부서
oz/a2m/system/verify                # D6 → D2
```

---

## 다음 문서

- `05_gap_analysis.md` - 기획 vs 현재 차이점

#!/bin/bash
# OZ_A2M 전체 시스템 시작 스크립트
# 순서: Infrastructure → Ant Colony Nest → 봇 진단 → 봇 실행
# 2026-04-02 업데이트: Gemini+Groq+Kimi LLM 체인

set -e
cd /home/ozzy-claw/OZ_A2M
source /home/ozzy-claw/.ozzy-secrets/master.env 2>/dev/null || true

echo "======================================"
echo "🐜 OZ_A2M 시스템 시작"
echo "======================================"
echo "자본: Binance \$32.71 | Bybit \$23.32 | MetaMask \$19.84"
echo "     Phantom A \$4.44 | B \$7.88 | C \$5.28"
echo "======================================"

# 1. 인프라 확인
echo ""
echo "[1/5] 인프라 상태 확인..."
docker ps --format "{{.Names}}: {{.Status}}" | grep -E "oz_a2m|oza2m" | while read line; do
    echo "  $line"
done

# Redis 테스트
if docker exec oz_a2m_redis redis-cli ping &>/dev/null; then
    echo "  ✅ Redis: PONG"
else
    echo "  ❌ Redis: 연결 실패"
fi

# MQTT 테스트
if mosquitto_pub -h localhost -t oz_a2m/health -m "ping" -q 0 &>/dev/null; then
    echo "  ✅ MQTT: OK"
fi

# Gateway 테스트
GW_STATUS=$(curl -s http://localhost:8000/llm/status | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('primary','none'))" 2>/dev/null)
echo "  ✅ LLM Gateway: $GW_STATUS"

# 2. Ant Colony Nest 시작
echo ""
echo "[2/5] Ant Colony Nest 시작..."
NEST_PID_FILE="/tmp/oz_a2m_nest.pid"
if [ -f "$NEST_PID_FILE" ] && kill -0 $(cat "$NEST_PID_FILE") 2>/dev/null; then
    echo "  ✅ Nest: 이미 실행 중 (PID: $(cat $NEST_PID_FILE))"
else
    cd /home/ozzy-claw/.openclaw/skills/oz-a2m-ant-colony-nest/scripts
    REDIS_HOST=localhost MQTT_HOST=localhost NEST_API_PORT=8084 \
        python3 nest_core.py &
    NEST_PID=$!
    echo "$NEST_PID" > "$NEST_PID_FILE"
    echo "  ✅ Nest: 시작됨 (PID: $NEST_PID, PORT: 8084)"
    cd /home/ozzy-claw/OZ_A2M
    sleep 2
fi

# 3. 봇 진단
echo ""
echo "[3/5] 봇 진단..."
python3 /home/ozzy-claw/OZ_A2M/scripts/fix_bots_and_resume_trading.py 2>&1 | grep -E "✅|❌|🔸|🔴|⚠️" | head -20

# 4. 수익 추적 DB 확인
echo ""
echo "[4/5] 수익 추적 DB..."
DB_PATH="$HOME/OZ_A2M/external/ant-colony-nest/data/profit_tracking.db"
if [ -f "$DB_PATH" ]; then
    echo "  ✅ DB 존재: $DB_PATH"
    ROWS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM capital_snapshots;" 2>/dev/null || echo "0")
    echo "  📊 캐피털 스냅샷: ${ROWS}개"
else
    echo "  ⚠️  DB 없음 - 첫 실행 시 자동 생성됨"
fi

# 5. 봇 실행
echo ""
echo "[5/5] 봇 실행..."
echo "  환경변수 체크:"
[ -n "$BINANCE_API_KEY" ] && echo "    ✅ BINANCE_API_KEY" || echo "    ❌ BINANCE_API_KEY 미설정"
[ -n "$BYBIT_API_KEY" ]   && echo "    ✅ BYBIT_API_KEY"   || echo "    ❌ BYBIT_API_KEY 미설정"
[ -n "$PHANTOM_WALLET_A" ] && echo "    ✅ PHANTOM_WALLET_A" || echo "    ❌ PHANTOM_WALLET_A 미설정"
[ -n "$PHANTOM_WALLET_B" ] && echo "    ✅ PHANTOM_WALLET_B" || echo "    ❌ PHANTOM_WALLET_B 미설정"
[ -n "$PHANTOM_WALLET_C" ] && echo "    ✅ PHANTOM_WALLET_C" || echo "    ❌ PHANTOM_WALLET_C 미설정"

if [ -n "$BINANCE_API_KEY" ] && [ -n "$BYBIT_API_KEY" ]; then
    echo ""
    echo "  봇 실행 시작..."
    cd /home/ozzy-claw/OZ_A2M/department_7/src/bot
    BOT_PID_FILE="/tmp/oz_a2m_bots.pid"
    python3 run_all_bots.py &
    BOT_PID=$!
    echo "$BOT_PID" > "$BOT_PID_FILE"
    echo "  ✅ 봇 실행 중 (PID: $BOT_PID)"
else
    echo ""
    echo "  ⚠️  API 키 미설정으로 봇 자동 실행 건너뜀"
    echo "  설정 방법:"
    echo "    export BINANCE_API_KEY=<your_key>"
    echo "    export BINANCE_API_SECRET=<your_secret>"
    echo "    export BYBIT_API_KEY=<your_key>"
    echo "    export BYBIT_API_SECRET=<your_secret>"
    echo "    export PHANTOM_WALLET_A=<phantom_a_address>"
    echo "    export PHANTOM_WALLET_B=<phantom_b_address>"
    echo "    export PHANTOM_WALLET_C=<phantom_c_address>"
    echo "  그 후: bash /home/ozzy-claw/OZ_A2M/scripts/start_oza2m.sh"
fi

echo ""
echo "======================================"
echo "📊 OZ_A2M 대시보드:"
echo "   Gateway:    http://localhost:8000"
echo "   LLM Status: http://localhost:8000/llm/status"
echo "   Nest API:   http://localhost:8084"
echo "   Grafana:    http://localhost:3000"
echo "   Tailscale:  http://100.77.207.113:8080"
echo "======================================"

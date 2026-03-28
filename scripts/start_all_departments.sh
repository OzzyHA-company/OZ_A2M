#!/bin/bash
# OZ_A2M 모든 부서 시작 스크립트

set -e

PROJECT_ROOT="/home/ozzy-claw/OZ_A2M"
LOG_DIR="$PROJECT_ROOT/logs"
PID_DIR="$PROJECT_ROOT/pids"

# 디렉토리 생성
mkdir -p "$LOG_DIR" "$PID_DIR"

echo "Starting OZ_A2M Department Services..."

# 제2부서: 정보검증분석센터
echo "[1/5] Starting Department 2 (Verification Center)..."
nohup python3 "$PROJECT_ROOT/department_2/src/verification_pipeline.py" \
    > "$LOG_DIR/dept2.log" 2>&1 &
echo $! > "$PID_DIR/dept2.pid"
echo "  PID: $(cat "$PID_DIR/dept2.pid")"

# 제3부서: 보안팀
echo "[2/5] Starting Department 3 (Security Team)..."
nohup python3 "$PROJECT_ROOT/department_3/src/main.py" \
    > "$LOG_DIR/dept3.log" 2>&1 &
echo $! > "$PID_DIR/dept3.pid"
echo "  PID: $(cat "$PID_DIR/dept3.pid")"

# 제4부서: 유지보수관리팀
echo "[3/5] Starting Department 4 (DevOps Team)..."
nohup python3 "$PROJECT_ROOT/department_4/src/main.py" \
    > "$LOG_DIR/dept4.log" 2>&1 &
echo $! > "$PID_DIR/dept4.pid"
echo "  PID: $(cat "$PID_DIR/dept4.pid")"

# 제5부서: 성과분석팀
echo "[4/5] Starting Department 5 (Performance Team)..."
nohup python3 "$PROJECT_ROOT/department_5/src/main.py" \
    > "$LOG_DIR/dept5.log" 2>&1 &
echo $! > "$PID_DIR/dept5.pid"
echo "  PID: $(cat "$PID_DIR/dept5.pid")"

# 제6부서: 연구개발팀
echo "[5/5] Starting Department 6 (R&D Team)..."
nohup python3 "$PROJECT_ROOT/department_6/src/main.py" \
    > "$LOG_DIR/dept6.log" 2>&1 &
echo $! > "$PID_DIR/dept6.pid"
echo "  PID: $(cat "$PID_DIR/dept6.pid")"

echo ""
echo "All departments started!"
echo "Logs: $LOG_DIR/"
echo "PIDs: $PID_DIR/"
echo ""
echo "Status check:"
sleep 2
for pid_file in "$PID_DIR"/*.pid; do
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        name=$(basename "$pid_file" .pid)
        if kill -0 "$pid" 2>/dev/null; then
            echo "  $name: RUNNING (PID: $pid)"
        else
            echo "  $name: NOT RUNNING"
        fi
    fi
done

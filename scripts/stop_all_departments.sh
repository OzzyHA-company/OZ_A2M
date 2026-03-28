#!/bin/bash
# OZ_A2M 모든 부서 중지 스크립트

set -e

PID_DIR="/home/ozzy-claw/OZ_A2M/pids"

echo "Stopping OZ_A2M Department Services..."

if [ ! -d "$PID_DIR" ]; then
    echo "PID directory not found: $PID_DIR"
    exit 1
fi

# 모든 PID 파일 처리
for pid_file in "$PID_DIR"/*.pid; do
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        name=$(basename "$pid_file" .pid)

        if kill -0 "$pid" 2>/dev/null; then
            echo "Stopping $name (PID: $pid)..."
            kill "$pid" 2>/dev/null || true

            # 종료 대기
            for i in {1..10}; do
                if ! kill -0 "$pid" 2>/dev/null; then
                    echo "  $name stopped"
                    break
                fi
                sleep 1
            done

            # 강제 종료
            if kill -0 "$pid" 2>/dev/null; then
                echo "  $name force killing..."
                kill -9 "$pid" 2>/dev/null || true
            fi
        else
            echo "$name not running (PID: $pid)"
        fi

        rm -f "$pid_file"
    fi
done

echo ""
echo "All departments stopped!"

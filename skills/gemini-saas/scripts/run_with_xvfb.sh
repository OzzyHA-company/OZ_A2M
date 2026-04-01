#!/bin/bash
# OZ-PI Gemini SaaS - Xvfb Runner Script
# Runs the authentication script with virtual display

# Check if xvfb-run is available
if ! command -v xvfb-run &> /dev/null; then
    echo "❌ xvfb-run is not installed"
    echo ""
    echo "Please install xvfb first:"
    echo "  sudo apt update && sudo apt install -y xvfb"
    echo ""
    exit 1
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run auth script with xvfb
# -a: auto-display (find free display number)
# --server-args: Xvfb server arguments
xvfb-run -a --server-args="-screen 0 1280x720x24" python3 "$SCRIPT_DIR/auth_gemini.py" "$@"

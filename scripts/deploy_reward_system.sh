#!/bin/bash
#
# OZ_A2M Reward System 배포 스크립트
# 수익 극대화형 RPG + FinRL 기반 보상 시스템
#

set -e

echo "=========================================="
echo "  OZ_A2M Reward System Deployment"
echo "  Phase 1-3: Complete"
echo "=========================================="

# 색상 설정
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 프로젝트 루트
PROJECT_ROOT="/home/ozzy-claw/OZ_A2M"
cd "$PROJECT_ROOT"

# 디렉토리 생성
echo -e "${YELLOW}[1/7] Creating directories...${NC}"
mkdir -p data logs config

# Python 경로 설정
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"

# 환경 변수 확인
echo -e "${YELLOW}[2/7] Checking environment...${NC}"
if [ -f "/home/ozzy-claw/.ozzy-secrets/master.env" ]; then
    echo -e "${GREEN}  ✓ Environment file found${NC}"
else
    echo -e "${RED}  ✗ Environment file not found${NC}"
    exit 1
fi

# 종속성 확인
echo -e "${YELLOW}[3/7] Checking dependencies...${NC}"
python3 -c "import aiomqtt, numpy" 2>/dev/null && echo -e "${GREEN}  ✓ Dependencies OK${NC}" || {
    echo -e "${RED}  ✗ Missing dependencies${NC}"
    pip3 install aiomqtt numpy --quiet
}

# Reward System 모듈 테스트
echo -e "${YELLOW}[4/7] Testing Reward System modules...${NC}"
python3 -c "
from lib.core.reward_system import (
    RewardCalculator, RPGSystem, BotClassifier, CapitalAllocator,
    RewardAwareBot, TradingAgentsRewardBridge
)
print('All modules loaded successfully')
" && echo -e "${GREEN}  ✓ Modules OK${NC}" || {
    echo -e "${RED}  ✗ Module import failed${NC}"
    exit 1
}

# 기존 프로세스 종료
echo -e "${YELLOW}[5/7] Stopping existing services...${NC}"
pkill -f "rnd_with_reward.py" 2>/dev/null || true
pkill -f "reward_service.py" 2>/dev/null || true
sleep 2
echo -e "${GREEN}  ✓ Services stopped${NC}"

# 새 서비스 시작
echo -e "${YELLOW}[6/7] Starting Reward System services...${NC}"

# R&D + Reward Service (department_6 통합)
nohup python3 department_6/src/rnd_with_reward.py > logs/rnd_reward_service.log 2>&1 &
echo $! > /tmp/rnd_reward_service.pid
echo -e "${GREEN}  ✓ R&D Reward Service started (PID: $(cat /tmp/rnd_reward_service.pid))${NC}"

# 서비스 시작 대기
sleep 3

# 서비스 상태 확인
if pgrep -f "rnd_with_reward.py" > /dev/null; then
    echo -e "${GREEN}  ✓ Service is running${NC}"
else
    echo -e "${RED}  ✗ Service failed to start${NC}"
    echo "  Check logs: logs/rnd_reward_service.log"
    exit 1
fi

# 봇 상태 초기화
echo -e "${YELLOW}[7/7] Initializing bot RPG states...${NC}"
python3 -c "
import sys
sys.path.insert(0, '.')
from lib.core.reward_system import RPGSystem, CapitalAllocator, BotClassifier
from lib.core.reward_system.bot_classifier import DEFAULT_BOT_CONFIGS

# 초기화
rpg = RPGSystem()
capital = CapitalAllocator()
classifier = BotClassifier()

# 11봇 등록
for config in DEFAULT_BOT_CONFIGS:
    bot_id = config['bot_id']
    capital.register_bot(bot_id, config['capital_usd'])
    classifier.create_profile(
        bot_id=bot_id,
        bot_name=config['name'],
        exchange=config['exchange'],
        symbols=config['symbols'],
        capital_usd=config['capital_usd']
    )
    state = rpg.get_or_create_state(bot_id, config['name'])
    print(f'  ✓ {bot_id}: Level {state.level.current}, Grade {state.grade.kr_name}')

# 저장
rpg.save()
capital.save()
print('All bots initialized')
"

echo ""
echo "=========================================="
echo -e "${GREEN}  Reward System Deployment Complete!${NC}"
echo "=========================================="
echo ""
echo "Services:"
echo "  - R&D Reward Service: Running (PID: $(cat /tmp/rnd_reward_service.pid))"
echo "  - Logs: logs/rnd_reward_service.log"
echo ""
echo "Endpoints:"
echo "  - Reward System: MQTT oz/a2m/rewards/#"
echo "  - RPG Status: oz/a2m/bots/+/rpg_status"
echo ""
echo "Dashboard:"
echo "  - CEO Dashboard: http://localhost:8086"
echo "  - Reward API: /api/reward/* (integration ready)"
echo ""
echo "Next steps:"
echo "  1. Start trading bots with Reward System enabled"
echo "  2. Monitor RPG status via dashboard"
echo "  3. Daily reallocation at 01:00 UTC"
echo ""

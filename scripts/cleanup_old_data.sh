#!/bin/bash
# OZ_A2M 오래된 데이터 정리 스크립트
# 잘못된/오래된 데이터 파일 정리

echo "🧹 OZ_A2M 오래된 데이터 정리 시작"
echo "================================"

# 1. 오래된 캐시 파일 정리
echo "1. Python 캐시 파일 정리..."
find /home/ozzy-claw/OZ_A2M -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find /home/ozzy-claw/OZ_A2M -name "*.pyc" -delete 2>/dev/null
echo "   ✅ 캐시 파일 정리 완료"

# 2. 오래된 로그 파일 정리 (30일 이상)
echo "2. 오래된 로그 파일 정리..."
find /tmp -name "*.log" -mtime +30 -delete 2>/dev/null
echo "   ✅ 오래된 로그 정리 완료"

# 3. 오래된 메모리 파일 아카이브
echo "3. 오래된 메모리 파일 정리..."
mkdir -p /home/ozzy-claw/.claude/projects/-home-ozzy-claw/memory/archive_2026_03
mv /home/ozzy-claw/.claude/projects/-home-ozzy-claw/memory/project_*_2026-03*.md /home/ozzy-claw/.claude/projects/-home-ozzy-claw/memory/archive_2026_03/ 2>/dev/null
echo "   ✅ 2026년 3월 메모리 파일 아카이브 완료"

# 4. 오래된 데이터 파일 정리
echo "4. 오래된 데이터 파일 정리..."
rm -f /home/ozzy-claw/OZ_A2M/data/capital_allocations.json  # 잘못된 자본 분배값
echo "   ✅ 오래된 capital_allocations.json 삭제"

# 5. 오래된 문서 아카이브
echo "5. 오래된 문서 정리..."
mkdir -p /home/ozzy-claw/OZ_A2M/docs/archive
cp /home/ozzy-claw/OZ_A2M/docs/*2026-03*.md /home/ozzy-claw/OZ_A2M/docs/archive/ 2>/dev/null
echo "   ✅ 3월 문서 아카이브 완료"

echo ""
echo "================================"
echo "✅ 데이터 정리 완료"
echo ""
echo "주의: 다음 파일들은 수동 확인 필요"
echo "  - docs/DIAGNOSTIC_REPORT_2026-03-30.md"
echo "  - docs/FIX_REPORT_2026-03-30.md"
echo "  - .claude/memory/SHARED_CONTEXT.md (수동 업데이트 필요)"

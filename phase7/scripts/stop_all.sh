#!/bin/bash
# OZ_A2M Phase 7: Stop All Enhanced Infrastructure

set -e

BASE_DIR="/home/ozzy-claw/OZ_A2M/phase7"

echo "🛑 OZ_A2M Phase 7 인프라 종료"
echo "=============================="

# Stop Observability
echo "📊 Observability Stack 종료..."
cd "$BASE_DIR/observability"
docker-compose -f docker-compose.observability.yml down

# Stop Kafka
echo "📨 Kafka Cluster 종료..."
cd "$BASE_DIR/kafka"
docker-compose down

# Stop Redis
echo "📦 Redis Cluster 종료..."
cd "$BASE_DIR/redis"
docker-compose -f redis_cluster.yml down

echo ""
echo "✅ 모든 서비스가 종료되었습니다."

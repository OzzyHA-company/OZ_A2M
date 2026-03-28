#!/bin/bash
# OZ_A2M Phase 7: Start All Enhanced Infrastructure

set -e

echo "🚀 OZ_A2M Phase 7 고도화 인프라 시작"
echo "========================================"

BASE_DIR="/home/ozzy-claw/OZ_A2M/phase7"

# Function to check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        echo "❌ Docker가 실행 중이 아닙니다. Docker를 시작해주세요."
        exit 1
    fi
}

# Start Redis Cluster
start_redis() {
    echo ""
    echo "📦 Redis Cluster 시작..."
    cd "$BASE_DIR/redis"
    docker-compose -f redis_cluster.yml up -d
    sleep 3

    # Check Redis
    if redis-cli -p 6379 ping | grep -q "PONG"; then
        echo "✅ Redis Master-1 연결됨"
    fi
    if redis-cli -p 26379 ping | grep -q "PONG"; then
        echo "✅ Redis Sentinel 연결됨"
    fi
}

# Start Kafka
start_kafka() {
    echo ""
    echo "📨 Kafka Cluster 시작..."
    cd "$BASE_DIR/kafka"
    docker-compose up -d
    sleep 10

    # Initialize topics
    echo "📋 Kafka 토픽 초기화..."
    python3 topics/init_topics.py || echo "⚠️ 토픽 초기화 스킵 (Kafka 대기 중)"
}

# Start Observability
start_observability() {
    echo ""
    echo "📊 Observability Stack 시작..."
    cd "$BASE_DIR/observability"
    docker-compose -f docker-compose.observability.yml up -d
    sleep 5
}

# Main execution
main() {
    check_docker

    echo ""
    read -p "모든 서비스를 시작하시겠습니까? (y/n) " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        start_redis
        start_kafka
        start_observability

        echo ""
        echo "========================================"
        echo "✅ Phase 7 인프라 시작 완료!"
        echo ""
        echo "🌐 서비스 URL:"
        echo "  • Grafana:      http://localhost:3001 (admin/oza2m_admin)"
        echo "  • Prometheus:   http://localhost:9090"
        echo "  • Jaeger:       http://localhost:16686"
        echo "  • Kafka UI:     http://localhost:8080"
        echo ""
        echo "🔧 Redis Ports:"
        echo "  • Master-1:     6379"
        echo "  • Master-2:     6380"
        echo "  • Master-3:     6381"
        echo "  • Sentinel:     26379"
        echo ""
        echo "📨 Kafka Ports:"
        echo "  • Broker-1:     9092"
        echo "  • Broker-2:     9093"
        echo ""
        echo "⚠️  종료하려면: bash $BASE_DIR/scripts/stop_all.sh"
    else
        echo "취소되었습니다."
    fi
}

main

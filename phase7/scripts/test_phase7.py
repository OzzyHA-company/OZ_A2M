#!/usr/bin/env python3
"""
OZ_A2M Phase 7 Integration Test
고도화 인프라 통합 테스트
"""

import sys
import asyncio
import redis
from kafka import KafkaProducer, KafkaConsumer
from kafka.admin import KafkaAdminClient
import json
import time
from pathlib import Path

# Add project path
sys.path.insert(0, '/home/ozzy-claw/OZ_A2M')
sys.path.insert(0, '/home/ozzy-claw/OZ_A2M/phase7/mlops')
sys.path.insert(0, '/home/ozzy-claw/OZ_A2M/phase7/observability')

class Phase7Tester:
    """Phase 7 통합 테스트"""

    def __init__(self):
        self.results = []

    def log(self, message: str, success: bool = True):
        """테스트 결과 로깅"""
        status = "✅" if success else "❌"
        print(f"{status} {message}")
        self.results.append((message, success))

    def test_redis(self) -> bool:
        """Redis 연결 테스트"""
        print("\n📦 Redis Cluster 테스트")
        print("-" * 40)

        try:
            # Test Master-1
            r = redis.Redis(host='localhost', port=6380, decode_responses=True)
            r.ping()
            self.log("Redis Master-1 연결")

            # Test operations
            r.setex("test:phase7", 60, json.dumps({"timestamp": time.time()}))
            data = r.get("test:phase7")
            self.log("Redis SET/GET 작동")

            # Test hash (for market data caching)
            r.hset("cache:market:BTCUSDT", mapping={
                "price": "65000.00",
                "change": "2.5",
                "volume": "15000"
            })
            self.log("Redis Hash 작동 (시장 데이터 캐싱)")

            # Test sorted set (for leaderboards)
            r.zadd("leaderboard:pnl", {"bot1": 125.5, "bot2": 98.3})
            self.log("Redis Sorted Set 작동 (리더보드)")

            # Clean up
            r.delete("test:phase7", "cache:market:BTCUSDT")
            r.delete("leaderboard:pnl")

            return True
        except Exception as e:
            self.log(f"Redis 테스트 실패: {e}", success=False)
            return False

    def test_kafka(self) -> bool:
        """Kafka 연결 테스트"""
        print("\n📨 Kafka 테스트")
        print("-" * 40)

        try:
            # Test admin connection
            admin = KafkaAdminClient(
                bootstrap_servers='localhost:9092',
                client_id='phase7-test'
            )
            topics = admin.list_topics()
            admin.close()
            self.log(f"Kafka 연결 성공 ({len(topics)} 토픽)")

            # Test producer
            producer = KafkaProducer(
                bootstrap_servers=['localhost:9092'],
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )

            # Send test message
            future = producer.send('system.heartbeat', {
                'service': 'phase7-test',
                'timestamp': time.time(),
                'status': 'healthy'
            })
            future.get(timeout=10)
            producer.close()
            self.log("Kafka Producer 작동")

            return True
        except Exception as e:
            self.log(f"Kafka 테스트 실패: {e}", success=False)
            return False

    def test_model_registry(self) -> bool:
        """ML Model Registry 테스트"""
        print("\n🤖 Model Registry 테스트")
        print("-" * 40)

        try:
            from model_registry import get_registry

            registry = get_registry()

            # Create dummy model file
            test_model_dir = Path('/home/ozzy-claw/OZ_A2M/phase7/mlops/test_models')
            test_model_dir.mkdir(exist_ok=True)

            test_model = test_model_dir / 'test_model.pkl'
            test_model.write_bytes(b'dummy model data')

            # Register model
            metadata = registry.register_model(
                name="test_strategy",
                version="v1.0.0",
                model_path=str(test_model),
                framework="sklearn",
                description="Test model for Phase 7",
                metrics={"accuracy": 0.85, "f1": 0.82},
                tags=["test", "scalping"],
                author="Phase7Tester"
            )

            self.log(f"모델 등록: {metadata.name}:{metadata.version}")

            # Retrieve model
            model_path = registry.get_model("test_strategy", "v1.0.0")
            if model_path:
                self.log("모델 검색 작동")

            # Clean up
            registry.delete_model("test_strategy", "v1.0.0")
            test_model.unlink()

            return True
        except Exception as e:
            self.log(f"Model Registry 테스트 실패: {e}", success=False)
            return False

    def test_opentelemetry(self) -> bool:
        """OpenTelemetry 테스트"""
        print("\n📊 OpenTelemetry 테스트")
        print("-" * 40)

        try:
            from observability.opentelemetry_setup import get_telemetry

            telemetry = get_telemetry(service_name="phase7-test")

            # Test tracing
            with telemetry.span("test.operation", {"test": True}):
                time.sleep(0.01)

            self.log("Distributed Tracing 작동")

            # Test metrics
            telemetry.record_order("BTC/USDT", "buy", 0.1, 150.5)
            telemetry.record_trade("BTC/USDT", "sell", 0.05, 65100.0)
            telemetry.update_pnl("BTC/USDT", 125.50)
            self.log("메트릭 기록 작동")

            return True
        except Exception as e:
            self.log(f"OpenTelemetry 테스트 실패: {e}", success=False)
            return False

    def run_all_tests(self):
        """모든 테스트 실행"""
        print("=" * 60)
        print("🔬 OZ_A2M Phase 7 통합 테스트 시작")
        print("=" * 60)

        tests = [
            ("Redis Cluster", self.test_redis),
            ("Kafka Event Bus", self.test_kafka),
            ("ML Model Registry", self.test_model_registry),
            ("OpenTelemetry", self.test_opentelemetry),
        ]

        passed = 0
        failed = 0

        for name, test_func in tests:
            try:
                if test_func():
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                self.log(f"{name} 테스트 예외: {e}", success=False)
                failed += 1

        # Summary
        print("\n" + "=" * 60)
        print("📋 테스트 결과 요약")
        print("=" * 60)

        for message, success in self.results:
            status = "PASS" if success else "FAIL"
            print(f"  [{status}] {message}")

        print("-" * 60)
        print(f"총 테스트: {passed + failed}")
        print(f"✅ 통과: {passed}")
        print(f"❌ 실패: {failed}")

        if failed == 0:
            print("\n🎉 Phase 7 모든 테스트 통과!")
            return 0
        else:
            print(f"\n⚠️  {failed}개 테스트 실패")
            return 1


if __name__ == "__main__":
    tester = Phase7Tester()
    sys.exit(tester.run_all_tests())

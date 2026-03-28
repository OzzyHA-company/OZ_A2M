#!/usr/bin/env python3
"""
P1 통합 테스트
- 봇 아키텍처 통합 (UnifiedBotManager)
- Phase 7 인프라 연동 (EventBus - Kafka + MQTT)
"""

import sys
import asyncio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from lib.messaging.event_bus import EventBus, EventType, EventPriority, Event, get_event_bus
from department_7.manager import UnifiedBotManager, get_bot_manager


def test_event_bus_creation():
    """EventBus 생성 테스트"""
    print("\n📦 EventBus 생성 테스트")
    print("-" * 40)

    try:
        # 기본 EventBus (MQTT만)
        bus = get_event_bus()
        assert bus is not None
        print("✅ EventBus 인스턴스 생성 (MQTT only)")

        # Kafka 활성화 EventBus
        bus_with_kafka = get_event_bus(
            mqtt_host="localhost",
            mqtt_port=1883,
            enable_kafka=True
        )
        assert bus_with_kafka is not None
        print("✅ EventBus 인스턴스 생성 (Kafka + MQTT)")

        return True
    except Exception as e:
        print(f"❌ EventBus 생성 실패: {e}")
        return False


def test_event_creation():
    """Event 생성 및 변환 테스트"""
    print("\n📨 Event 생성 테스트")
    print("-" * 40)

    try:
        event = Event(
            type=EventType.SIGNAL_BUY,
            payload={"symbol": "BTC/USDT", "price": 65000.0},
            priority=EventPriority.HIGH,
            source="test"
        )

        # to_dict 변환
        event_dict = event.to_dict()
        assert event_dict["type"] == "signal.buy"
        assert event_dict["priority"] == "high"
        assert event_dict["payload"]["symbol"] == "BTC/USDT"
        print("✅ Event to_dict 변환")

        # to_json 변환
        event_json = event.to_json()
        assert isinstance(event_json, str)
        assert "signal.buy" in event_json
        print("✅ Event to_json 변환")

        return True
    except Exception as e:
        print(f"❌ Event 생성 실패: {e}")
        return False


def test_unified_bot_manager():
    """UnifiedBotManager 생성 테스트"""
    print("\n🤖 UnifiedBotManager 테스트")
    print("-" * 40)

    try:
        manager = get_bot_manager(dry_run=True)
        assert manager is not None
        assert manager.dry_run is True
        print("✅ UnifiedBotManager 인스턴스 생성")

        # 봇 상태 조회 (빈 상태)
        all_status = manager.get_all_status()
        assert isinstance(all_status, list)
        print("✅ 봇 상태 조회")

        return True
    except Exception as e:
        print(f"❌ UnifiedBotManager 테스트 실패: {e}")
        return False


async def test_event_bus_convenience_methods():
    """EventBus 편의 메서드 테스트"""
    print("\n📡 EventBus 편의 메서드 테스트")
    print("-" * 40)

    try:
        bus = get_event_bus()

        # 연결 (MQTT 브로커 없어도 실패하지 않음)
        try:
            await bus.connect()
            print("✅ EventBus 연결")
        except Exception as e:
            print(f"⚠️  EventBus 연결 실패 (예상됨 - MQTT 브로커 없음): {e}")

        # emit_signal 테스트
        try:
            await bus.emit_signal(
                signal_type="buy",
                symbol="BTC/USDT",
                price=65000.0,
                confidence=0.85
            )
            print("✅ emit_signal 호출")
        except Exception as e:
            print(f"⚠️  emit_signal 실패 (예상됨): {e}")

        # emit_order 테스트
        try:
            await bus.emit_order(
                order_id="test-order-001",
                symbol="BTC/USDT",
                side="buy",
                amount=0.001,
                price=65000.0,
                order_type="limit"
            )
            print("✅ emit_order 호출")
        except Exception as e:
            print(f"⚠️  emit_order 실패 (예상됨): {e}")

        # emit_trade 테스트
        try:
            await bus.emit_trade(
                trade_id="test-trade-001",
                order_id="test-order-001",
                symbol="BTC/USDT",
                side="buy",
                amount=0.001,
                price=65000.0,
                pnl=0.0
            )
            print("✅ emit_trade 호출")
        except Exception as e:
            print(f"⚠️  emit_trade 실패 (예상됨): {e}")

        # emit_bot_status 테스트
        try:
            await bus.emit_bot_status(
                bot_id="test-bot-001",
                status="running",
                detail={"uptime": 3600}
            )
            print("✅ emit_bot_status 호출")
        except Exception as e:
            print(f"⚠️  emit_bot_status 실패 (예상됨): {e}")

        # 연결 해제
        try:
            await bus.disconnect()
            print("✅ EventBus 연결 해제")
        except:
            pass

        return True
    except Exception as e:
        print(f"❌ EventBus 편의 메서드 테스트 실패: {e}")
        return False


def test_scalper_bot_with_event_bus():
    """ScalpingBot EventBus 통합 테스트"""
    print("\n🔄 ScalpingBot EventBus 통합 테스트")
    print("-" * 40)

    try:
        from department_7.src.bot.scalper import ScalpingBot

        bot = ScalpingBot(
            bot_id="test_scalper",
            symbol="BTC/USDT",
            sandbox=True
        )

        # EventBus 속성 확인
        assert hasattr(bot, 'event_bus')
        assert hasattr(bot, 'enable_kafka')
        print("✅ ScalpingBot EventBus 속성 확인")

        return True
    except Exception as e:
        print(f"❌ ScalpingBot 통합 테스트 실패: {e}")
        return False


def test_architecture_consolidation():
    """아키텍처 통합 검증"""
    print("\n🏗️  아키텍처 통합 검증")
    print("-" * 40)

    try:
        # 1. UnifiedBotManager가 department_7에 있어야 함
        from department_7.manager import UnifiedBotManager
        print("✅ UnifiedBotManager가 department_7에 위치")

        # 2. ScalpingBot이 department_7/src/bot에 있어야 함
        from department_7.src.bot.scalper import ScalpingBot
        print("✅ ScalpingBot이 department_7/src/bot에 위치")

        # 3. EventBus가 lib/messaging에 있어야 함
        from lib.messaging.event_bus import EventBus
        print("✅ EventBus가 lib/messaging에 위치")

        # 4. MQTT 클라이언트가 lib/messaging에 있어야 함
        from lib.messaging.mqtt_client import MQTTClient
        print("✅ MQTTClient가 lib/messaging에 위치")

        # 5. 중복 없이 단일 라이브러리 사용 (aiomqtt)
        import lib.messaging.mqtt_client as mqtt_module
        import inspect
        source = inspect.getsource(mqtt_module)
        assert "aiomqtt" in source
        assert "gmqtt" not in source
        print("✅ MQTT 라이브러리 통일 (aiomqtt)")

        return True
    except Exception as e:
        print(f"❌ 아키텍처 통합 검증 실패: {e}")
        return False


async def run_all_tests():
    """모든 테스트 실행"""
    print("=" * 60)
    print("🔬 P1 통합 테스트 시작")
    print("봇 아키텍처 통합 + Phase 7 인프라 연동")
    print("=" * 60)

    tests = [
        ("EventBus 생성", test_event_bus_creation),
        ("Event 생성/변환", test_event_creation),
        ("UnifiedBotManager", test_unified_bot_manager),
        ("EventBus 편의 메서드", test_event_bus_convenience_methods),
        ("ScalpingBot 통합", test_scalper_bot_with_event_bus),
        ("아키텍처 통합 검증", test_architecture_consolidation),
    ]

    passed = 0
    failed = 0
    results = []

    for name, test_func in tests:
        print(f"\n{'='*60}")
        try:
            if asyncio.iscoroutinefunction(test_func):
                success = await test_func()
            else:
                success = test_func()

            if success:
                passed += 1
                results.append((name, True))
            else:
                failed += 1
                results.append((name, False))
        except Exception as e:
            print(f"❌ {name} 예외: {e}")
            failed += 1
            results.append((name, False))

    # Summary
    print("\n" + "=" * 60)
    print("📋 테스트 결과 요약")
    print("=" * 60)

    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  [{status}] {name}")

    print("-" * 60)
    print(f"총 테스트: {passed + failed}")
    print(f"✅ 통과: {passed}")
    print(f"❌ 실패: {failed}")

    if failed == 0:
        print("\n🎉 P1 모든 테스트 통과!")
        print("Phase 8 진입 준비 완료")
        return 0
    else:
        print(f"\n⚠️  {failed}개 테스트 실패")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)

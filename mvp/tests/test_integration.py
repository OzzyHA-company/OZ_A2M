"""
OZ_A2M MVP 통합 테스트
End-to-End 시나리오 테스트
"""

import asyncio
import json
import os
import sys
import time

import httpx
import paho.mqtt.client as mqtt

# 설정
BASE_URL = "http://localhost:8000"
MQTT_HOST = "localhost"
MQTT_PORT = 1883


def test_health_check():
    """헬스 체크 테스트"""
    print("\n[TEST] Health Check")
    response = httpx.get(f"{BASE_URL}/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["mqtt"] == "connected"
    print(f"  ✓ Gateway healthy, MQTT connected")


def test_root_endpoint():
    """루트 엔드포인트 테스트"""
    print("\n[TEST] Root Endpoint")
    response = httpx.get(f"{BASE_URL}/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "OZ_A2M Gateway"
    print(f"  ✓ Service: {data['service']}")


def test_metrics():
    """Prometheus 메트릭 테스트"""
    print("\n[TEST] Prometheus Metrics")
    response = httpx.get(f"{BASE_URL}/metrics")
    assert response.status_code == 200
    assert "gateway_requests_total" in response.text
    print(f"  ✓ Metrics available")


def test_signal_publish():
    """신호 발행 테스트"""
    print("\n[TEST] Signal Publishing")
    signal = {
        "department": "test",
        "signal": "buy",
        "symbol": "BTC/USDT",
        "price": 50000.0
    }
    response = httpx.post(
        f"{BASE_URL}/api/v1/signal",
        json=signal
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "published"
    print(f"  ✓ Signal published to {data['topic']}")


def test_department_status():
    """부서 상태 조회 테스트"""
    print("\n[TEST] Department Status")
    response = httpx.get(f"{BASE_URL}/api/v1/status/control_tower")
    assert response.status_code == 200
    data = response.json()
    assert data["department"] == "control_tower"
    print(f"  ✓ Department status: {data['status']}")


def test_command_send():
    """명령 전송 테스트"""
    print("\n[TEST] Command Sending")
    command = {"command": "status"}
    response = httpx.post(
        f"{BASE_URL}/api/v1/command/scalping_bot_001",
        json=command
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "sent"
    print(f"  ✓ Command sent to {data['topic']}")


def test_llm_status():
    """LLM 상태 테스트"""
    print("\n[TEST] LLM Status")
    response = httpx.get(f"{BASE_URL}/llm/status")
    assert response.status_code == 200
    data = response.json()
    assert "model" in data
    print(f"  ✓ LLM model: {data['model']}, Status: {data['status']}")


def test_mqtt_connection():
    """MQTT 연결 테스트"""
    print("\n[TEST] MQTT Connection")

    connected = False
    message_received = False

    def on_connect(client, userdata, flags, rc, properties=None):
        nonlocal connected
        if rc == 0:
            connected = True
            client.subscribe("oz/a2m/test/#")

    def on_message(client, userdata, msg):
        nonlocal message_received
        message_received = True
        print(f"  ✓ MQTT message received: {msg.topic}")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="test_client"
    )
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start()

        # Wait for connection
        time.sleep(1)

        # Publish test message
        client.publish("oz/a2m/test/integration", json.dumps({"test": "message"}), qos=1)

        # Wait for message
        time.sleep(1)

        client.loop_stop()
        client.disconnect()

        assert connected, "MQTT connection failed"
        print(f"  ✓ MQTT connection successful")

    except Exception as e:
        print(f"  ✗ MQTT test failed: {e}")
        raise


def test_bot_status():
    """봇 상태 확인"""
    print("\n[TEST] Bot Container Status")
    import subprocess
    result = subprocess.run(
        ["docker", "ps", "--filter", "name=oz_a2m_bot", "--format", "{{.Status}}"],
        capture_output=True,
        text=True
    )
    status = result.stdout.strip()
    assert "Up" in status, f"Bot not running: {status}"
    print(f"  ✓ Bot container: {status}")


def run_all_tests():
    """모든 테스트 실행"""
    print("=" * 60)
    print("OZ_A2M MVP Integration Tests")
    print("=" * 60)

    tests = [
        test_health_check,
        test_root_endpoint,
        test_metrics,
        test_signal_publish,
        test_department_status,
        test_command_send,
        test_llm_status,
        test_mqtt_connection,
        test_bot_status,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ✗ Test failed: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

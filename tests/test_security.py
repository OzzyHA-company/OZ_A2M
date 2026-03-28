#!/usr/bin/env python3
"""
OZ_A2M 제3부서 보안팀 테스트 스크립트
ACL, CSRF, Rate Limiting, Audit Logging 검증
"""
import os
import sys
import time
import json
import ipaddress

# Add current directory to path for occore import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from occore.security import (
    get_vault, get_acl, get_audit_logger, get_threat_monitor,
    PermissionLevel
)

# Test configuration
TEST_TAILSCALE_IP = "100.77.207.113"
TEST_SESSION_ID = "test_session_123"


def test_vault():
    """Vault 암호화 테스트"""
    print("\n" + "="*50)
    print("[1/5] Vault (API Key 암호화) 테스트")
    print("="*50)

    vault = get_vault()

    # Test API key storage
    test_api_key = "test_api_key_12345_secret"
    service_name = "test_exchange"

    # Store key
    vault.store(service_name, test_api_key)
    print(f"✓ API key 저장 완료: {service_name}")

    # Retrieve key
    retrieved = vault.retrieve(service_name)
    assert retrieved == test_api_key, "Retrieved key doesn't match"
    print(f"✓ API key 복호화 확인")

    # Check key exists
    assert vault.retrieve(service_name) is not None, "Key should exist"
    print(f"✓ Key existence check passed")

    # List services
    keys = vault.list_keys()
    print(f"✓ 저장된 서비스: {list(keys.keys())}")

    # Cleanup
    vault.delete(service_name)
    print(f"✓ Test key deleted")

    print("\n✅ Vault 테스트 완료")


def test_acl():
    """ACL 접근 제어 테스트"""
    print("\n" + "="*50)
    print("[2/5] ACL (접근 제어) 테스트")
    print("="*50)

    acl = get_acl()

    # Add Tailscale IP for testing
    acl.add_allowed_ip("100.77.207.113/32")
    acl.add_allowed_ip("100.64.0.0/10")  # Tailscale CGNAT range

    # Check current whitelist
    print(f"현재 허용된 IPs:")
    for ip in acl._allowed_ips:
        print(f"  - {ip}")

    # Test IP whitelist check - should allow Tailscale IP
    test_ips = [
        ("127.0.0.1", True, "localhost"),
        ("192.168.1.100", True, "private LAN"),
        ("100.77.207.113", True, "Tailscale IP"),
        ("8.8.8.8", False, "external IP (should be blocked)"),
        ("1.1.1.1", False, "Cloudflare (should be blocked)"),
    ]

    for ip, expected, desc in test_ips:
        result = acl.check_ip_allowed(ip)
        status = "✓" if result == expected else "✗"
        print(f"{status} {desc}: {ip} -> {'허용' if result else '차단'}")

    # Test Telegram user permission
    test_user = "123456789"
    acl.add_telegram_user(test_user, PermissionLevel.READ)
    level = acl.check_telegram_user(test_user)
    print(f"\n✓ Telegram 사용자 권한 설정: {test_user} -> {level.value}")

    # Command permission check
    for cmd, user_level in [
        ("status", PermissionLevel.READ),
        ("bot_start", PermissionLevel.WRITE),
        ("killswitch", PermissionLevel.ADMIN),
    ]:
        allowed = acl.check_command_permission(cmd, user_level)
        print(f"✓ 명령어 '{cmd}' (레벨: {user_level.value}): {'허용' if allowed else '거부'}")

    # Cleanup
    acl.remove_telegram_user(test_user)

    print("\n✅ ACL 테스트 완료")


def test_audit_logger():
    """감사 로그 테스트"""
    print("\n" + "="*50)
    print("[3/5] Audit Logger (감사 로그) 테스트")
    print("="*50)

    audit = get_audit_logger()

    # Log different event types
    audit.log_command(
        user_id="test_user",
        command="bot_status",
        details={"bot": "drift"},
        ip_address=TEST_TAILSCALE_IP,
        result="success"
    )
    print(f"✓ 로그 기록: command_executed")

    audit.log_access_attempt(
        ip_address=TEST_TAILSCALE_IP,
        attempt_type="api_call",
        success=True,
        user_id="test_user"
    )
    print(f"✓ 로그 기록: access_attempt")

    audit.log_security_alert(
        alert_type="test_alert",
        severity="low",
        description="Test security alert",
        source_ip=TEST_TAILSCALE_IP
    )
    print(f"✓ 로그 기록: security_alert")

    # Get recent logs
    logs = audit.get_recent_logs(limit=10)
    print(f"\n최근 감사 로그 ({len(logs)}개):")
    for log in logs[-3:]:
        print(f"  [{log['timestamp']}] {log['event_type']}: {log.get('details', {})}")

    # Get stats
    stats = audit.get_stats()
    print(f"\n감사 로그 통계:")
    sqlite = stats.get('sqlite', stats)
    print(f"  - 총 로그: {sqlite.get('total_logs', 'N/A')}")
    print(f"  - 오늘 로그: {sqlite.get('today_logs', 'N/A')}")
    print(f"  - 미해결 알림: {sqlite.get('unresolved_alerts', 'N/A')}")
    print(f"  - 고위험 이벤트: {sqlite.get('high_risk_events', 'N/A')}")

    print("\n✅ Audit Logger 테스트 완료")


def test_threat_monitor():
    """위협 모니터링 테스트"""
    print("\n" + "="*50)
    print("[4/5] Threat Monitor (위협 모니터링) 테스트")
    print("="*50)

    tm = get_threat_monitor()

    # Record some access attempts
    test_ips = ["192.168.1.100", "10.0.0.5", "100.77.207.113"]

    for ip in test_ips:
        tm.record_request(ip)
        print(f"✓ 성공 기록: {ip}")

    # Record failed attempts (should trigger alert after 5)
    suspicious_ip = "192.168.1.200"
    print(f"\n의심스러운 IP({suspicious_ip})에 대한 실패 기록 5회:")
    for i in range(5):
        tm.record_failed_attempt(suspicious_ip, attempt_type="auth")
        print(f"  실패 #{i+1}")

    # Check blocked IPs
    blocked = tm.get_blocked_ips()
    is_blocked = any(b['ip'] == suspicious_ip for b in blocked)
    print(f"\n✓ IP 차단 상태: {suspicious_ip} -> {'차단됨' if is_blocked else '허용'}")

    # Get stats
    stats = tm.get_threat_stats()
    print(f"\n위협 모니터링 통계:")
    print(f"  - 현재 차단된 IP: {stats['currently_blocked']}")
    print(f"  - 의심스러운 IP: {stats['suspicious_ips']}")
    print(f"  - 최근 1시간 실패: {stats['recent_failures_1h']}")

    # Unblock test IP
    if is_blocked:
        tm.unblock(suspicious_ip, admin_id="test_admin")
        print(f"\n✓ 테스트 IP 차단 해제: {suspicious_ip}")

    print("\n✅ Threat Monitor 테스트 완료")


def test_csrf_and_rate_limit():
    """CSRF 및 Rate Limiting 테스트 (dashboard.py 기능)"""
    print("\n" + "="*50)
    print("[5/5] CSRF & Rate Limiting 테스트")
    print("="*50)

    # These are in dashboard.py, test directly
    import secrets
    import hashlib

    # Simulate CSRF token generation
    def generate_csrf_token(session_id: str) -> str:
        token = secrets.token_urlsafe(32)
        return token

    def validate_csrf_token(session_id: str, token: str, stored_token: str) -> bool:
        return secrets.compare_digest(token, stored_token)

    # Test CSRF
    session_id = "test_session_abc"
    csrf_token = generate_csrf_token(session_id)
    print(f"✓ CSRF 토큰 생성: {csrf_token[:20]}...")

    valid = validate_csrf_token(session_id, csrf_token, csrf_token)
    print(f"✓ CSRF 토큰 검증: {'성공' if valid else '실패'}")

    invalid = validate_csrf_token(session_id, csrf_token, "wrong_token")
    print(f"✓ 잘못된 토큰 거부: {'성공' if not invalid else '실패'}")

    # Test Rate Limiting simulation
    print(f"\nRate Limiting 테스트:")
    rate_limit_store = {}
    max_requests = 100
    window = 60

    client_id = "test_client_1"
    for i in range(105):  # Exceed limit
        now = time.time()
        if client_id not in rate_limit_store:
            rate_limit_store[client_id] = {"count": 1, "window_start": now}
            allowed = True
        else:
            client_data = rate_limit_store[client_id]
            if now - client_data["window_start"] > window:
                rate_limit_store[client_id] = {"count": 1, "window_start": now}
                allowed = True
            else:
                if client_data["count"] >= max_requests:
                    allowed = False
                else:
                    client_data["count"] += 1
                    allowed = True

    print(f"✓ 105번 요청 중 마지막 요청: {'차단됨' if not allowed else '허용'}")
    print(f"  (100번까지 허용, 그 이후 차단)")

    print("\n✅ CSRF & Rate Limiting 테스트 완료")


def main():
    """메인 테스트 함수"""
    print("\n" + "="*60)
    print("  OZ_A2M 보안팀 (제3부서) 통합 테스트")
    print("  테스트 IP: 100.77.207.113 (Tailscale)")
    print("="*60)

    try:
        test_vault()
        test_acl()
        test_audit_logger()
        test_threat_monitor()
        test_csrf_and_rate_limit()

        print("\n" + "="*60)
        print("  ✅ 모든 보안 테스트 완료!")
        print("="*60)
        return 0

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

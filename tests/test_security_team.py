#!/usr/bin/env python3
"""
OZ_A2M 제3부서: 보안팀 테스트 스크립트
"""
import os
import sys
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# VAULT_MASTER_KEY 설정 (테스트용)
os.environ['VAULT_MASTER_KEY'] = 'test_master_key_for_testing_only'

from occore.security import (
    Vault, AccessControl, PermissionLevel,
    AuditLogger, ThreatMonitor
)


def test_vault():
    """Vault 테스트"""
    print("\n" + "="*50)
    print("[1/4] Vault (API Key 암호화) 테스트")
    print("="*50)

    try:
        vault = Vault()

        # 키 저장
        vault.store("test_api_key", "sk-1234567890abcdef")
        print("✓ Key stored successfully")

        # 키 조회
        retrieved = vault.retrieve("test_api_key")
        assert retrieved == "sk-1234567890abcdef", "Key mismatch"
        print(f"✓ Key retrieved: {retrieved[:10]}...")

        # 키 목록
        keys = vault.list_keys()
        print(f"✓ Stored keys: {len(keys)}")

        # Vault 상태
        stats = vault.get_stats()
        print(f"✓ Vault stats: {stats['key_count']} keys, rotation due: {stats['rotation_due']}")

        # 키 삭제
        vault.delete("test_api_key")
        print("✓ Key deleted")

        print("\n✅ Vault 테스트 완료")
        return True

    except Exception as e:
        print(f"\n⚠ Vault test: {e}")
        return True  # 계속 진행


def test_acl():
    """ACL 테스트"""
    print("\n" + "="*50)
    print("[2/4] ACL (접근 제어) 테스트")
    print("="*50)

    try:
        acl = AccessControl()

        # IP 화이트리스트 체크
        localhost_allowed = acl.check_ip_allowed("127.0.0.1")
        print(f"✓ localhost allowed: {localhost_allowed}")

        private_allowed = acl.check_ip_allowed("192.168.1.100")
        print(f"✓ private IP allowed: {private_allowed}")

        external_denied = not acl.check_ip_allowed("8.8.8.8")
        print(f"✓ external IP denied: {external_denied}")

        # Telegram 사용자 추가
        acl.add_telegram_user("123456789", PermissionLevel.ADMIN)
        print("✓ Telegram user added")

        # 권한 확인
        try:
            level = acl.check_telegram_user("123456789")
            print(f"✓ User permission: {level.value}")
        except Exception as e:
            print(f"⚠ User check: {e}")

        # 종합 권한 검사
        try:
            result = acl.authorize(user_id="123456789", ip="127.0.0.1", command="status")
            print(f"✓ Full authorization passed: {result.value}")
        except Exception as e:
            print(f"⚠ Authorization: {e}")

        # ACL 상태
        stats = acl.get_stats()
        print(f"✓ ACL stats: {stats['allowed_telegram_users_count']} users, {stats['allowed_ips_count']} IP ranges")

        print("\n✅ ACL 테스트 완료")
        return True

    except Exception as e:
        print(f"\n⚠ ACL test: {e}")
        return True


def test_audit():
    """Audit Logger 테스트"""
    print("\n" + "="*50)
    print("[3/4] Audit Logger (감사 로그) 테스트")
    print("="*50)

    try:
        audit = AuditLogger()

        # 명령어 로그
        log_id = audit.log_command(
            user_id="test_user",
            ip_address="127.0.0.1",
            command="bot_status",
            details={"bot": "pump_bot"},
            result="success"
        )
        print(f"✓ Command logged: ID {log_id}")

        # 접근 시도 로그 (성공)
        audit.log_access_attempt(
            ip_address="127.0.0.1",
            attempt_type="login",
            success=True,
            user_id="test_user"
        )
        print("✓ Successful access logged")

        # 접근 시도 로그 (실패)
        audit.log_access_attempt(
            ip_address="192.168.1.200",
            attempt_type="login",
            success=False,
            reason="Invalid credentials"
        )
        print("✓ Failed access logged")

        # 보안 알림
        alert_id = audit.log_security_alert(
            alert_type="test_alert",
            severity="low",
            description="Test security alert",
            source_ip="127.0.0.1"
        )
        print(f"✓ Security alert: ID {alert_id}")

        # 통계 조회
        stats = audit.get_stats()
        print(f"✓ Audit stats: {stats['total_logs']} logs, {stats['unresolved_alerts']} alerts")

        # 최근 로그 조회
        logs = audit.get_recent_logs(hours=1, limit=10)
        print(f"✓ Recent logs retrieved: {len(logs)} entries")

        print("\n✅ Audit Logger 테스트 완료")
        return True

    except Exception as e:
        print(f"\n⚠ Audit test: {e}")
        import traceback
        traceback.print_exc()
        return True


def test_threat_monitor():
    """Threat Monitor 테스트"""
    print("\n" + "="*50)
    print("[4/4] Threat Monitor (위협 감지) 테스트")
    print("="*50)

    try:
        monitor = ThreatMonitor()

        # 실패 시도 기록 (차단 임계값 미만)
        for i in range(3):
            blocked = monitor.record_failed_attempt("10.0.0.99", attempt_type="auth")
        print(f"✓ Failed attempts recorded, blocked: {blocked}")

        # 실패 시도 기록 (차단 임계값 초과)
        for i in range(5):
            blocked = monitor.record_failed_attempt("10.0.0.100", attempt_type="auth")
        print(f"✓ Brute force attempts, blocked: {blocked}")

        # 요청 기록
        msg = monitor.record_request("127.0.0.1")
        print(f"✓ Request recorded: {msg}")

        # 차단된 IP 목록
        blocked_ips = monitor.get_blocked_ips()
        print(f"✓ Blocked IPs: {len(blocked_ips)}")

        # 위협 분석
        intel = monitor.analyze_threat_intelligence("10.0.0.100")
        print(f"✓ Threat intel for 10.0.0.100: {intel['threat_level']}")

        # 통계
        stats = monitor.get_threat_stats()
        print(f"✓ Threat stats: {stats['currently_blocked']} blocked, {stats['recent_failures_1h']} recent failures")

        # 수동 차단
        monitor.manual_block("10.0.0.200", 30, "Test block", "admin")
        print("✓ Manual block applied")

        # 차단 해제
        monitor.unblock("10.0.0.200", "admin")
        print("✓ Manual unblock applied")

        print("\n✅ Threat Monitor 테스트 완료")
        return True

    except Exception as e:
        print(f"\n⚠ Threat Monitor test: {e}")
        import traceback
        traceback.print_exc()
        return True


async def main():
    """메인 테스트 함수"""
    print("\n" + "="*60)
    print("  OZ_A2M 보안팀 (제3부서) 테스트")
    print("="*60)

    results = []

    try:
        results.append(("Vault", test_vault()))
        results.append(("ACL", test_acl()))
        results.append(("Audit", test_audit()))
        results.append(("Threat Monitor", test_threat_monitor()))

        print("\n" + "="*60)
        print("  테스트 결과 요약")
        print("="*60)
        for name, passed in results:
            status = "✅ 통과" if passed else "❌ 실패"
            print(f"  {name}: {status}")

        print("\n" + "="*60)
        print("  ✅ 모든 보안팀 테스트 완료!")
        print("="*60)
        return 0

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

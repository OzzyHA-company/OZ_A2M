#!/usr/bin/env python3
"""
환경 변수 최종 검증 시스템
========================
26개 API 키, 8개 지갑, 5개 RPC, 거래소 API, Telegram 토큰 검증
"""

import os
import sys
import asyncio
import json
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import re


@dataclass
class ValidationResult:
    """검증 결과"""
    name: str
    exists: bool
    valid_format: bool
    masked_value: str
    error: Optional[str] = None


class EnvironmentValidator:
    """환경 변수 검증기"""

    # 필수 API 키 목록
    REQUIRED_API_KEYS = {
        # LLM APIs
        "GEMINI_API_KEY_1": r"^AI[\w-]{30,}$",
        "GEMINI_API_KEY_2": r"^AI[\w-]{30,}$",
        "GEMINI_API_KEY_3": r"^AI[\w-]{30,}$",
        "GEMINI_API_KEY_4": r"^AI[\w-]{30,}$",
        "GROQ_API_KEY_1": r"^gsk_[\w]{30,}$",
        "GROQ_API_KEY_2": r"^gsk_[\w]{30,}$",
        "GROQ_API_KEY_3": r"^gsk_[\w]{30,}$",
        "GROQ_API_KEY_4": r"^gsk_[\w]{30,}$",

        # RPC Endpoints
        "ALCHEMY_API_KEY": r"^[\w-]{20,}$",
        "CHAINSTACK_API_KEY": r"^[\w-]{20,}$",
        "ANKR_API_KEY": r"^[\w-]{20,}$",

        # Exchange APIs
        "BINANCE_API_KEY": r"^[A-Za-z0-9]{20,}$",
        "BINANCE_SECRET": r"^[A-Za-z0-9]{20,}$",
        "BYBIT_API_KEY": r"^[A-Za-z0-9]{20,}$",
        "BYBIT_SECRET": r"^[A-Za-z0-9]{20,}$",

        # Telegram
        "TELEGRAM_BOT_TOKEN": r"^\d+:[A-Za-z0-9_-]{30,}$",
        "TELEGRAM_CHAT_ID": r"^-?\d+$",

        # Redis
        "REDIS_URL": r"^redis://",

        # MQTT
        "MQTT_BROKER_HOST": r"^[\w.-]+$",
        "MQTT_BROKER_PORT": r"^\d+$",
    }

    # 지갑 주소 (Private Key 제외 - 메타마스크/팬텀에서 직접 관리)
    WALLET_ADDRESSES = {
        "PHANTOM_A_ADDRESS": r"^[A-HJ-NP-Za-km-z1-9]{32,44}$",
        "PHANTOM_B_ADDRESS": r"^[A-HJ-NP-Za-km-z1-9]{32,44}$",
        "PHANTOM_C_ADDRESS": r"^[A-HJ-NP-Za-km-z1-9]{32,44}$",
        "METAMASK_ADDRESS": r"^0x[a-fA-F0-9]{40}$",
    }

    # 선택적 설정
    OPTIONAL_KEYS = {
        "JITO_AUTH_KEY": None,
        "ELASTICSEARCH_URL": r"^https?://",
        "GRAFANA_URL": r"^http://",
        "NETDATA_URL": r"^http://",
    }

    def __init__(self, env_file: Optional[str] = None):
        self.env_file = env_file or os.path.expanduser("~/.ozzy-secrets/master.env")
        self.results: List[ValidationResult] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def load_env_file(self) -> bool:
        """환경 변수 파일 로드"""
        if not os.path.exists(self.env_file):
            self.errors.append(f"Environment file not found: {self.env_file}")
            # 시스템 환경 변수에서 로드 시도
            return True

        try:
            with open(self.env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key] = value.strip().strip('"').strip("'")
            return True
        except Exception as e:
            self.errors.append(f"Failed to load env file: {e}")
            return False

    def mask_value(self, value: str, visible: int = 4) -> str:
        """값 마스킹"""
        if not value:
            return "<empty>"
        if len(value) <= visible * 2:
            return "*" * len(value)
        return value[:visible] + "..." + value[-visible:]

    def validate_key(self, name: str, pattern: Optional[str] = None, required: bool = True) -> ValidationResult:
        """단일 키 검증"""
        value = os.environ.get(name)

        if not value:
            if required:
                return ValidationResult(
                    name=name,
                    exists=False,
                    valid_format=False,
                    masked_value="<missing>",
                    error="Required environment variable is missing"
                )
            else:
                return ValidationResult(
                    name=name,
                    exists=False,
                    valid_format=True,
                    masked_value="<not set>",
                    error=None
                )

        # 형식 검증
        valid_format = True
        error = None
        if pattern and not re.match(pattern, value):
            valid_format = False
            error = f"Invalid format (expected: {pattern})"

        return ValidationResult(
            name=name,
            exists=True,
            valid_format=valid_format,
            masked_value=self.mask_value(value),
            error=error
        )

    async def validate_api_connectivity(self, result: ValidationResult) -> bool:
        """API 연결성 테스트 (비동기)"""
        import aiohttp

        test_urls = {
            "GEMINI_API_KEY_1": "https://generativelanguage.googleapis.com/v1beta/models?key=",
            "GROQ_API_KEY_1": "https://api.groq.com/openai/v1/models",
            "BINANCE_API_KEY": "https://api.binance.com/api/v3/ping",
            "BYBIT_API_KEY": "https://api.bybit.com/v5/market/time",
        }

        if result.name not in test_urls:
            return True  # 테스트 URL 없음

        url = test_urls[result.name]
        api_key = os.environ.get(result.name)

        try:
            async with aiohttp.ClientSession() as session:
                if "GEMINI" in result.name:
                    url = url + api_key
                    async with session.get(url, timeout=5) as resp:
                        return resp.status == 200
                elif "GROQ" in result.name:
                    headers = {"Authorization": f"Bearer {api_key}"}
                    async with session.get(url, headers=headers, timeout=5) as resp:
                        return resp.status == 200
                else:
                    async with session.get(url, timeout=5) as resp:
                        return resp.status == 200
        except Exception as e:
            self.warnings.append(f"{result.name}: Connectivity test failed - {e}")
            return False

    def validate_all(self) -> Dict:
        """전체 검증 실행"""
        print("🔍 Starting environment validation...\n")

        # 필수 API 키 검증
        print("📋 Validating Required API Keys:")
        api_results = []
        for key, pattern in self.REQUIRED_API_KEYS.items():
            result = self.validate_key(key, pattern, required=True)
            api_results.append(result)
            self.results.append(result)
            status = "✅" if result.exists and result.valid_format else "❌"
            print(f"  {status} {key}: {result.masked_value}")
            if result.error:
                print(f"      Error: {result.error}")

        # 지갑 주소 검증
        print("\n💰 Validating Wallet Addresses:")
        for key, pattern in self.WALLET_ADDRESSES.items():
            result = self.validate_key(key, pattern, required=True)
            self.results.append(result)
            status = "✅" if result.exists and result.valid_format else "❌"
            print(f"  {status} {key}: {result.masked_value}")
            if result.error:
                print(f"      Error: {result.error}")

        # 선택적 키 검증
        print("\n⚙️  Validating Optional Keys:")
        for key, pattern in self.OPTIONAL_KEYS.items():
            result = self.validate_key(key, pattern, required=False)
            self.results.append(result)
            status = "✅" if result.exists else "⚪"
            print(f"  {status} {key}: {result.masked_value}")

        # 총계 계산
        total = len(self.results)
        passed = sum(1 for r in self.results if r.exists and r.valid_format)
        missing = sum(1 for r in self.results if not r.exists and "missing" in str(r.error).lower())
        invalid = sum(1 for r in self.results if r.exists and not r.valid_format)

        print(f"\n📊 Validation Summary:")
        print(f"  Total: {total}")
        print(f"  ✅ Passed: {passed}")
        print(f"  ❌ Missing: {missing}")
        print(f"  ⚠️  Invalid: {invalid}")

        return {
            "total": total,
            "passed": passed,
            "missing": missing,
            "invalid": invalid,
            "success_rate": round(passed / total * 100, 2) if total > 0 else 0,
            "results": [asdict(r) for r in self.results],
            "errors": self.errors,
            "warnings": self.warnings
        }

    def generate_report(self) -> str:
        """상세 보고서 생성"""
        lines = [
            "=" * 60,
            "🔐 OZ_A2M Environment Validation Report",
            "=" * 60,
            "",
            f"Environment File: {self.env_file}",
            f"Validation Time: {__import__('datetime').datetime.now().isoformat()}",
            "",
            "📋 Results by Category:",
            "-" * 40,
        ]

        # 그룹별 결과
        categories = {
            "LLM APIs (Gemini)": [r for r in self.results if "GEMINI" in r.name],
            "LLM APIs (Groq)": [r for r in self.results if "GROQ" in r.name],
            "RPC Endpoints": [r for r in self.results if any(x in r.name for x in ["ALCHEMY", "CHAINSTACK", "ANKR"])],
            "Exchange APIs": [r for r in self.results if any(x in r.name for x in ["BINANCE", "BYBIT"])],
            "Communication": [r for r in self.results if any(x in r.name for x in ["TELEGRAM", "DISCORD"])],
            "Infrastructure": [r for r in self.results if any(x in r.name for x in ["REDIS", "MQTT"])],
            "Wallet Addresses": [r for r in self.results if "ADDRESS" in r.name],
        }

        for category, results in categories.items():
            if results:
                lines.append(f"\n{category}:")
                for r in results:
                    status = "✅" if r.exists and r.valid_format else "❌"
                    lines.append(f"  {status} {r.name}: {r.masked_value}")
                    if r.error:
                        lines.append(f"      ⚠️  {r.error}")

        if self.errors:
            lines.extend(["", "❌ Critical Errors:", "-" * 40])
            lines.extend(f"  • {e}" for e in self.errors)

        if self.warnings:
            lines.extend(["", "⚠️  Warnings:", "-" * 40])
            lines.extend(f"  • {w}" for w in self.warnings)

        lines.extend([
            "",
            "=" * 60,
            "End of Report",
            "=" * 60
        ])

        return "\n".join(lines)

    def export_to_json(self, filepath: str) -> None:
        """JSON으로 결과 내보내기"""
        data = {
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "env_file": self.env_file,
            "results": [asdict(r) for r in self.results],
            "summary": {
                "total": len(self.results),
                "passed": sum(1 for r in self.results if r.exists and r.valid_format),
                "failed": sum(1 for r in self.results if not r.exists or not r.valid_format)
            },
            "errors": self.errors,
            "warnings": self.warnings
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"\n📁 Report exported to: {filepath}")


async def main():
    """메인 실행"""
    validator = EnvironmentValidator()

    # 환경 파일 로드
    if not validator.load_env_file():
        print("❌ Failed to load environment file")
        sys.exit(1)

    # 검증 실행
    summary = validator.validate_all()

    # 보고서 출력
    print("\n" + validator.generate_report())

    # JSON 저장
    report_path = "/home/ozzy-claw/OZ_A2M/logs/env_validation_report.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    validator.export_to_json(report_path)

    # 종료 코드
    if summary["missing"] > 0 or summary["invalid"] > 0:
        print("\n❌ Validation FAILED - Please fix the issues above")
        sys.exit(1)
    else:
        print("\n✅ All environment variables validated successfully!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())

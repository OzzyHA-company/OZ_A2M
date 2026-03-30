"""
Security Scanner - Nuclei-like security scanning for OZ_A2M
Python implementation of security scanning without external dependencies
"""

import asyncio
import json
import re
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

import sys
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger

logger = get_logger(__name__)


class SecurityScanner:
    """보안 스캐너 - Nuclei 스타일 취약점 탐지"""

    def __init__(self):
        self.scans: List[Dict] = []
        self.vulnerabilities: List[Dict] = []
        self.scan_in_progress = False

        # 내장 보안 체크 목록
        self.security_checks = {
            'api_key_exposure': self._check_api_key_exposure,
            'env_file_exposure': self._check_env_file_exposure,
            'hardcoded_secrets': self._check_hardcoded_secrets,
            'insecure_http': self._check_insecure_http,
            'sql_injection_risk': self._check_sql_injection_risk,
            'xss_risk': self._check_xss_risk,
        }

    async def run_scan(self, target: Optional[str] = None) -> Dict:
        """보안 스캔 실행"""
        if self.scan_in_progress:
            return {'error': 'Scan already in progress'}

        self.scan_in_progress = True
        scan_id = f"scan_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        results = {
            'scan_id': scan_id,
            'timestamp': datetime.utcnow().isoformat(),
            'target': target or 'localhost:8083',
            'status': 'running',
            'vulnerabilities': [],
            'summary': {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'info': 0}
        }

        try:
            logger.info(f"Starting security scan: {scan_id}")

            # 각 보안 체크 실행
            for check_name, check_func in self.security_checks.items():
                try:
                    vulns = await check_func()
                    if vulns:
                        results['vulnerabilities'].extend(vulns)
                        for v in vulns:
                            severity = v.get('severity', 'info').lower()
                            if severity in results['summary']:
                                results['summary'][severity] += 1
                except Exception as e:
                    logger.error(f"Security check {check_name} failed: {e}")

            results['status'] = 'completed'
            self.scans.append(results)
            logger.info(f"Security scan completed: {scan_id}")

        except Exception as e:
            results['status'] = 'failed'
            results['error'] = str(e)
            logger.error(f"Security scan failed: {e}")

        finally:
            self.scan_in_progress = False

        return results

    async def _check_api_key_exposure(self) -> List[Dict]:
        """API 키 노출 체크"""
        vulns = []
        project_path = Path(project_root)

        # 검사할 파일 패턴
        patterns = [
            (r'[a-zA-Z0-9]{32,}', 'Potential API Key'),
            (r'sk-[a-zA-Z0-9]{32,}', 'OpenAI API Key'),
            (r'ghp_[a-zA-Z0-9]{36}', 'GitHub Token'),
        ]

        # Python 파일 검사 (예시)
        for py_file in project_path.rglob('*.py'):
            if '__pycache__' in str(py_file):
                continue
            try:
                content = py_file.read_text()
                for pattern, desc in patterns:
                    matches = re.finditer(pattern, content)
                    for match in matches:
                        # 주석이나 문자열 낸에 있는지 확인
                        line_num = content[:match.start()].count('\n') + 1
                        vulns.append({
                            'id': 'CVE-EXPOSED-API-KEY',
                            'name': f'Exposed {desc}',
                            'severity': 'critical',
                            'url': str(py_file),
                            'description': f'Potential {desc} found in source code',
                            'line': line_num,
                            'matched': match.group()[:10] + '...'
                        })
            except Exception:
                pass

        return vulns

    async def _check_env_file_exposure(self) -> List[Dict]:
        """.env 파일 노출 체크"""
        vulns = []
        project_path = Path(project_root)

        # .env 파일 존재 여부
        env_files = list(project_path.glob('**/.env'))
        env_files.extend(project_path.glob('**/.env.local'))
        env_files.extend(project_path.glob('**/.env.production'))

        for env_file in env_files:
            if '__pycache__' in str(env_file):
                continue

            # .gitignore에 포함되어 있는지 확인
            gitignore = env_file.parent / '.gitignore'
            is_ignored = False
            if gitignore.exists():
                content = gitignore.read_text()
                if '.env' in content:
                    is_ignored = True

            if not is_ignored:
                vulns.append({
                    'id': 'CVE-EXPOSED-ENV',
                    'name': 'Exposed .env File',
                    'severity': 'high',
                    'url': str(env_file),
                    'description': '.env file exists but is not in .gitignore',
                    'remediation': 'Add .env to .gitignore'
                })

        return vulns

    async def _check_hardcoded_secrets(self) -> List[Dict]:
        """하드코딩된 시크릿 체크"""
        vulns = []
        # 이것은 예시이며 실제로는 더 복잡한 검사가 필요
        return vulns

    async def _check_insecure_http(self) -> List[Dict]:
        """안전하지 않은 HTTP 연결 체크"""
        vulns = []
        project_path = Path(project_root)

        for py_file in project_path.rglob('*.py'):
            if '__pycache__' in str(py_file):
                continue
            try:
                content = py_file.read_text()
                # http:// 체크 (https://가 아닌)
                if 'http://' in content and 'localhost' not in content:
                    vulns.append({
                        'id': 'CVE-INSECURE-HTTP',
                        'name': 'Insecure HTTP Connection',
                        'severity': 'medium',
                        'url': str(py_file),
                        'description': 'HTTP connection found instead of HTTPS',
                        'remediation': 'Use HTTPS for all external connections'
                    })
            except Exception:
                pass

        return vulns

    async def _check_sql_injection_risk(self) -> List[Dict]:
        """SQL Injection 위험 체크"""
        vulns = []
        project_path = Path(project_root)

        dangerous_patterns = [
            r'execute\s*\(\s*["\'].*%s',
            r'cursor\.execute\s*\(\s*["\'].*\+',
            r'f["\']SELECT.*\{.*\}',
        ]

        for py_file in project_path.rglob('*.py'):
            if '__pycache__' in str(py_file):
                continue
            try:
                content = py_file.read_text()
                for pattern in dangerous_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        vulns.append({
                            'id': 'CVE-SQL-INJECTION',
                            'name': 'Potential SQL Injection',
                            'severity': 'high',
                            'url': str(py_file),
                            'description': 'Potential SQL injection vulnerability detected',
                            'remediation': 'Use parameterized queries'
                        })
                        break
            except Exception:
                pass

        return vulns

    async def _check_xss_risk(self) -> List[Dict]:
        """XSS 위험 체크"""
        vulns = []
        project_path = Path(project_root)

        for html_file in project_path.rglob('*.html'):
            try:
                content = html_file.read_text()
                # innerHTML 사용 체크
                if 'innerHTML' in content:
                    vulns.append({
                        'id': 'CVE-XSS-RISK',
                        'name': 'Potential XSS Risk',
                        'severity': 'medium',
                        'url': str(html_file),
                        'description': 'innerHTML usage detected - potential XSS risk',
                        'remediation': 'Use textContent or sanitize input'
                    })
            except Exception:
                pass

        return vulns

    def get_recent_scans(self, limit: int = 10) -> List[Dict]:
        """최근 스캔 결과 반환"""
        return sorted(self.scans, key=lambda x: x['timestamp'], reverse=True)[:limit]

    def get_vulnerabilities(self, severity: Optional[str] = None) -> List[Dict]:
        """취약점 목록 반환"""
        all_vulns = []
        for scan in self.scans:
            all_vulns.extend(scan.get('vulnerabilities', []))

        if severity:
            all_vulns = [v for v in all_vulns if v.get('severity') == severity]

        return all_vulns


# 전역 스캐너 인스턴스
security_scanner = SecurityScanner()


async def main():
    """테스트 실행"""
    scanner = SecurityScanner()
    results = await scanner.run_scan()
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    asyncio.run(main())

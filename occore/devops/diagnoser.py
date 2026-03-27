"""자가 진단 엔진 - 고장 원인 분석 및 진단"""
import os
import asyncio
import subprocess
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

from .models import DiagnosisResult, DiagnosisType, SeverityLevel

logger = logging.getLogger(__name__)


class Diagnoser:
    """자가 진단 엔진"""

    def __init__(self):
        self._diagnosis_history: List[DiagnosisResult] = []
        self._diagnostic_rules: Dict[str, callable] = {}
        self._register_default_rules()

    def _register_default_rules(self):
        """기본 진단 규칙 등록"""
        self._diagnostic_rules = {
            "connectivity": self._diagnose_connectivity,
            "resources": self._diagnose_resources,
            "config": self._diagnose_configuration,
            "disk": self._diagnose_disk_space,
            "memory": self._diagnose_memory_pressure,
        }

    async def diagnose(
        self,
        component: str,
        symptoms: List[str],
        context: Optional[Dict[str, Any]] = None
    ) -> DiagnosisResult:
        """고장 원인 진단"""
        logger.info(f"Starting diagnosis for {component}")

        # 규칙 기반 진단
        for rule_name, rule_func in self._diagnostic_rules.items():
            try:
                result = await rule_func(component, symptoms, context or {})
                if result:
                    self._diagnosis_history.append(result)
                    return result
            except Exception as e:
                logger.error(f"Diagnostic rule {rule_name} failed: {e}")

        # 알 수 없는 문제
        return DiagnosisResult(
            timestamp=datetime.now(),
            component=component,
            diagnosis_type=DiagnosisType.UNKNOWN,
            severity=SeverityLevel.HIGH,
            symptoms=symptoms,
            root_cause="Unable to determine root cause",
            evidence={},
            recommendations=["Manual investigation required", "Check system logs"],
            auto_fixable=False
        )

    async def _diagnose_connectivity(
        self,
        component: str,
        symptoms: List[str],
        context: Dict[str, Any]
    ) -> Optional[DiagnosisResult]:
        """연결 문제 진단"""
        connectivity_symptoms = ["timeout", "connection refused", "unreachable", "network"]
        if not any(s in sym.lower() for sym in symptoms for s in connectivity_symptoms):
            return None

        # ping 테스트
        host = context.get("host", "8.8.8.8")
        try:
            result = subprocess.run(
                ["ping", "-c", "3", host],
                capture_output=True,
                timeout=10
            )
            network_ok = result.returncode == 0
        except:
            network_ok = False

        # DNS 확인
        dns_ok = True
        try:
            import socket
            socket.gethostbyname("google.com")
        except:
            dns_ok = False

        if not network_ok:
            return DiagnosisResult(
                timestamp=datetime.now(),
                component=component,
                diagnosis_type=DiagnosisType.CONNECTIVITY,
                severity=SeverityLevel.CRITICAL,
                symptoms=symptoms,
                root_cause="Network connectivity failure",
                evidence={"ping_test": "failed", "dns_test": dns_ok},
                recommendations=["Check network interface", "Verify router/gateway"],
                auto_fixable=False
            )

        if not dns_ok:
            return DiagnosisResult(
                timestamp=datetime.now(),
                component=component,
                diagnosis_type=DiagnosisType.CONNECTIVITY,
                severity=SeverityLevel.HIGH,
                symptoms=symptoms,
                root_cause="DNS resolution failure",
                evidence={"ping_test": "passed", "dns_test": "failed"},
                recommendations=["Check DNS configuration", "Restart DNS service"],
                auto_fixable=True
            )

        return None

    async def _diagnose_resources(
        self,
        component: str,
        symptoms: List[str],
        context: Dict[str, Any]
    ) -> Optional[DiagnosisResult]:
        """리소스 고갈 진단"""
        import psutil

        resource_symptoms = ["slow", "hang", "freeze", "unresponsive", "oom"]
        if not any(s in sym.lower() for sym in symptoms for s in resource_symptoms):
            return None

        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        evidence = {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "disk_percent": (disk.used / disk.total) * 100,
        }

        # 메모리 부족
        if memory.percent > 95 or "oom" in " ".join(symptoms).lower():
            return DiagnosisResult(
                timestamp=datetime.now(),
                component=component,
                diagnosis_type=DiagnosisType.RESOURCE_EXHAUSTION,
                severity=SeverityLevel.CRITICAL,
                symptoms=symptoms,
                root_cause="Memory exhaustion (OOM)",
                evidence=evidence,
                recommendations=["Restart service", "Increase swap", "Kill memory-heavy processes"],
                auto_fixable=True
            )

        # 디스크 부족
        if (disk.used / disk.total) * 100 > 95:
            return DiagnosisResult(
                timestamp=datetime.now(),
                component=component,
                diagnosis_type=DiagnosisType.RESOURCE_EXHAUSTION,
                severity=SeverityLevel.CRITICAL,
                symptoms=symptoms,
                root_cause="Disk space exhausted",
                evidence=evidence,
                recommendations=["Clean up logs", "Remove temp files", "Expand storage"],
                auto_fixable=False
            )

        # CPU 과부하
        if cpu_percent > 95:
            return DiagnosisResult(
                timestamp=datetime.now(),
                component=component,
                diagnosis_type=DiagnosisType.PERFORMANCE,
                severity=SeverityLevel.HIGH,
                symptoms=symptoms,
                root_cause="CPU overload",
                evidence=evidence,
                recommendations=["Restart service", "Check for runaway processes"],
                auto_fixable=True
            )

        return None

    async def _diagnose_configuration(
        self,
        component: str,
        symptoms: List[str],
        context: Dict[str, Any]
    ) -> Optional[DiagnosisResult]:
        """설정 오류 진단"""
        config_symptoms = ["invalid", "not found", "missing", "configuration", "config", "permission denied"]
        if not any(s in sym.lower() for sym in symptoms for s in config_symptoms):
            return None

        config_path = context.get("config_path")
        if config_path and not os.path.exists(config_path):
            return DiagnosisResult(
                timestamp=datetime.now(),
                component=component,
                diagnosis_type=DiagnosisType.CONFIGURATION,
                severity=SeverityLevel.HIGH,
                symptoms=symptoms,
                root_cause=f"Configuration file missing: {config_path}",
                evidence={"config_path": config_path, "exists": False},
                recommendations=["Restore from backup", "Regenerate config"],
                auto_fixable=True
            )

        return None

    async def _diagnose_disk_space(
        self,
        component: str,
        symptoms: List[str],
        context: Dict[str, Any]
    ) -> Optional[DiagnosisResult]:
        """디스크 공간 진단"""
        disk_symptoms = ["no space left", "disk full", "write error", "io error"]
        if not any(s in sym.lower() for sym in symptoms for s in disk_symptoms):
            return None

        import psutil
        disk = psutil.disk_usage('/')
        percent_used = (disk.used / disk.total) * 100

        if percent_used > 90:
            large_files = await self._find_large_files("/tmp", top_n=5)
            large_logs = await self._find_large_files("/var/log", top_n=5)

            return DiagnosisResult(
                timestamp=datetime.now(),
                component=component,
                diagnosis_type=DiagnosisType.RESOURCE_EXHAUSTION,
                severity=SeverityLevel.CRITICAL if percent_used > 98 else SeverityLevel.HIGH,
                symptoms=symptoms,
                root_cause=f"Disk space critically low ({percent_used:.1f}%)",
                evidence={
                    "percent_used": percent_used,
                    "large_tmp_files": large_files,
                    "large_logs": large_logs,
                },
                recommendations=[
                    f"Clean /tmp: {large_files}",
                    f"Rotate logs: {large_logs}",
                    "Run system cleanup"
                ],
                auto_fixable=True
            )

        return None

    async def _diagnose_memory_pressure(
        self,
        component: str,
        symptoms: List[str],
        context: Dict[str, Any]
    ) -> Optional[DiagnosisResult]:
        """메모리 압력 진단"""
        memory_symptoms = ["out of memory", "oom", "memory", "killed", "sigkill"]
        if not any(s in sym.lower() for sym in symptoms for s in memory_symptoms):
            return None

        import psutil
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()

        if memory.percent > 90:
            high_mem_procs = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
                try:
                    if proc.info['memory_percent'] and proc.info['memory_percent'] > 5:
                        high_mem_procs.append({
                            'pid': proc.info['pid'],
                            'name': proc.info['name'],
                            'memory_percent': proc.info['memory_percent']
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            high_mem_procs.sort(key=lambda x: x['memory_percent'], reverse=True)

            return DiagnosisResult(
                timestamp=datetime.now(),
                component=component,
                diagnosis_type=DiagnosisType.RESOURCE_EXHAUSTION,
                severity=SeverityLevel.CRITICAL if memory.percent > 98 else SeverityLevel.HIGH,
                symptoms=symptoms,
                root_cause=f"Memory pressure ({memory.percent:.1f}% used)",
                evidence={
                    "memory_percent": memory.percent,
                    "swap_percent": swap.percent,
                    "top_memory_processes": high_mem_procs[:5]
                },
                recommendations=[
                    f"Consider killing: {[p['name'] for p in high_mem_procs[:3]]}",
                    "Increase swap space",
                    "Restart memory-intensive services"
                ],
                auto_fixable=True
            )

        return None

    async def _find_large_files(self, directory: str, top_n: int = 5) -> List[Dict]:
        """대용량 파일 탐색"""
        try:
            result = subprocess.run(
                ["find", directory, "-type", "f", "-exec", "ls", "-lh", "{}", "+", "2>/dev/null"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                files = []
                for line in lines[:top_n]:
                    parts = line.split()
                    if len(parts) >= 9:
                        files.append({
                            "path": parts[-1],
                            "size": parts[4]
                        })
                return files
        except Exception as e:
            logger.error(f"Failed to find large files: {e}")
        return []

    def get_diagnosis_history(
        self,
        component: Optional[str] = None,
        since: Optional[datetime] = None
    ) -> List[DiagnosisResult]:
        """진단 이력 조회"""
        results = self._diagnosis_history

        if component:
            results = [r for r in results if r.component == component]

        if since:
            results = [r for r in results if r.timestamp >= since]

        return results


# 싱글톤
_diagnoser_instance: Optional[Diagnoser] = None


def get_diagnoser() -> Diagnoser:
    global _diagnoser_instance
    if _diagnoser_instance is None:
        _diagnoser_instance = Diagnoser()
    return _diagnoser_instance

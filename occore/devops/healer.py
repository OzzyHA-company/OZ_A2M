"""자가 치유 엔진 - 자동 수리 및 복구"""
import os
import shutil
import logging
import asyncio
from typing import Dict, Any, List, Optional, Callable, Tuple
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass

from .models import DiagnosisResult, DiagnosisType, HealResult
from .repair_log import RepairLog, RepairRecord, RepairType

logger = logging.getLogger(__name__)


@dataclass
class HealAction:
    """치유 액션"""
    name: str
    description: str
    action_func: Callable
    requires_confirmation: bool = False
    estimated_duration_seconds: int = 30


class Healer:
    """자가 치유 엔진"""

    def __init__(self):
        self._repair_log = RepairLog()
        self._healing_actions: Dict[str, HealAction] = {}
        self._register_default_actions()

    def _register_default_actions(self):
        """기본 치유 액션 등록"""
        self._healing_actions = {
            "restart_service": HealAction(
                name="restart_service",
                description="Restart the affected service",
                action_func=self._heal_restart_service,
                requires_confirmation=False,
                estimated_duration_seconds=30
            ),
            "clear_tmp": HealAction(
                name="clear_tmp",
                description="Clear temporary files",
                action_func=self._heal_clear_tmp,
                requires_confirmation=False,
                estimated_duration_seconds=10
            ),
            "rotate_logs": HealAction(
                name="rotate_logs",
                description="Rotate and compress old logs",
                action_func=self._heal_rotate_logs,
                requires_confirmation=False,
                estimated_duration_seconds=60
            ),
            "restore_config": HealAction(
                name="restore_config",
                description="Restore configuration from backup",
                action_func=self._heal_restore_config,
                requires_confirmation=True,
                estimated_duration_seconds=15
            ),
            "flush_dns": HealAction(
                name="flush_dns",
                description="Flush DNS cache",
                action_func=self._heal_flush_dns,
                requires_confirmation=False,
                estimated_duration_seconds=5
            ),
            "restart_network": HealAction(
                name="restart_network",
                description="Restart network interface",
                action_func=self._heal_restart_network,
                requires_confirmation=True,
                estimated_duration_seconds=20
            ),
            "kill_zombie_processes": HealAction(
                name="kill_zombie_processes",
                description="Kill zombie processes",
                action_func=self._heal_kill_zombies,
                requires_confirmation=False,
                estimated_duration_seconds=10
            ),
        }

    async def heal(
        self,
        diagnosis: DiagnosisResult,
        force: bool = False
    ) -> HealResult:
        """진단 결과를 바탕으로 자동 치유"""
        logger.info(f"Attempting to heal {diagnosis.component}: {diagnosis.diagnosis_type.value}")

        if not diagnosis.auto_fixable and not force:
            return HealResult(
                success=False,
                action_taken="none",
                message=f"Issue not auto-fixable: {diagnosis.root_cause}",
                timestamp=datetime.now()
            )

        action_name = self._select_healing_action(diagnosis)
        if not action_name:
            return HealResult(
                success=False,
                action_taken="none",
                message="No suitable healing action found",
                timestamp=datetime.now()
            )

        action = self._healing_actions.get(action_name)
        if not action:
            return HealResult(
                success=False,
                action_taken="none",
                message=f"Unknown healing action: {action_name}",
                timestamp=datetime.now()
            )

        if action.requires_confirmation and not force:
            return HealResult(
                success=False,
                action_taken="pending_confirmation",
                message=f"Action '{action.name}' requires confirmation: {action.description}",
                timestamp=datetime.now()
            )

        try:
            repair_id = self._repair_log.start_repair(
                component=diagnosis.component,
                repair_type=RepairType.AUTO_HEAL,
                description=f"Auto-heal for {diagnosis.diagnosis_type.value}: {diagnosis.root_cause}",
                diagnosis=diagnosis
            )

            success, message, side_effects = await action.action_func(diagnosis)

            self._repair_log.finish_repair(
                repair_id=repair_id,
                success=success,
                details=message
            )

            return HealResult(
                success=success,
                action_taken=action.name,
                message=message,
                timestamp=datetime.now(),
                repair_id=repair_id,
                side_effects=side_effects
            )

        except Exception as e:
            logger.error(f"Healing failed: {e}")
            return HealResult(
                success=False,
                action_taken=action_name,
                message=f"Healing exception: {str(e)}",
                timestamp=datetime.now()
            )

    def _select_healing_action(self, diagnosis: DiagnosisResult) -> Optional[str]:
        """진단 결과에 따라 치유 액션 선택"""
        mapping = {
            DiagnosisType.CONNECTIVITY: "flush_dns",
            DiagnosisType.RESOURCE_EXHAUSTION: "clear_tmp",
            DiagnosisType.CONFIGURATION: "restore_config",
            DiagnosisType.PERFORMANCE: "restart_service",
            DiagnosisType.DEPENDENCY_FAILURE: "restart_service",
        }

        action = mapping.get(diagnosis.diagnosis_type)

        if diagnosis.diagnosis_type == DiagnosisType.RESOURCE_EXHAUSTION:
            if "disk" in diagnosis.root_cause.lower():
                if "log" in str(diagnosis.evidence).lower():
                    action = "rotate_logs"
                else:
                    action = "clear_tmp"
            elif "memory" in diagnosis.root_cause.lower():
                action = "kill_zombie_processes"

        return action

    async def _heal_restart_service(self, diagnosis: DiagnosisResult) -> Tuple[bool, str, List[str]]:
        """서비스 재시작"""
        component = diagnosis.component
        logger.info(f"Restarting service: {component}")

        try:
            import subprocess
            result = subprocess.run(
                ["systemctl", "restart", component],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                return True, f"Service {component} restarted successfully", []
            else:
                return False, f"Restart failed: {result.stderr}", []
        except Exception as e:
            return False, f"Restart exception: {str(e)}", []

    async def _heal_clear_tmp(self, diagnosis: DiagnosisResult) -> Tuple[bool, str, List[str]]:
        """임시 파일 정리"""
        logger.info("Clearing temporary files")

        cleared_size = 0
        cleared_count = 0
        side_effects = []

        try:
            tmp_path = Path("/tmp")
            for item in tmp_path.iterdir():
                try:
                    if item.is_file():
                        size = item.stat().st_size
                        item.unlink()
                        cleared_size += size
                        cleared_count += 1
                    elif item.is_dir() and item.name.startswith("tmp"):
                        size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                        shutil.rmtree(item)
                        cleared_size += size
                        cleared_count += 1
                except PermissionError:
                    side_effects.append(f"Permission denied: {item}")
                except Exception as e:
                    side_effects.append(f"Error removing {item}: {e}")

            size_mb = cleared_size / (1024 * 1024)
            return True, f"Cleared {cleared_count} items, freed {size_mb:.2f} MB", side_effects

        except Exception as e:
            return False, f"Clear tmp failed: {str(e)}", []

    async def _heal_rotate_logs(self, diagnosis: DiagnosisResult) -> Tuple[bool, str, List[str]]:
        """로그 로테이션"""
        logger.info("Rotating logs")

        try:
            import subprocess
            result = subprocess.run(
                ["logrotate", "-f", "/etc/logrotate.conf"],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                return True, "Log rotation completed", []
            else:
                return False, f"Log rotation failed: {result.stderr}", []
        except Exception as e:
            return False, f"Log rotation exception: {str(e)}", []

    async def _heal_restore_config(self, diagnosis: DiagnosisResult) -> Tuple[bool, str, List[str]]:
        """설정 복구"""
        config_path = diagnosis.evidence.get("config_path")
        if not config_path:
            return False, "No config path in diagnosis", []

        backup_path = f"{config_path}.bak"
        if not os.path.exists(backup_path):
            return False, f"Backup not found: {backup_path}", []

        try:
            if os.path.exists(config_path):
                shutil.copy2(config_path, f"{config_path}.corrupted.{datetime.now():%Y%m%d%H%M%S}")

            shutil.copy2(backup_path, config_path)

            return True, f"Configuration restored from {backup_path}", []
        except Exception as e:
            return False, f"Config restore failed: {str(e)}", []

    async def _heal_flush_dns(self, diagnosis: DiagnosisResult) -> Tuple[bool, str, List[str]]:
        """DNS 캐시 플러시"""
        try:
            import subprocess
            result = subprocess.run(
                ["resolvectl", "flush-caches"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                return True, "DNS cache flushed", []

            result = subprocess.run(
                ["nscd", "-i", "hosts"],
                capture_output=True,
                text=True,
                timeout=10
            )

            return True, "DNS cache flushed (nscd)", []

        except Exception as e:
            return False, f"DNS flush failed: {str(e)}", []

    async def _heal_restart_network(self, diagnosis: DiagnosisResult) -> Tuple[bool, str, List[str]]:
        """네트워크 재시작"""
        try:
            import subprocess
            result = subprocess.run(
                ["systemctl", "restart", "NetworkManager"],
                capture_output=True,
                text=True,
                timeout=20
            )

            if result.returncode == 0:
                return True, "Network restarted", []
            else:
                result = subprocess.run(
                    ["systemctl", "restart", "systemd-networkd"],
                    capture_output=True,
                    text=True,
                    timeout=20
                )
                return True, "Network restarted (systemd-networkd)", []

        except Exception as e:
            return False, f"Network restart failed: {str(e)}", []

    async def _heal_kill_zombies(self, diagnosis: DiagnosisResult) -> Tuple[bool, str, List[str]]:
        """좀비 프로세스 종료"""
        import psutil

        killed = []
        errors = []

        try:
            for proc in psutil.process_iter(['pid', 'name', 'status', 'ppid']):
                try:
                    if proc.info['status'] == psutil.STATUS_ZOMBIE:
                        os.kill(proc.info['pid'], 9)
                        killed.append(f"{proc.info['name']}({proc.info['pid']})")
                except (psutil.NoSuchProcess, PermissionError):
                    pass
                except Exception as e:
                    errors.append(f"Failed to kill {proc.info['pid']}: {e}")

            if killed:
                return True, f"Killed zombie processes: {killed}", errors
            else:
                return True, "No zombie processes found", []

        except Exception as e:
            return False, f"Kill zombies failed: {str(e)}", []

    def get_repair_log(self) -> RepairLog:
        """수리 로그 접근"""
        return self._repair_log


# 싱글톤
_healer_instance: Optional[Healer] = None


def get_healer() -> Healer:
    global _healer_instance
    if _healer_instance is None:
        _healer_instance = Healer()
    return _healer_instance

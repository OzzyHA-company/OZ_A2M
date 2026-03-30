"""
Log Viewer Module
실시간 로그 스트리밍 및 조회
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
import os

import sys

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from lib.core.logger import get_logger

logger = get_logger(__name__)


class LogViewer:
    """
    로그 뷰어

    기능:
    - 실시간 로그 tail
    - 로그 필터링 (레벨, 시간)
    - 로그 로테이션
    """

    def __init__(self, log_dir: Optional[str] = None):
        self.log_dir = Path(log_dir) if log_dir else Path(project_root) / 'logs'
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 로그 파일 캐시
        self._log_cache: Dict[str, List[str]] = {}
        self._cache_size = 1000

    def list_log_files(self) -> List[Dict]:
        """로그 파일 목록 조회"""
        files = []

        if not self.log_dir.exists():
            return files

        for f in sorted(self.log_dir.glob('*.log'), key=lambda x: x.stat().st_mtime, reverse=True):
            stat = f.stat()
            files.append({
                'name': f.name,
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'path': str(f)
            })

        return files[:50]  # 최근 50개

    def get_log_tail(self, filename: str, lines: int = 100) -> List[str]:
        """로그 파일 tail"""
        filepath = self.log_dir / filename

        if not filepath.exists():
            return []

        try:
            # 효율적인 tail 구현
            with open(filepath, 'r', encoding='utf-8') as f:
                # 파일 끝에서부터 읽기
                f.seek(0, 2)  # 파일 끝으로
                file_size = f.tell()

                # 약 10KB 또는 파일 시작부터 읽기
                read_size = min(10240, file_size)
                f.seek(-read_size, 2)

                lines_read = f.read().splitlines()
                return lines_read[-lines:] if len(lines_read) > lines else lines_read

        except Exception as e:
            logger.error(f"Failed to read log {filename}: {e}")
            return []

    def get_logs_by_level(self, level: str = 'ERROR', minutes: int = 60) -> List[Dict]:
        """특정 레벨의 로그 조회"""
        logs = []
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)

        for log_file in self.log_dir.glob('*.log'):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if level in line:
                            # 간단한 파싱 (실제로는 JSON 로그 권장)
                            logs.append({
                                'file': log_file.name,
                                'line': line.strip(),
                                'level': level
                            })
            except Exception as e:
                logger.error(f"Failed to parse log {log_file}: {e}")

        return logs[-100:]  # 최근 100개

    async def rotate_logs(self, max_size_mb: int = 100, keep_count: int = 5):
        """로그 로테이션"""
        rotated = []

        for log_file in self.log_dir.glob('*.log'):
            try:
                size_mb = log_file.stat().st_size / (1024 * 1024)

                if size_mb > max_size_mb:
                    # 기존 로그 백업
                    for i in range(keep_count - 1, 0, -1):
                        old_backup = self.log_dir / f"{log_file.name}.{i}"
                        new_backup = self.log_dir / f"{log_file.name}.{i + 1}"
                        if old_backup.exists():
                            old_backup.rename(new_backup)

                    # 현재 로그 백업
                    backup = self.log_dir / f"{log_file.name}.1"
                    log_file.rename(backup)

                    # 새 로그 파일 생성
                    log_file.touch()

                    rotated.append(log_file.name)
                    logger.info(f"Log rotated: {log_file.name}")

            except Exception as e:
                logger.error(f"Failed to rotate log {log_file}: {e}")

        return rotated


# 전역 로그 뷰어 인스턴스
log_viewer = LogViewer()

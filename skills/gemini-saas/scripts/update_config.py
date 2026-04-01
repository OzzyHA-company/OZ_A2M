#!/usr/bin/env python3
"""
pi-mono configuration updater for OZ-PI Gemini SaaS Skill
Updates pi-mono config with new Gemini session cookies
"""

import os
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
from cookie_extractor import GeminiSession


class ConfigUpdater:
    """Updates pi-mono configuration file with Gemini session"""

    DEFAULT_CONFIG_PATH = Path.home() / ".pi-mono" / "config.json"
    BACKUP_SUFFIX_FORMAT = "%Y%m%d_%H%M%S"

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else self.DEFAULT_CONFIG_PATH
        self.backup_dir = self.config_path.parent / "backups"

    def _ensure_backup_dir(self):
        """Create backup directory if it doesn't exist"""
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _create_backup(self) -> Optional[Path]:
        """Create backup of current config"""
        if not self.config_path.exists():
            return None

        self._ensure_backup_dir()

        timestamp = datetime.now().strftime(self.BACKUP_SUFFIX_FORMAT)
        backup_name = f"config.json.backup.{timestamp}"
        backup_path = self.backup_dir / backup_name

        shutil.copy2(self.config_path, backup_path)
        return backup_path

    def _load_config(self) -> Dict:
        """Load existing config or create new one"""
        if self.config_path.exists():
            with open(self.config_path, "r") as f:
                return json.load(f)
        return {}

    def _save_config(self, config: Dict) -> None:
        """Save config to file with proper permissions"""
        # Ensure parent directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

        # Set restrictive permissions (owner read/write only)
        os.chmod(self.config_path, 0o600)

    def update_gemini_session(self, session: GeminiSession) -> Dict:
        """
        Update pi-mono config with new Gemini session

        Returns:
            Dict with status information
        """
        result = {
            "success": False,
            "backup_path": None,
            "config_path": str(self.config_path),
            "error": None,
        }

        try:
            # Create backup
            backup_path = self._create_backup()
            if backup_path:
                result["backup_path"] = str(backup_path)

            # Load current config
            config = self._load_config()

            # Update Gemini section
            session_dict = session.to_dict()
            config["gemini"] = {
                "session_cookies": session_dict["session_cookies"],
                "last_updated": session_dict["extracted_at"],
                "expires_at": session_dict["expires_at"],
                "auto_refresh_enabled": True,
            }

            # Save updated config
            self._save_config(config)

            result["success"] = True

        except Exception as e:
            result["error"] = str(e)
            # Attempt to restore backup if available
            if result["backup_path"]:
                try:
                    shutil.copy2(result["backup_path"], self.config_path)
                    result["restored_from_backup"] = True
                except Exception as restore_error:
                    result["restore_error"] = str(restore_error)

        return result

    def get_current_session_status(self) -> Optional[Dict]:
        """Get current Gemini session status from config"""
        try:
            config = self._load_config()
            gemini_config = config.get("gemini", {})

            if not gemini_config:
                return None

            return {
                "last_updated": gemini_config.get("last_updated"),
                "expires_at": gemini_config.get("expires_at"),
                "auto_refresh_enabled": gemini_config.get("auto_refresh_enabled", False),
                "has_session_cookies": bool(gemini_config.get("session_cookies")),
            }
        except Exception:
            return None

    def cleanup_old_backups(self, keep_count: int = 10) -> int:
        """Clean up old backup files, keeping only the most recent ones"""
        if not self.backup_dir.exists():
            return 0

        backups = sorted(
            self.backup_dir.glob("config.json.backup.*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        removed = 0
        for old_backup in backups[keep_count:]:
            try:
                old_backup.unlink()
                removed += 1
            except Exception:
                pass

        return removed


def update_config_from_session(
    session: GeminiSession,
    config_path: Optional[str] = None,
) -> Dict:
    """Convenience function to update config from session"""
    updater = ConfigUpdater(config_path)
    return updater.update_gemini_session(session)


if __name__ == "__main__":
    # Test the updater
    print("Config Updater Test")
    print("=" * 50)

    updater = ConfigUpdater()

    # Check current status
    status = updater.get_current_session_status()
    if status:
        print("Current session status:")
        print(json.dumps(status, indent=2))
    else:
        print("No existing Gemini session found")

    # Test with mock session
    test_session = GeminiSession(
        secure_1psid="test_session_id_12345",
        secure_1psidts="test_timestamp",
        secure_1psidcc="test_cc",
    )

    print("\nUpdating with test session...")
    result = updater.update_gemini_session(test_session)
    print(json.dumps(result, indent=2))

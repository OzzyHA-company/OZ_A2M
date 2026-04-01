#!/usr/bin/env python3
"""
Crypto utilities for OZ-PI Gemini SaaS Skill
Handles AES-256 encryption/decryption of sensitive data
"""

import os
import base64
import getpass
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class CryptoManager:
    """Manages encryption/decryption using AES-256 via Fernet"""

    SALT_FILE = Path.home() / ".oz_gemini_salt"
    PASSWORD_FILE = Path.home() / ".oz_gemini.enc"

    def __init__(self):
        self._key = None

    def _get_or_create_salt(self) -> bytes:
        """Get existing salt or create new one"""
        if self.SALT_FILE.exists():
            return self.SALT_FILE.read_bytes()

        # Generate new salt
        salt = os.urandom(16)
        self.SALT_FILE.write_bytes(salt)
        self.SALT_FILE.chmod(0o600)
        return salt

    def _derive_key(self, master_password: str, salt: bytes) -> bytes:
        """Derive encryption key from master password using PBKDF2"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(master_password.encode()))
        return key

    def encrypt_password(self, google_password: str, master_password: str = None) -> None:
        """Encrypt Google password and save to file"""
        if master_password is None:
            master_password = getpass.getpass("Enter master password for encryption: ")
            confirm = getpass.getpass("Confirm master password: ")
            if master_password != confirm:
                raise ValueError("Passwords do not match")

        salt = self._get_or_create_salt()
        key = self._derive_key(master_password, salt)
        fernet = Fernet(key)

        encrypted = fernet.encrypt(google_password.encode())
        self.PASSWORD_FILE.write_bytes(encrypted)
        self.PASSWORD_FILE.chmod(0o600)

        print(f"✓ Password encrypted and saved to {self.PASSWORD_FILE}")

    def decrypt_password(self, master_password: str = None) -> str:
        """Decrypt and return Google password"""
        if not self.PASSWORD_FILE.exists():
            raise FileNotFoundError(
                f"Encrypted password file not found at {self.PASSWORD_FILE}\n"
                "Run: python3 setup_password.py"
            )

        if master_password is None:
            master_password = getpass.getpass("Enter master password: ")

        salt = self._get_or_create_salt()
        key = self._derive_key(master_password, salt)
        fernet = Fernet(key)

        try:
            encrypted = self.PASSWORD_FILE.read_bytes()
            decrypted = fernet.decrypt(encrypted)
            return decrypted.decode()
        except Exception as e:
            raise ValueError(f"Failed to decrypt password. Wrong master password?") from e

    def is_password_set(self) -> bool:
        """Check if encrypted password file exists"""
        return self.PASSWORD_FILE.exists()


def setup_password_interactive():
    """Interactive setup for password encryption"""
    print("=" * 50)
    print("OZ-PI Gemini SaaS - Password Setup")
    print("=" * 50)
    print()
    print("This will encrypt your Google account password")
    print("for secure storage and automatic authentication.")
    print()

    email = os.environ.get("OZ_GEMINI_EMAIL", "ozzyclaw9085@gmail.com")
    print(f"Email: {email}")
    print()

    google_password = getpass.getpass("Enter your Google account password: ")
    if not google_password:
        raise ValueError("Password cannot be empty")

    print()
    print("Now set a master password for encryption.")
    print("This will be required each time you run the auth script.")
    print()

    crypto = CryptoManager()
    crypto.encrypt_password(google_password)

    print()
    print("=" * 50)
    print("Setup complete! You can now run:")
    print("  /oz-pi-gemini-saas")
    print("=" * 50)


if __name__ == "__main__":
    setup_password_interactive()

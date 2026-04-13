"""
Wallet Encryptor - Fernet-based Private Key Encryption
Phase 1: Security & Wallet Setup

Usage:
    python3 wallet_encryptor.py --generate-key
    python3 wallet_encryptor.py --encrypt --key <KEY> --input <FILE>
    python3 wallet_encryptor.py --decrypt --key <KEY> --input <FILE>
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken


def generate_master_key() -> str:
    """Generate a new Fernet master key."""
    return Fernet.generate_key().decode()


def encrypt_private_key(private_key: str, master_key: str) -> str:
    """Encrypt a private key using Fernet."""
    f = Fernet(master_key.encode())
    encrypted = f.encrypt(private_key.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_private_key(encrypted_key: str, master_key: str) -> str:
    """Decrypt a private key using Fernet."""
    try:
        f = Fernet(master_key.encode())
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_key.encode())
        decrypted = f.decrypt(encrypted_bytes)
        return decrypted.decode()
    except InvalidToken:
        raise ValueError("Invalid master key or corrupted encrypted data")
    except Exception as e:
        raise ValueError(f"Decryption failed: {e}")


class WalletVault:
    """Secure wallet storage with Fernet encryption."""

    def __init__(self, vault_path: str, master_key: str):
        self.vault_path = Path(vault_path)
        self.master_key = master_key
        self.wallets: Dict[str, Dict] = {}
        self._load_vault()

    def _load_vault(self):
        """Load encrypted vault from disk."""
        if self.vault_path.exists():
            try:
                with open(self.vault_path, 'r') as f:
                    data = json.load(f)
                    self.wallets = data.get('wallets', {})
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load vault: {e}")
                self.wallets = {}

    def _save_vault(self):
        """Save encrypted vault to disk."""
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.vault_path, 'w') as f:
            json.dump({
                'version': '1.0',
                'wallets': self.wallets
            }, f, indent=2)
        os.chmod(self.vault_path, 0o600)

    def add_wallet(self, name: str, private_key: str, chain: str = 'solana',
                   metadata: Optional[Dict] = None) -> Dict:
        """Add a wallet to the vault with encrypted private key."""
        encrypted_key = encrypt_private_key(private_key, self.master_key)

        wallet_data = {
            'name': name,
            'chain': chain,
            'encrypted_key': encrypted_key,
            'metadata': metadata or {},
            'created_at': os.path.getmtime(self.vault_path) if self.vault_path.exists() else 0
        }

        self.wallets[name] = wallet_data
        self._save_vault()
        return wallet_data

    def get_wallet(self, name: str) -> Optional[Dict]:
        """Get wallet data (without decrypted key)."""
        return self.wallets.get(name)

    def decrypt_wallet_key(self, name: str) -> str:
        """Decrypt and return the private key for a wallet."""
        wallet = self.wallets.get(name)
        if not wallet:
            raise ValueError(f"Wallet '{name}' not found in vault")

        return decrypt_private_key(wallet['encrypted_key'], self.master_key)

    def list_wallets(self) -> list:
        """List all wallet names in vault."""
        return list(self.wallets.keys())

    def remove_wallet(self, name: str) -> bool:
        """Remove a wallet from vault."""
        if name in self.wallets:
            del self.wallets[name]
            self._save_vault()
            return True
        return False


def migrate_from_env(env_file: str, vault_path: str, master_key: str) -> int:
    """Migrate wallet keys from .env file to encrypted vault."""
    vault = WalletVault(vault_path, master_key)

    # Parse .env file
    wallets_migrated = 0
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Detect wallet private keys
            if 'PRIVATE_KEY' in line or 'WALLET' in line:
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")

                    if len(value) > 20 and ' ' not in value:  # Likely a key
                        chain = 'solana' if 'SOL' in key or 'PHANTOM' in key else 'evm'
                        vault.add_wallet(
                            name=key.lower(),
                            private_key=value,
                            chain=chain,
                            metadata={'source': 'env_migration'}
                        )
                        wallets_migrated += 1
                        print(f"  ✓ Migrated: {key}")

    return wallets_migrated


def main():
    parser = argparse.ArgumentParser(description='Wallet Encryption Tool')
    parser.add_argument('--generate-key', action='store_true',
                        help='Generate a new master encryption key')
    parser.add_argument('--encrypt', action='store_true',
                        help='Encrypt a private key')
    parser.add_argument('--decrypt', action='store_true',
                        help='Decrypt an encrypted key')
    parser.add_argument('--key', type=str, help='Master key for encryption/decryption')
    parser.add_argument('--input', type=str, help='Input file or string')
    parser.add_argument('--vault', type=str, default='~/.ozzy-secrets/wallet_vault.enc',
                        help='Path to wallet vault file')
    parser.add_argument('--migrate-env', type=str,
                        help='Migrate wallets from .env file to vault')

    args = parser.parse_args()

    if args.generate_key:
        key = generate_master_key()
        print("=" * 60)
        print("Generated Master Key (SAVE THIS SECURELY):")
        print("=" * 60)
        print(key)
        print("=" * 60)
        print("\nStore this in ~/.ozzy-secrets/.vault_key with chmod 600")
        return

    if args.migrate_env:
        if not args.key:
            print("Error: --key required for migration")
            sys.exit(1)

        vault_path = os.path.expanduser(args.vault)
        count = migrate_from_env(args.migrate_env, vault_path, args.key)
        print(f"\n✅ Migrated {count} wallets to {vault_path}")
        return

    if args.encrypt:
        if not args.key or not args.input:
            print("Error: --key and --input required for encryption")
            sys.exit(1)

        encrypted = encrypt_private_key(args.input, args.key)
        print(f"Encrypted: {encrypted}")
        return

    if args.decrypt:
        if not args.key or not args.input:
            print("Error: --key and --input required for decryption")
            sys.exit(1)

        try:
            decrypted = decrypt_private_key(args.input, args.key)
            print(f"Decrypted: {decrypted}")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
        return

    parser.print_help()


if __name__ == '__main__':
    main()

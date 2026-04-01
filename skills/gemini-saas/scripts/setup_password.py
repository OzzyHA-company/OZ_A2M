#!/usr/bin/env python3
"""
Setup script for OZ-PI Gemini SaaS Skill
Encrypts Google password for secure storage
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto_utils import setup_password_interactive

if __name__ == "__main__":
    try:
        setup_password_interactive()
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)

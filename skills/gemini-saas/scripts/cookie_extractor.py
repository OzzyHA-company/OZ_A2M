#!/usr/bin/env python3
"""
Cookie extraction and validation utility for OZ-PI Gemini SaaS Skill
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict


@dataclass
class GeminiSession:
    """Represents a Gemini session with cookies and metadata"""

    # Essential cookies for Gemini authentication
    secure_1psid: str
    secure_1psidts: Optional[str] = None
    secure_1psidcc: Optional[str] = None

    # Google session cookies
    sid: Optional[str] = None
    ssid: Optional[str] = None
    apisid: Optional[str] = None
    sapisid: Optional[str] = None

    # Metadata
    extracted_at: Optional[str] = None
    expires_at: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "session_cookies": {
                "__Secure-1PSID": self.secure_1psid,
                "__Secure-1PSIDTS": self.secure_1psidts,
                "__Secure-1PSIDCC": self.secure_1psidcc,
                "SID": self.sid,
                "SSID": self.ssid,
                "APISID": self.apisid,
                "SAPISID": self.sapisid,
            },
            "extracted_at": self.extracted_at or datetime.utcnow().isoformat(),
            "expires_at": self.expires_at or (datetime.utcnow() + timedelta(days=7)).isoformat(),
        }

    @classmethod
    def from_cookies_list(cls, cookies: List[Dict]) -> "GeminiSession":
        """Create GeminiSession from Playwright cookies list"""
        cookie_map = {c["name"]: c["value"] for c in cookies}

        return cls(
            secure_1psid=cookie_map.get("__Secure-1PSID"),
            secure_1psidts=cookie_map.get("__Secure-1PSIDTS"),
            secure_1psidcc=cookie_map.get("__Secure-1PSIDCC"),
            sid=cookie_map.get("SID"),
            ssid=cookie_map.get("SSID"),
            apisid=cookie_map.get("APISID"),
            sapisid=cookie_map.get("SAPISID"),
            extracted_at=datetime.utcnow().isoformat(),
            expires_at=(datetime.utcnow() + timedelta(days=7)).isoformat(),
        )

    def is_valid(self) -> bool:
        """Check if session has required cookies"""
        return bool(self.secure_1psid)

    def get_expiry_status(self) -> str:
        """Get human-readable expiry status"""
        if not self.expires_at:
            return "Unknown"

        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            now = datetime.utcnow()

            if expiry < now:
                return "EXPIRED"

            days_left = (expiry - now).days
            if days_left <= 1:
                return f"EXPIRES SOON ({days_left} day left)"
            elif days_left <= 3:
                return f"EXPIRES SOON ({days_left} days left)"
            else:
                return f"Valid ({days_left} days left)"
        except Exception:
            return "Unknown"


class CookieExtractor:
    """Extracts and processes cookies from browser context"""

    # Cookies required for Gemini authentication
    REQUIRED_COOKIES = ["__Secure-1PSID"]

    # All cookies we want to capture
    TARGET_COOKIES = [
        "__Secure-1PSID",
        "__Secure-1PSIDTS",
        "__Secure-1PSIDCC",
        "SID",
        "SSID",
        "APISID",
        "SAPISID",
    ]

    def __init__(self, debug_dir: Optional[str] = None):
        self.debug_dir = debug_dir

    async def extract_from_context(self, context) -> GeminiSession:
        """Extract cookies from Playwright browser context"""
        # Get all cookies
        all_cookies = await context.cookies()

        # Filter for Gemini/Google domains
        gemini_cookies = [
            c for c in all_cookies
            if any(domain in c.get("domain", "") for domain in [".google.com", "google.com", ".gemini.google.com"])
        ]

        # Create session object
        session = GeminiSession.from_cookies_list(gemini_cookies)

        # Validate
        if not session.is_valid():
            missing = self.REQUIRED_COOKIES
            raise ValueError(f"Missing required cookies: {missing}")

        return session

    def save_session(self, session: GeminiSession, output_path: str) -> None:
        """Save session to JSON file"""
        with open(output_path, "w") as f:
            json.dump(session.to_dict(), f, indent=2)

        # Set restrictive permissions
        import os
        os.chmod(output_path, 0o600)

    def load_session(self, input_path: str) -> GeminiSession:
        """Load session from JSON file"""
        with open(input_path, "r") as f:
            data = json.load(f)

        cookies = data.get("session_cookies", {})
        return GeminiSession(
            secure_1psid=cookies.get("__Secure-1PSID"),
            secure_1psidts=cookies.get("__Secure-1PSIDTS"),
            secure_1psidcc=cookies.get("__Secure-1PSIDCC"),
            sid=cookies.get("SID"),
            ssid=cookies.get("SSID"),
            apisid=cookies.get("APISID"),
            sapisid=cookies.get("SAPISID"),
            extracted_at=data.get("extracted_at"),
            expires_at=data.get("expires_at"),
        )


def filter_gemini_cookies(cookies: List[Dict]) -> Dict[str, str]:
    """Filter and return only Gemini-relevant cookies"""
    gemini_names = {
        "__Secure-1PSID",
        "__Secure-1PSIDTS",
        "__Secure-1PSIDCC",
        "SID",
        "SSID",
        "APISID",
        "SAPISID",
    }

    return {
        c["name"]: c["value"]
        for c in cookies
        if c["name"] in gemini_names
    }


if __name__ == "__main__":
    # Test the extractor
    print("Cookie Extractor Test")
    print("=" * 50)

    # Create a mock session
    session = GeminiSession(
        secure_1psid="test_session_id",
        secure_1psidts="test_timestamp",
        secure_1psidcc="test_cc",
    )

    print(f"Session valid: {session.is_valid()}")
    print(f"Expiry status: {session.get_expiry_status()}")
    print("\nSession data:")
    print(json.dumps(session.to_dict(), indent=2))

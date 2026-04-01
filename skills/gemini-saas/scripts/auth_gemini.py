#!/usr/bin/env python3
"""
Main authentication script for OZ-PI Gemini SaaS Skill
Automates Google login to Gemini Advanced and extracts session cookies
"""

import os
import sys
import argparse
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional

# Import local modules
sys.path.insert(0, str(Path(__file__).parent))

try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext
except ImportError:
    print("Error: Playwright not installed.")
    print("Install with: pip install playwright && playwright install chromium")
    sys.exit(1)

from crypto_utils import CryptoManager
from cookie_extractor import CookieExtractor, GeminiSession
from update_config import ConfigUpdater


class GeminiAuthenticator:
    """Handles Google authentication and Gemini session extraction"""

    GOOGLE_LOGIN_URL = "https://accounts.google.com/signin"
    GEMINI_URL = "https://gemini.google.com/app"
    EMAIL_SELECTOR = 'input[type="email"]'
    PASSWORD_SELECTOR = 'input[type="password"]'
    EMAIL_NEXT_SELECTOR = "#identifierNext"
    PASSWORD_NEXT_SELECTOR = "#passwordNext"

    def __init__(
        self,
        email: str,
        headless: bool = False,
        debug_dir: Optional[str] = None,
        config_path: Optional[str] = None,
    ):
        self.email = email
        self.headless = headless
        self.debug_dir = Path(debug_dir) if debug_dir else Path(__file__).parent / "debug"
        self.config_path = config_path
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        # Ensure debug directory exists
        self.debug_dir.mkdir(parents=True, exist_ok=True)

    async def __aenter__(self):
        """Async context manager entry"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def _take_screenshot(self, name: str):
        """Take screenshot for debugging"""
        if self.page:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = self.debug_dir / f"{name}_{timestamp}.png"
            await self.page.screenshot(path=str(screenshot_path), full_page=True)
            print(f"  Screenshot saved: {screenshot_path}")

    async def _enter_email(self):
        """Enter email address"""
        print(f"  Entering email: {self.email}")

        # Wait for and fill email field
        await self.page.wait_for_selector(self.EMAIL_SELECTOR, timeout=10000)
        await self.page.fill(self.EMAIL_SELECTOR, self.email)

        # Click next
        await self.page.click(self.EMAIL_NEXT_SELECTOR)
        await asyncio.sleep(2)

    async def _enter_password(self, password: str):
        """Enter password"""
        print("  Entering password...")

        # Wait for password field
        await self.page.wait_for_selector(self.PASSWORD_SELECTOR, timeout=10000)
        await self.page.fill(self.PASSWORD_SELECTOR, password)

        # Click next
        await self.page.click(self.PASSWORD_NEXT_SELECTOR)
        await asyncio.sleep(3)

    async def _handle_2fa_or_challenge(self) -> bool:
        """Handle 2FA or security challenges if they appear"""
        current_url = self.page.url

        # Check if we're still on Google auth pages
        if "accounts.google.com" in current_url:
            print("  ⚠️  Additional authentication required")
            print("  You may need to:")
            print("    - Complete 2FA on your device")
            print("    - Verify 'Yes, it was me'")
            print("    - Solve a CAPTCHA")

            if not self.headless:
                print("\n  Waiting for manual authentication (60 seconds)...")
                print("  Complete the auth in the browser window.")

                # Wait for redirect away from auth page
                try:
                    await self.page.wait_for_load_state("networkidle", timeout=60000)
                    # Check if we're still on auth page
                    if "accounts.google.com" not in self.page.url:
                        print("  ✓ Authentication completed")
                        return True
                except Exception:
                    pass

            await self._take_screenshot("auth_challenge")
            return False

        return True

    async def _navigate_to_gemini(self):
        """Navigate to Gemini Advanced"""
        print("  Navigating to Gemini...")
        try:
            # Try networkidle first with longer timeout
            await self.page.goto(self.GEMINI_URL, wait_until="networkidle", timeout=60000)
        except Exception:
            # Fallback to domcontentloaded if networkidle times out
            print("  Falling back to faster load strategy...")
            await self.page.goto(self.GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

        # Check if we're actually on Gemini
        if "gemini.google.com" not in self.page.url:
            print(f"  Warning: Not on Gemini page. Current URL: {self.page.url}")
            await self._take_screenshot("gemini_navigation_failed")
            raise Exception("Failed to navigate to Gemini")

        print("  ✓ Successfully loaded Gemini")

    async def _check_gemini_loaded(self) -> bool:
        """Check if Gemini page loaded successfully"""
        try:
            # Look for Gemini-specific elements
            selectors = [
                '[data-test-id="chat-input"]',
                'textarea[placeholder*="Ask Gemini"]',
                '.chat-container',
                '[role="main"]',
            ]

            for selector in selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=5000)
                    return True
                except:
                    continue

            return False
        except Exception:
            return False

    async def authenticate(self, password: str) -> bool:
        """
        Perform full authentication flow

        Returns:
            bool: True if authentication successful
        """
        try:
            print("\n🌐 Starting authentication...")

            # Navigate to Google login
            print("  Loading Google login page...")
            await self.page.goto(self.GOOGLE_LOGIN_URL, wait_until="networkidle")
            await asyncio.sleep(2)

            # Enter email
            await self._enter_email()

            # Enter password
            await self._enter_password(password)

            # Handle any 2FA/challenges
            if not await self._handle_2fa_or_challenge():
                print("  ✗ Authentication failed - manual intervention required")
                return False

            # Navigate to Gemini
            await self._navigate_to_gemini()

            # Verify Gemini loaded
            if not await self._check_gemini_loaded():
                print("  Warning: Gemini page elements not found, but continuing...")
                await self._take_screenshot("gemini_uncertain")

            print("  ✓ Authentication successful")
            return True

        except Exception as e:
            print(f"  ✗ Authentication error: {e}")
            await self._take_screenshot("auth_error")
            return False

    async def extract_session(self) -> Optional[GeminiSession]:
        """Extract Gemini session from browser context"""
        try:
            print("\n🍪 Extracting session cookies...")

            extractor = CookieExtractor(debug_dir=str(self.debug_dir))
            session = await extractor.extract_from_context(self.context)

            if session.is_valid():
                print(f"  ✓ Extracted {len([c for c in session.to_dict()['session_cookies'].values() if c])} cookies")
                print(f"  ✓ Main session ID: {session.secure_1psid[:20]}...")
                return session
            else:
                print("  ✗ Session validation failed")
                return None

        except Exception as e:
            print(f"  ✗ Cookie extraction error: {e}")
            return None


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="OZ-PI Gemini SaaS Re-Authenticator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--email",
        default=os.environ.get("OZ_GEMINI_EMAIL", "ozzyclaw9085@gmail.com"),
        help="Google account email (default: OZ_GEMINI_EMAIL env var)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (no browser window)",
    )
    parser.add_argument(
        "--config-path",
        default=os.environ.get("PI_MONO_CONFIG_PATH"),
        help="Path to pi-mono config file",
    )
    parser.add_argument(
        "--debug-dir",
        help="Directory for debug screenshots",
    )
    parser.add_argument(
        "--setup-password",
        action="store_true",
        help="Run password setup instead of authentication",
    )

    args = parser.parse_args()

    # Handle password setup
    if args.setup_password:
        from crypto_utils import setup_password_interactive
        setup_password_interactive()
        return

    # Banner
    print("=" * 60)
    print("🔐 OZ-PI Gemini SaaS Re-Authenticator")
    print("=" * 60)
    print()

    # Check for encrypted password
    crypto = CryptoManager()
    if not crypto.is_password_set():
        print("❌ Encrypted password not found!")
        print()
        print("Please run setup first:")
        print("  python3 auth_gemini.py --setup-password")
        print()
        sys.exit(1)

    # Decrypt password
    try:
        password = crypto.decrypt_password()
    except Exception as e:
        print(f"❌ Failed to decrypt password: {e}")
        sys.exit(1)

    print(f"📧 Email: {args.email}")
    print(f"🖥️  Mode: {'Headless' if args.headless else 'Browser visible'}")
    print()

    # Perform authentication
    async with GeminiAuthenticator(
        email=args.email,
        headless=args.headless,
        debug_dir=args.debug_dir,
        config_path=args.config_path,
    ) as auth:
        # Authenticate
        if not await auth.authenticate(password):
            print("\n❌ Authentication failed")
            sys.exit(1)

        # Extract session
        session = await auth.extract_session()
        if not session:
            print("\n❌ Session extraction failed")
            sys.exit(1)

        # Update config
        print("\n💾 Updating pi-mono configuration...")
        updater = ConfigUpdater(args.config_path)
        result = updater.update_gemini_session(session)

        if result["success"]:
            print(f"  ✓ Config updated: {result['config_path']}")
            if result["backup_path"]:
                print(f"  ✓ Backup created: {result['backup_path']}")

            # Show session status
            print()
            print("📊 Session Status:")
            print(f"  Extracted: {session.extracted_at}")
            print(f"  Expires:   {session.expires_at}")
            print(f"  Status:    {session.get_expiry_status()}")

            # Cleanup old backups
            removed = updater.cleanup_old_backups(keep_count=10)
            if removed > 0:
                print(f"  🧹 Cleaned up {removed} old backups")

            print()
            print("=" * 60)
            print("✅ Gemini session successfully updated!")
            print("=" * 60)

        else:
            print(f"  ✗ Config update failed: {result.get('error', 'Unknown error')}")
            sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)

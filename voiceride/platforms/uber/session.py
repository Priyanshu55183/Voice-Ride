"""
Uber session management — login persistence and session health checks.

Handles:
  - Persistent browser context (cookies saved to disk, reused across runs)
  - One-time interactive login via helper script
  - Session validity detection (logged in? expired? redirected to login?)
"""

from __future__ import annotations

import structlog
from playwright.async_api import BrowserContext, Page

from voiceride.platforms.uber.selectors import UberSelectors

log = structlog.get_logger()


class UberSessionManager:
    """Manages Uber login session state and persistence."""

    def __init__(self):
        self.sel = UberSelectors

    async def is_logged_in(self, page: Page) -> bool:
        """
        Check if the current page shows a logged-in state.

        Looks for the presence of user-specific UI elements (avatar, account menu)
        and the absence of login prompts.

        Returns True if the session appears valid.
        """
        try:
            # Check for user avatar / account menu — indicates logged in
            avatar_visible = await page.is_visible(self.sel.USER_AVATAR, timeout=3000)
            if avatar_visible:
                log.debug("session_check", status="logged_in", indicator="user_avatar")
                return True

            # Check for login prompt — indicates NOT logged in
            login_visible = await page.is_visible(self.sel.LOGIN_PROMPT, timeout=2000)
            if login_visible:
                log.debug("session_check", status="not_logged_in", indicator="login_prompt")
                return False

            # Ambiguous — check URL for login redirect
            if "login" in page.url.lower() or "auth" in page.url.lower():
                log.debug("session_check", status="not_logged_in", indicator="url_redirect")
                return False

            # If no clear indicator, assume logged in (we're on a ride page, etc.)
            log.debug("session_check", status="assumed_logged_in", url=page.url)
            return True

        except Exception as e:
            log.warning("session_check_error", error=str(e))
            return False

    async def detect_session_expired(self, page: Page) -> bool:
        """
        Check if we've been redirected to a login page mid-flow.

        This is called during automation to catch session expiry that happens
        between actions (e.g., cookies expired while we were polling).

        Returns True if the session appears to have expired.
        """
        # URL-based detection (most reliable)
        if "login" in page.url.lower() or "auth" in page.url.lower():
            log.warning("session_expired", indicator="url_redirect", url=page.url)
            return True

        # UI-based detection
        try:
            login_visible = await page.is_visible(self.sel.LOGIN_PROMPT, timeout=1000)
            if login_visible:
                log.warning("session_expired", indicator="login_prompt_visible")
                return True
        except Exception:
            pass

        return False

    async def wait_for_manual_login(self, page: Page, timeout_seconds: int = 300) -> bool:
        """
        Wait for the user to complete manual login in the browser window.

        Used by scripts/uber_login.py. Opens the login page and waits
        until the user has authenticated, then the session cookies are
        automatically saved to the persistent context directory.

        Args:
            page: The Playwright page showing the login form.
            timeout_seconds: Max time to wait for login (default 5 minutes).

        Returns:
            True if login was detected, False if timed out.
        """
        import asyncio

        log.info("waiting_for_manual_login", timeout_seconds=timeout_seconds)
        print("\n" + "=" * 60)
        print("  Please log in to Uber in the browser window.")
        print("  The session will be saved automatically.")
        print(f"  Timeout: {timeout_seconds} seconds")
        print("=" * 60 + "\n")

        elapsed = 0
        poll_interval = 2

        while elapsed < timeout_seconds:
            if await self.is_logged_in(page):
                log.info("manual_login_detected")
                print("\n✅ Login detected! Session saved.\n")
                return True

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            if elapsed % 30 == 0:
                print(f"  Still waiting for login... ({elapsed}s / {timeout_seconds}s)")

        log.warning("manual_login_timeout", timeout_seconds=timeout_seconds)
        print("\n❌ Login timed out.\n")
        return False

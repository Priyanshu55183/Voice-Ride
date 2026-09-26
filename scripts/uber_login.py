"""
Interactive Uber login helper.

Run this once to log into Uber manually in a browser window. The session
(cookies) will be saved to disk and reused by VoiceRide automatically.

Usage:
    python scripts/uber_login.py

What happens:
    1. Opens a Chromium browser window pointed at m.uber.com
    2. You log in manually (phone number, OTP, etc.)
    3. The script detects when login is complete
    4. Cookies are saved to data/uber_session/
    5. Future VoiceRide runs reuse the session — no re-login needed
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path so we can import voiceride
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def main():
    from playwright.async_api import async_playwright
    from voiceride.config import settings
    from voiceride.platforms.uber.session import UberSessionManager

    print("=" * 60)
    print("  VoiceRide — Uber Login Helper")
    print("=" * 60)
    print()
    print(f"  Session directory: {settings.uber_user_data_dir}")
    print(f"  Target URL: {settings.uber_base_url}")
    print()

    user_data_dir = str(settings.get_uber_data_dir())

    async with await async_playwright().start() as pw:
        # Launch with persistent context — cookies will be saved here
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,  # Must be visible for manual login
            viewport={"width": 430, "height": 932},
            user_agent=(
                "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36"
            ),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(settings.uber_base_url, wait_until="domcontentloaded")

        session_manager = UberSessionManager()

        # Check if already logged in
        if await session_manager.is_logged_in(page):
            print("✅ Already logged in! Session is valid.")
            print("   You can close this window.")
        else:
            # Wait for manual login
            success = await session_manager.wait_for_manual_login(page, timeout_seconds=300)
            if success:
                print("✅ Session saved successfully!")
                print("   You can now run VoiceRide and it will reuse this session.")
            else:
                print("❌ Login timed out. Please try again.")

        # Keep browser open briefly so the user can verify
        print("\nClosing browser in 5 seconds...")
        await asyncio.sleep(5)
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())

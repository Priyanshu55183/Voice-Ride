"""
UberAdapter — implements PlatformAdapter using Playwright against m.uber.com.

This is the thin glue layer between the generic PlatformAdapter interface
and the Uber-specific Playwright automation. It:
  1. Manages the Playwright browser lifecycle (init/teardown)
  2. Delegates all DOM interactions to UberAutomation (automation.py)
  3. Checks session health via UberSessionManager (session.py)
"""

from __future__ import annotations

import structlog
from playwright.async_api import async_playwright, BrowserContext, Page, Playwright

from voiceride.config import settings
from voiceride.orchestrator.models import (
    CancelResult,
    PlatformName,
    RideQuote,
    RideRequest,
    RideStatus,
)
from voiceride.platforms.base import PlatformAdapter
from voiceride.platforms.uber.automation import UberAutomation
from voiceride.platforms.uber.session import UberSessionManager

log = structlog.get_logger()


class UberAdapter(PlatformAdapter):
    """
    Uber platform adapter using Playwright to automate m.uber.com.

    Lifecycle:
        initialize() → request_quote() → book_ride() → poll_status() (×N) → teardown()
        At any point: cancel_ride() may be called by the orchestrator.
    """

    @property
    def name(self) -> PlatformName:
        return PlatformName.UBER

    def __init__(self):
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._automation: UberAutomation | None = None
        self._session_manager = UberSessionManager()
        self._booking_id: str | None = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("UberAdapter not initialized. Call initialize() first.")
        return self._page

    @property
    def automation(self) -> UberAutomation:
        if self._automation is None:
            raise RuntimeError("UberAdapter not initialized. Call initialize() first.")
        return self._automation

    async def initialize(self) -> None:
        """
        Launch Playwright with a persistent browser context.

        The persistent context saves cookies/localStorage to disk, so Uber's
        login session survives across runs without re-authentication.
        """
        log.info("uber_adapter_initializing")

        self._playwright = await async_playwright().start()

        # Persistent context = cookies saved to uber_user_data_dir
        user_data_dir = str(settings.get_uber_data_dir())
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=settings.uber_headless,
            viewport={"width": 430, "height": 932},  # Mobile-like viewport
            user_agent=(
                "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36"
            ),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )

        # Use the first page or create a new one
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

        self._automation = UberAutomation(self._page)

        # Check session status
        await self.page.goto(settings.uber_base_url, wait_until="domcontentloaded")
        is_logged_in = await self._session_manager.is_logged_in(self.page)

        if not is_logged_in:
            log.error(
                "uber_not_logged_in",
                help="Run 'python scripts/uber_login.py' to log in interactively.",
            )
            raise RuntimeError(
                "Uber session not found or expired. "
                "Please run 'python scripts/uber_login.py' to log in first."
            )

        log.info("uber_adapter_initialized", logged_in=True)

    async def request_quote(self, request: RideRequest) -> RideQuote:
        """Navigate to booking, enter locations, and get a fare estimate."""
        log.info("uber_requesting_quote", pickup=request.pickup, drop=request.drop)

        # Check session health before starting
        if await self._session_manager.detect_session_expired(self.page):
            raise RuntimeError("Uber session expired mid-flow")

        # Navigate to the booking page
        await self.automation.navigate_to_booking()

        # Enter pickup and drop locations
        await self.automation.set_pickup(request.pickup)
        await self.automation.set_drop(request.drop)

        # Get the fare quote
        quote = await self.automation.select_ride_and_get_quote(request)

        log.info(
            "uber_quote_received",
            ride_type=quote.ride_type,
            fare=quote.estimated_fare,
        )
        return quote

    async def book_ride(self, quote: RideQuote) -> str:
        """Confirm the booking and return a booking reference."""
        log.info("uber_booking_ride", ride_type=quote.ride_type, fare=quote.estimated_fare)

        await self.automation.confirm_booking()

        # Generate a local booking ID for tracking
        import uuid
        self._booking_id = f"uber-{uuid.uuid4().hex[:8]}"

        log.info("uber_ride_booked", booking_id=self._booking_id)
        return self._booking_id

    async def poll_status(self) -> RideStatus:
        """Check the current ride status by reading the page."""
        # Quick session check
        if await self._session_manager.detect_session_expired(self.page):
            from voiceride.orchestrator.models import BookingState
            from datetime import datetime, timezone
            return RideStatus(
                platform=PlatformName.UBER,
                state=BookingState.ERROR,
                timestamp=datetime.now(timezone.utc),
                raw_data={"error": "session_expired"},
            )

        status = await self.automation.read_ride_status()
        log.info(
            "uber_status_polled",
            state=status.state.value,
            driver=status.driver_name,
            eta=status.driver_eta_seconds,
        )
        return status

    async def cancel_ride(self) -> CancelResult:
        """Cancel the active ride."""
        log.info("uber_cancelling_ride", booking_id=self._booking_id)
        result = await self.automation.cancel_current_ride()
        log.info(
            "uber_cancel_result",
            success=result.success,
            reason=result.reason,
            booking_id=self._booking_id,
        )
        return result

    async def teardown(self) -> None:
        """Close the browser gracefully."""
        log.info("uber_adapter_teardown")
        try:
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            log.warning("uber_teardown_error", error=str(e))
        finally:
            self._page = None
            self._context = None
            self._playwright = None
            self._automation = None

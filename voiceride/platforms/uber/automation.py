"""
Playwright page-object actions for m.uber.com.

This file contains ALL the actual browser interactions — clicking, typing,
reading text, waiting for elements. It's the "messy" layer that deals with
the real-world DOM.

If Uber redesigns their page, you edit THIS FILE (and selectors.py).
The adapter (adapter.py) and orchestrator don't need to change.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from voiceride.config import settings
from voiceride.orchestrator.models import (
    BookingState,
    CancelResult,
    PlatformName,
    RideQuote,
    RideRequest,
    RideStatus,
)
from voiceride.platforms.uber.selectors import UberSelectors

log = structlog.get_logger()


class UberAutomation:
    """
    Page-object wrapper for all Playwright interactions with m.uber.com.

    Each method maps to a single user-visible action on the Uber mobile web UI.
    All selectors come from UberSelectors — never hardcoded in this file.
    """

    def __init__(self, page: Page):
        self.page = page
        self.sel = UberSelectors
        self._element_timeout = settings.uber_element_timeout

    # ── Navigation ───────────────────────────────────────────────────────

    async def navigate_to_booking(self) -> None:
        """Navigate to m.uber.com and wait for the booking interface to load."""
        log.info("uber_navigate", url=settings.uber_base_url)
        await self.page.goto(
            settings.uber_base_url,
            wait_until="domcontentloaded",
            timeout=settings.uber_page_load_timeout,
        )
        # Wait for either the "Where to" button or the pickup input to appear
        await self.page.wait_for_selector(
            f"{self.sel.WHERE_TO_BUTTON}, {self.sel.PICKUP_INPUT}",
            timeout=self._element_timeout,
        )
        log.info("uber_booking_page_loaded")

    # ── Location Entry ───────────────────────────────────────────────────

    async def set_pickup(self, location: str) -> None:
        """
        Enter the pickup location and select the first autocomplete suggestion.

        Steps:
        1. Click the pickup input field
        2. Clear any existing text
        3. Type the location name
        4. Wait for autocomplete suggestions to appear
        5. Click the first suggestion
        """
        log.info("uber_set_pickup", location=location)

        # Click "Where to?" button first if it's visible (initial state)
        try:
            where_to = await self.page.wait_for_selector(
                self.sel.WHERE_TO_BUTTON, timeout=3000
            )
            if where_to:
                await where_to.click()
                log.debug("uber_clicked_where_to")
        except PlaywrightTimeout:
            pass  # Already past the initial screen

        # Focus and fill the pickup input
        pickup_input = await self.page.wait_for_selector(
            self.sel.PICKUP_INPUT, timeout=self._element_timeout
        )
        await pickup_input.click()
        await pickup_input.fill("")  # Clear existing text
        await pickup_input.type(location, delay=50)  # Type with human-like delay

        # Wait for and click the first autocomplete suggestion
        await self.page.wait_for_selector(
            self.sel.SUGGESTION_LIST, timeout=self._element_timeout
        )
        # Small delay to let suggestions fully render
        await self.page.wait_for_timeout(500)
        await self.page.click(self.sel.FIRST_SUGGESTION)

        log.info("uber_pickup_set", location=location)

    async def set_drop(self, location: str) -> None:
        """
        Enter the drop-off location and select the first autocomplete suggestion.

        Same pattern as set_pickup but targeting the destination input.
        """
        log.info("uber_set_drop", location=location)

        drop_input = await self.page.wait_for_selector(
            self.sel.DROP_INPUT, timeout=self._element_timeout
        )
        await drop_input.click()
        await drop_input.fill("")
        await drop_input.type(location, delay=50)

        await self.page.wait_for_selector(
            self.sel.SUGGESTION_LIST, timeout=self._element_timeout
        )
        await self.page.wait_for_timeout(500)
        await self.page.click(self.sel.FIRST_SUGGESTION)

        log.info("uber_drop_set", location=location)

    # ── Ride Options & Quoting ───────────────────────────────────────────

    async def get_ride_options(self) -> list[dict]:
        """
        Read all available ride options (UberGo, Auto, etc.) with fares.

        Returns a list of dicts, each containing:
          - name: ride type name (e.g., "UberGo")
          - fare: estimated fare string (e.g., "₹89")
          - eta: estimated arrival time (if available)
          - element: the Playwright element handle (for clicking later)
        """
        log.info("uber_reading_ride_options")

        # Wait for ride options to load
        await self.page.wait_for_selector(
            self.sel.RIDE_OPTIONS_CONTAINER, timeout=self._element_timeout
        )
        await self.page.wait_for_timeout(1000)  # Let all options render

        options = await self.page.query_selector_all(self.sel.RIDE_OPTION_ITEM)
        ride_options = []

        for option in options:
            try:
                text_content = await option.text_content() or ""
                ride_options.append({
                    "name": text_content.strip(),
                    "element": option,
                })
            except Exception as e:
                log.warning("uber_option_parse_error", error=str(e))

        log.info("uber_ride_options_found", count=len(ride_options))
        return ride_options

    async def get_fare_estimate(self) -> str:
        """Read the fare estimate for the currently selected ride option."""
        try:
            fare_el = await self.page.wait_for_selector(
                self.sel.FARE_ESTIMATE, timeout=self._element_timeout
            )
            fare_text = await fare_el.text_content() if fare_el else "unknown"
            log.info("uber_fare_estimate", fare=fare_text)
            return fare_text or "unknown"
        except PlaywrightTimeout:
            log.warning("uber_fare_estimate_timeout")
            return "unknown"

    async def select_ride_and_get_quote(self, request: RideRequest) -> RideQuote:
        """
        Read ride options, select one, and return the quote.

        If request.ride_type is specified, try to match it.
        Otherwise, select the first (usually cheapest) option.
        """
        options = await self.get_ride_options()

        if not options:
            raise RuntimeError("No ride options found on Uber")

        # Select the first option for now (ride type matching is Phase 2+)
        selected = options[0]
        await selected["element"].click()
        await self.page.wait_for_timeout(500)

        fare = await self.get_fare_estimate()

        return RideQuote(
            platform=PlatformName.UBER,
            ride_type=selected.get("name", "unknown"),
            estimated_fare=fare,
        )

    # ── Booking ──────────────────────────────────────────────────────────

    async def confirm_booking(self) -> None:
        """Click the 'Confirm' / 'Request' button to place the booking."""
        log.info("uber_confirming_booking")

        book_btn = await self.page.wait_for_selector(
            self.sel.BOOK_BUTTON, timeout=self._element_timeout
        )
        await book_btn.click()

        # Wait for confirmation that booking was dispatched
        try:
            await self.page.wait_for_selector(
                self.sel.BOOKING_CONFIRMED_INDICATOR, timeout=self._element_timeout
            )
            log.info("uber_booking_dispatched")
        except PlaywrightTimeout:
            # The page might transition directly to "searching" without a distinct
            # confirmation step — check for the searching indicator instead
            try:
                await self.page.wait_for_selector(
                    self.sel.SEARCHING_INDICATOR, timeout=5000
                )
                log.info("uber_booking_dispatched", indicator="searching_visible")
            except PlaywrightTimeout:
                log.warning("uber_booking_confirmation_ambiguous", url=self.page.url)
                # Proceed anyway — we'll detect the real state via polling

    # ── Status Polling ───────────────────────────────────────────────────

    async def read_ride_status(self) -> RideStatus:
        """
        Read the current ride status from the page.

        Checks for visual indicators in priority order:
        1. Driver card visible → DRIVER_CONFIRMED
        2. "No drivers" message → NO_DRIVER
        3. Searching indicator → POLLING
        4. Login prompt → ERROR (session expired)
        5. None of the above → POLLING (assume still searching)
        """
        now = datetime.now(timezone.utc)

        try:
            # 1. Check for driver assigned (the "win" state)
            if await self.page.is_visible(self.sel.DRIVER_CARD, timeout=1000):
                driver_name = await self._safe_text(self.sel.DRIVER_NAME)
                driver_eta = await self._safe_text(self.sel.DRIVER_ETA)
                vehicle_info = await self._safe_text(self.sel.VEHICLE_INFO)

                eta_seconds = self._parse_eta(driver_eta)

                return RideStatus(
                    platform=PlatformName.UBER,
                    state=BookingState.DRIVER_CONFIRMED,
                    driver_name=driver_name,
                    driver_eta_seconds=eta_seconds,
                    vehicle_info=vehicle_info,
                    timestamp=now,
                    raw_data={"eta_text": driver_eta},
                )

            # 2. Check for "no drivers available"
            if await self.page.is_visible(self.sel.NO_DRIVERS_MESSAGE, timeout=1000):
                return RideStatus(
                    platform=PlatformName.UBER,
                    state=BookingState.NO_DRIVER,
                    timestamp=now,
                )

            # 3. Check for session expiry
            if "login" in self.page.url.lower():
                return RideStatus(
                    platform=PlatformName.UBER,
                    state=BookingState.ERROR,
                    timestamp=now,
                    raw_data={"error": "session_expired", "url": self.page.url},
                )

            # 4. Default: still searching
            return RideStatus(
                platform=PlatformName.UBER,
                state=BookingState.POLLING,
                timestamp=now,
            )

        except Exception as e:
            log.error("uber_status_read_error", error=str(e))
            return RideStatus(
                platform=PlatformName.UBER,
                state=BookingState.ERROR,
                timestamp=now,
                raw_data={"error": str(e)},
            )

    # ── Cancellation ─────────────────────────────────────────────────────

    async def cancel_current_ride(self) -> CancelResult:
        """
        Cancel the currently active ride.

        Steps:
        1. Click the cancel button
        2. Select a cancel reason (if prompted)
        3. Confirm the cancellation
        4. Verify cancellation was successful
        """
        now = datetime.now(timezone.utc)

        try:
            # Click the cancel button
            cancel_btn = await self.page.wait_for_selector(
                self.sel.CANCEL_BUTTON, timeout=self._element_timeout
            )
            await cancel_btn.click()
            log.info("uber_cancel_button_clicked")

            # Select cancel reason if prompted
            try:
                reason = await self.page.wait_for_selector(
                    self.sel.CANCEL_REASON_OPTION, timeout=3000
                )
                if reason:
                    await reason.click()
                    log.debug("uber_cancel_reason_selected")
            except PlaywrightTimeout:
                pass  # No reason prompt — continue to confirmation

            # Confirm cancellation
            try:
                confirm = await self.page.wait_for_selector(
                    self.sel.CONFIRM_CANCEL_BUTTON, timeout=5000
                )
                if confirm:
                    await confirm.click()
                    log.debug("uber_cancel_confirmed")
            except PlaywrightTimeout:
                # Some flows don't have a separate confirmation step
                pass

            # Verify success
            await self.page.wait_for_timeout(1500)

            # Check if we're back to the booking screen or see cancel confirmation
            is_cancelled = (
                await self.page.is_visible(self.sel.CANCEL_SUCCESS_INDICATOR, timeout=3000)
                or await self.page.is_visible(self.sel.WHERE_TO_BUTTON, timeout=2000)
                or not await self.page.is_visible(self.sel.DRIVER_CARD, timeout=1000)
            )

            return CancelResult(
                platform=PlatformName.UBER,
                success=is_cancelled,
                reason=None if is_cancelled else "cancel_verification_failed",
                cancelled_at=now if is_cancelled else None,
            )

        except Exception as e:
            log.error("uber_cancel_error", error=str(e))
            return CancelResult(
                platform=PlatformName.UBER,
                success=False,
                reason=str(e),
            )

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _safe_text(self, selector: str) -> str | None:
        """Safely read text content from a selector, returning None on failure."""
        try:
            el = await self.page.query_selector(selector)
            if el:
                return (await el.text_content() or "").strip()
        except Exception:
            pass
        return None

    @staticmethod
    def _parse_eta(eta_text: str | None) -> int | None:
        """
        Parse an ETA string like '3 min' or '5 minutes' into seconds.

        Returns None if parsing fails.
        """
        if not eta_text:
            return None
        try:
            import re
            match = re.search(r"(\d+)\s*min", eta_text, re.IGNORECASE)
            if match:
                return int(match.group(1)) * 60
        except Exception:
            pass
        return None

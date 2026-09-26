"""
Abstract base class defining the contract for all platform automation adapters.

The orchestrator (dispatcher, first-confirm detector) ONLY talks to adapters
through this interface. It never knows or cares whether the underlying
implementation uses Playwright (Uber) or Appium (Ola, Rapido).

To add a new platform:
  1. Create a new directory under platforms/<name>/
  2. Implement a class that inherits from PlatformAdapter
  3. Implement all 6 abstract methods
  4. Register it in the dispatcher's adapter list
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from voiceride.orchestrator.models import (
    CancelResult,
    PlatformName,
    RideQuote,
    RideRequest,
    RideStatus,
)


class PlatformAdapter(ABC):
    """
    Contract for all platform automation adapters.

    Each adapter manages a single platform's lifecycle:
    initialize → request_quote → book_ride → poll_status (loop) → cancel_ride → teardown
    """

    @property
    @abstractmethod
    def name(self) -> PlatformName:
        """The platform this adapter automates."""
        ...

    @abstractmethod
    async def initialize(self) -> None:
        """
        Launch the automation environment and load persisted session.

        For Uber: launch Playwright browser with persistent context.
        For Ola/Rapido: start Appium session with noReset=true.

        Raises:
            RuntimeError: If the session cannot be initialized.
        """
        ...

    @abstractmethod
    async def request_quote(self, request: RideRequest) -> RideQuote:
        """
        Enter pickup/drop on the platform and return the fare estimate.

        This involves:
        1. Navigating to the booking screen
        2. Entering the pickup location
        3. Entering the drop location
        4. Waiting for and reading the fare estimate

        Args:
            request: The user's ride request with pickup/drop info.

        Returns:
            RideQuote with estimated fare and ride type.

        Raises:
            RuntimeError: If the quote cannot be fetched (e.g., session expired).
        """
        ...

    @abstractmethod
    async def book_ride(self, quote: RideQuote) -> str:
        """
        Confirm the booking on the platform.

        Args:
            quote: The quote to confirm (used to select the right ride type).

        Returns:
            A platform-specific booking identifier (for logging/reference).

        Raises:
            RuntimeError: If booking confirmation fails.
        """
        ...

    @abstractmethod
    async def poll_status(self) -> RideStatus:
        """
        Check the current ride status on the platform.

        Called repeatedly by the polling loop (~every 4 seconds).
        Must detect these key states:
        - POLLING / DISPATCHED: still searching for a driver
        - DRIVER_CONFIRMED: a driver has been assigned
        - NO_DRIVER: platform gave up searching
        - ERROR: something unexpected happened

        Returns:
            RideStatus with the current state and any driver info.
        """
        ...

    @abstractmethod
    async def cancel_ride(self) -> CancelResult:
        """
        Cancel the active ride on this platform.

        Called when another platform found a driver first.
        Must interact with the platform's cancel UI and verify success.

        Returns:
            CancelResult indicating success/failure and reason.
        """
        ...

    @abstractmethod
    async def teardown(self) -> None:
        """
        Close the automation environment gracefully.

        For Uber: close the Playwright browser.
        For Ola/Rapido: quit the Appium session.

        Should NOT raise exceptions — best-effort cleanup.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} platform={self.name.value}>"

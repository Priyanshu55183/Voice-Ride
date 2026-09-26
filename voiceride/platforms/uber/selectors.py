"""
All CSS/XPath selectors for m.uber.com — isolated in one file.

When Uber updates their website, you edit ONLY THIS FILE.
Nothing else in the Uber adapter needs to change.

Each selector has:
  - A descriptive constant name
  - A comment explaining what UI element it targets
  - A "last verified" note (update this when you re-verify)

IMPORTANT: These are initial best-guess selectors. The real selectors MUST
be discovered by inspecting m.uber.com in DevTools. Run `scripts/uber_login.py`
and inspect the page to find the actual data-testid / aria-label / CSS values.
"""


class UberSelectors:
    """
    UI selectors for m.uber.com.
    
    Selector priority (most stable → least stable):
      1. data-testid attributes (most stable — Uber's test infrastructure)
      2. aria-label attributes (accessibility — changes less often)
      3. CSS class selectors (fragile — obfuscated class names change frequently)
      4. XPath (last resort)
    
    Last verified: 2026-09-25 (NEEDS REAL VERIFICATION)
    """

    # ── Landing / Home ───────────────────────────────────────────────────

    # The main "Where to?" or "Get a ride" entry point on the home screen
    WHERE_TO_BUTTON = '[data-testid="ride-request-button"], [aria-label*="Where to"]'

    # ── Location Input ───────────────────────────────────────────────────

    # Pickup location input field
    PICKUP_INPUT = (
        'input[data-testid="pickup-input"], '
        'input[aria-label*="Pickup"], '
        'input[placeholder*="Pickup"]'
    )

    # Drop-off location input field
    DROP_INPUT = (
        'input[data-testid="destination-input"], '
        'input[aria-label*="Dropoff"], '
        'input[aria-label*="destination"], '
        'input[placeholder*="Where to"]'
    )

    # Autocomplete suggestion list container
    SUGGESTION_LIST = (
        '[data-testid="location-suggestions"], '
        '[data-testid="suggestion-list"], '
        'ul[role="listbox"]'
    )

    # First autocomplete suggestion (top result)
    FIRST_SUGGESTION = (
        '[data-testid="location-suggestions"] li:first-child, '
        '[data-testid="suggestion-list"] li:first-child, '
        'ul[role="listbox"] li:first-child'
    )

    # ── Ride Options ─────────────────────────────────────────────────────

    # Container for ride type options (UberGo, Auto, etc.)
    RIDE_OPTIONS_CONTAINER = (
        '[data-testid="ride-options"], '
        '[data-testid="product-selector"]'
    )

    # Individual ride option item (generic — matches any ride type)
    RIDE_OPTION_ITEM = (
        '[data-testid*="product-option"], '
        '[data-testid*="ride-option"]'
    )

    # Fare estimate text within a ride option
    FARE_ESTIMATE = (
        '[data-testid="fare-estimate"], '
        '[data-testid*="price"]'
    )

    # ETA text within a ride option
    ETA_ESTIMATE = (
        '[data-testid="eta-estimate"], '
        '[data-testid*="eta"]'
    )

    # ── Booking Confirmation ─────────────────────────────────────────────

    # The main "Confirm" / "Request" / "Book" button
    BOOK_BUTTON = (
        'button[data-testid="confirm-booking-btn"], '
        'button[data-testid="request-ride-btn"], '
        'button[aria-label*="Confirm"], '
        'button[aria-label*="Request"]'
    )

    # Indicator that booking has been dispatched (driver search started)
    BOOKING_CONFIRMED_INDICATOR = (
        '[data-testid="booking-confirmed"], '
        '[data-testid="ride-dispatched"], '
        '[data-testid="looking-for-driver"]'
    )

    # ── Driver Search / Status ───────────────────────────────────────────

    # Searching/matching animation or text
    SEARCHING_INDICATOR = (
        '[data-testid="searching-for-driver"], '
        '[data-testid="looking-for-driver"], '
        '[data-testid="matching"]'
    )

    # Driver info card (appears when driver is assigned)
    DRIVER_CARD = (
        '[data-testid="driver-info-card"], '
        '[data-testid="driver-details"], '
        '[data-testid="trip-driver"]'
    )

    # Driver name text within the driver card
    DRIVER_NAME = (
        '[data-testid="driver-name"], '
        '[data-testid="driver-info-card"] [data-testid*="name"]'
    )

    # Driver ETA text
    DRIVER_ETA = (
        '[data-testid="driver-eta"], '
        '[data-testid="arrival-time"]'
    )

    # Vehicle info (make, model, plate number)
    VEHICLE_INFO = (
        '[data-testid="vehicle-info"], '
        '[data-testid="vehicle-details"]'
    )

    # "No drivers available" / "Try again" message
    NO_DRIVERS_MESSAGE = (
        '[data-testid="no-drivers-available"], '
        '[data-testid="no-drivers"], '
        'text="No drivers available"'
    )

    # ── Cancellation ─────────────────────────────────────────────────────

    # Cancel ride button (usually in ride status screen)
    CANCEL_BUTTON = (
        'button[data-testid="cancel-ride-btn"], '
        'button[data-testid="cancel-trip"], '
        'button[aria-label*="Cancel"]'
    )

    # Cancel reason selection (if prompted)
    CANCEL_REASON_OPTION = (
        '[data-testid="cancel-reason-option"]:first-child, '
        '[data-testid*="cancel-reason"] li:first-child'
    )

    # Confirm cancellation button (in the confirmation dialog)
    CONFIRM_CANCEL_BUTTON = (
        'button[data-testid="confirm-cancel-btn"], '
        'button[data-testid="confirm-cancellation"], '
        'button[aria-label*="Yes, cancel"]'
    )

    # Success indicator after cancellation
    CANCEL_SUCCESS_INDICATOR = (
        '[data-testid="cancel-confirmed"], '
        '[data-testid="ride-cancelled"], '
        'text="Ride cancelled"'
    )

    # ── Session / Auth ───────────────────────────────────────────────────

    # Login prompt or redirect indicator
    LOGIN_PROMPT = (
        '[data-testid="login-form"], '
        'form[action*="login"], '
        'input[name="phoneNumber"]'
    )

    # User avatar / account menu (indicates logged-in state)
    USER_AVATAR = (
        '[data-testid="user-avatar"], '
        '[data-testid="account-menu"], '
        '[aria-label*="Account"]'
    )

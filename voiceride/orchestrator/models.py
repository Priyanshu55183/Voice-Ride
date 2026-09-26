"""
Core data models that flow through the entire VoiceRide system.

These Pydantic models are the "common language" between the orchestrator,
platform adapters, storage, and notifications. Every module imports from here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ─── Enums ────────────────────────────────────────────────────────────────────


class BookingState(str, Enum):
    """All possible states in a booking run's lifecycle."""

    IDLE = "idle"
    """Initial state — run created but nothing started yet."""

    REQUESTING = "requesting"
    """Sending the ride request to the platform."""

    QUOTED = "quoted"
    """Platform returned a fare estimate / ride options."""

    DISPATCHED = "dispatched"
    """Booking confirmed, platform is searching for a driver."""

    POLLING = "polling"
    """Actively polling the platform for driver assignment."""

    DRIVER_CONFIRMED = "driver_confirmed"
    """A driver has been assigned. This is the 'win' state."""

    NO_DRIVER = "no_driver"
    """Platform gave up — no drivers available."""

    CANCELLED = "cancelled"
    """We cancelled the ride (because another platform won)."""

    CANCEL_FAILED = "cancel_failed"
    """Cancel was attempted but failed after all retries."""

    ERROR = "error"
    """Something went wrong (adapter crash, session expired, etc.)."""


class EventType(str, Enum):
    """Types of events logged to the event_log table."""

    STATE_CHANGE = "state_change"
    QUOTE_FETCHED = "quote_fetched"
    BOOKING_PLACED = "booking_placed"
    STATUS_POLLED = "status_polled"
    DRIVER_CONFIRMED = "driver_confirmed"
    CANCEL_TRIGGERED = "cancel_triggered"
    CANCEL_SUCCESS = "cancel_success"
    CANCEL_FAILED = "cancel_failed"
    CANCEL_RETRY = "cancel_retry"
    ERROR = "error"
    TIMEOUT = "timeout"
    SESSION_EXPIRED = "session_expired"
    RUN_COMPLETED = "run_completed"
    NOTIFICATION_SENT = "notification_sent"


class PlatformName(str, Enum):
    """Supported cab booking platforms."""

    UBER = "uber"
    OLA = "ola"
    RAPIDO = "rapido"


# ─── Request / Response Models ────────────────────────────────────────────────


class RideRequest(BaseModel):
    """What the user wants — extracted from voice or CLI input."""

    pickup: str
    """Pickup location (place name or address)."""

    drop: str
    """Drop-off location (place name or address)."""

    pickup_lat: float | None = None
    pickup_lng: float | None = None
    drop_lat: float | None = None
    drop_lng: float | None = None

    ride_type: str | None = None
    """Preferred ride type: 'auto', 'mini', 'sedan', 'suv', 'bike', or None for 'ask me'."""


class RideQuote(BaseModel):
    """Fare estimate returned by a platform after entering pickup/drop."""

    platform: PlatformName
    ride_type: str
    estimated_fare: str
    """Display string like '₹89' or '₹120-150'."""

    estimated_eta: str | None = None
    """Estimated time of arrival like '3 min' (if available at quote stage)."""

    raw_data: dict[str, Any] = Field(default_factory=dict)
    """Platform-specific extra data for debugging."""


class RideStatus(BaseModel):
    """Current state of a ride on a single platform. Returned by poll_status()."""

    platform: PlatformName
    state: BookingState

    driver_name: str | None = None
    driver_eta_seconds: int | None = None
    vehicle_info: str | None = None
    """E.g. 'White Swift Dzire - KA 01 AB 1234'."""

    raw_data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CancelResult(BaseModel):
    """Result of attempting to cancel a ride on a platform."""

    platform: PlatformName
    success: bool
    reason: str | None = None
    """If failed: why (e.g. 'cancel button not found', 'already picked up')."""

    cancelled_at: datetime | None = None
    retry_count: int = 0


# ─── Booking Run (top-level orchestration unit) ──────────────────────────────


class BookingRun(BaseModel):
    """One complete invocation of VoiceRide — from request to outcome."""

    id: str
    """UUID for this run."""

    pickup: str
    drop: str
    ride_type: str | None = None

    state: BookingState = BookingState.IDLE
    """Current overall state of the run."""

    platforms: list[PlatformName] = Field(default_factory=list)
    """Which platforms are being used in this run."""

    winning_platform: PlatformName | None = None
    """The platform that found a driver first (if any)."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class EventLog(BaseModel):
    """A single logged event in the audit trail."""

    id: int | None = None
    run_id: str
    platform: PlatformName | None = None
    event_type: EventType
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

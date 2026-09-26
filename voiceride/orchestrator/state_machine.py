"""
Per-booking-run state machine with persistence.

Manages the lifecycle of each booking run, validating that state transitions
are legal and persisting every change to SQLite. If the process crashes,
the database knows which bookings are still active.

Valid transitions:
    IDLE → REQUESTING → QUOTED → DISPATCHED → POLLING → DRIVER_CONFIRMED
                                                       → NO_DRIVER
                                                       → CANCELLED
                                                       → CANCEL_FAILED
    Any state → ERROR (something broke)
"""

from __future__ import annotations

import structlog

from voiceride.orchestrator.models import BookingState, EventType, PlatformName
from voiceride.storage.database import Database

log = structlog.get_logger()

# ─── Legal Transitions ───────────────────────────────────────────────────────

# Maps each state to the set of states it can transition TO
VALID_TRANSITIONS: dict[BookingState, set[BookingState]] = {
    BookingState.IDLE: {BookingState.REQUESTING, BookingState.ERROR},
    BookingState.REQUESTING: {BookingState.QUOTED, BookingState.ERROR},
    BookingState.QUOTED: {BookingState.DISPATCHED, BookingState.ERROR},
    BookingState.DISPATCHED: {BookingState.POLLING, BookingState.ERROR},
    BookingState.POLLING: {
        BookingState.DRIVER_CONFIRMED,
        BookingState.NO_DRIVER,
        BookingState.CANCELLED,
        BookingState.CANCEL_FAILED,
        BookingState.ERROR,
    },
    # Terminal states — no further transitions (except ERROR as catch-all)
    BookingState.DRIVER_CONFIRMED: {BookingState.ERROR},
    BookingState.NO_DRIVER: {BookingState.ERROR},
    BookingState.CANCELLED: set(),
    BookingState.CANCEL_FAILED: set(),
    BookingState.ERROR: set(),
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, run_id: str, from_state: BookingState, to_state: BookingState):
        self.run_id = run_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid transition for run {run_id}: {from_state.value} → {to_state.value}"
        )


class BookingStateMachine:
    """Manages state transitions for a single booking run, with DB persistence."""

    def __init__(self, db: Database, run_id: str):
        self.db = db
        self.run_id = run_id
        self._current_state: BookingState | None = None

    async def get_state(self) -> BookingState:
        """Read the current state from the database."""
        run = await self.db.get_booking_run(self.run_id)
        if run is None:
            raise ValueError(f"Booking run {self.run_id} not found in database")
        self._current_state = run.state
        return self._current_state

    async def transition(
        self,
        new_state: BookingState,
        winning_platform: PlatformName | None = None,
        detail: dict | None = None,
    ) -> None:
        """
        Transition to a new state.

        Validates the transition, updates the DB, and logs the state change event.
        Raises InvalidTransitionError if the transition isn't allowed.
        """
        current = await self.get_state()

        # Validate the transition
        allowed = VALID_TRANSITIONS.get(current, set())
        if new_state not in allowed:
            raise InvalidTransitionError(self.run_id, current, new_state)

        old_state = current

        # Persist to database
        await self.db.update_run_state(self.run_id, new_state, winning_platform)

        # Log the state change as an event
        await self.db.log_event(
            run_id=self.run_id,
            event_type=EventType.STATE_CHANGE,
            detail={
                "from": old_state.value,
                "to": new_state.value,
                **(detail or {}),
            },
        )

        self._current_state = new_state
        log.info(
            "state_transition",
            run_id=self.run_id,
            from_state=old_state.value,
            to_state=new_state.value,
        )

    @property
    def is_terminal(self) -> bool:
        """Check if the current state is a terminal (final) state."""
        if self._current_state is None:
            return False
        return self._current_state in {
            BookingState.DRIVER_CONFIRMED,
            BookingState.NO_DRIVER,
            BookingState.CANCELLED,
            BookingState.CANCEL_FAILED,
            BookingState.ERROR,
        }

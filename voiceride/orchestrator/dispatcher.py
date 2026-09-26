"""
Parallel booking dispatcher — launches rides on multiple platforms simultaneously.

Uses asyncio.gather to run all platform adapters concurrently. Each platform
gets its own async task that runs independently. The dispatcher handles per-platform
failures gracefully — if one platform crashes, the others continue.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import structlog

from voiceride.orchestrator.models import (
    BookingRun,
    BookingState,
    EventType,
    PlatformName,
    RideRequest,
    RideQuote,
)
from voiceride.orchestrator.state_machine import BookingStateMachine
from voiceride.platforms.base import PlatformAdapter
from voiceride.storage.database import Database

log = structlog.get_logger()


class PlatformTask:
    """Result of a single platform's quote + book attempt."""

    def __init__(self, platform: PlatformName):
        self.platform = platform
        self.quote: RideQuote | None = None
        self.booking_id: str | None = None
        self.error: str | None = None
        self.success: bool = False


class ParallelDispatcher:
    """
    Launches booking requests on multiple platforms simultaneously.

    For Phase 1 (Uber-only), this runs a single adapter.
    For Phase 4+, it runs Uber + Ola (+ Rapido) concurrently via asyncio.gather.
    """

    def __init__(self, adapters: list[PlatformAdapter], db: Database):
        self.adapters = adapters
        self.db = db

    async def dispatch(self, request: RideRequest) -> tuple[str, list[PlatformTask]]:
        """
        Create a booking run and dispatch ride requests to all adapters.

        Returns:
            Tuple of (run_id, list of PlatformTask results).
        """
        # Create the booking run
        run_id = uuid4().hex[:12]
        run = BookingRun(
            id=run_id,
            pickup=request.pickup,
            drop=request.drop,
            ride_type=request.ride_type,
            platforms=[adapter.name for adapter in self.adapters],
        )
        await self.db.create_booking_run(run)

        state_machine = BookingStateMachine(self.db, run_id)
        await state_machine.transition(BookingState.REQUESTING)

        log.info(
            "dispatch_starting",
            run_id=run_id,
            platforms=[a.name.value for a in self.adapters],
            pickup=request.pickup,
            drop=request.drop,
        )

        # Launch all platforms concurrently
        tasks = [
            self._run_platform(adapter, request, run_id)
            for adapter in self.adapters
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # Check how many succeeded
        successes = [r for r in results if r.success]
        failures = [r for r in results if not r.success]

        if failures:
            for f in failures:
                log.warning(
                    "platform_dispatch_failed",
                    run_id=run_id,
                    platform=f.platform.value,
                    error=f.error,
                )

        if not successes:
            await state_machine.transition(BookingState.ERROR, detail={"reason": "all_platforms_failed"})
            raise RuntimeError(f"All platforms failed to book: {[f.error for f in failures]}")

        # At least one platform succeeded — move to DISPATCHED
        await state_machine.transition(BookingState.QUOTED)
        await state_machine.transition(BookingState.DISPATCHED)

        log.info(
            "dispatch_complete",
            run_id=run_id,
            booked_platforms=[s.platform.value for s in successes],
            failed_platforms=[f.platform.value for f in failures],
        )

        return run_id, results

    async def _run_platform(
        self, adapter: PlatformAdapter, request: RideRequest, run_id: str
    ) -> PlatformTask:
        """
        Run the full quote → book flow for a single platform.

        Catches all exceptions so one platform's failure doesn't kill the others.
        """
        task = PlatformTask(adapter.name)

        try:
            # Step 1: Get fare quote
            quote = await adapter.request_quote(request)
            task.quote = quote

            await self.db.log_event(
                run_id=run_id,
                event_type=EventType.QUOTE_FETCHED,
                platform=adapter.name,
                detail={
                    "ride_type": quote.ride_type,
                    "fare": quote.estimated_fare,
                    "eta": quote.estimated_eta,
                },
            )

            # Step 2: Confirm booking
            booking_id = await adapter.book_ride(quote)
            task.booking_id = booking_id
            task.success = True

            await self.db.log_event(
                run_id=run_id,
                event_type=EventType.BOOKING_PLACED,
                platform=adapter.name,
                detail={"booking_id": booking_id},
            )

            log.info(
                "platform_booked",
                run_id=run_id,
                platform=adapter.name.value,
                booking_id=booking_id,
                fare=quote.estimated_fare,
            )

        except Exception as e:
            task.error = str(e)
            log.error(
                "platform_dispatch_error",
                run_id=run_id,
                platform=adapter.name.value,
                error=str(e),
                exc_info=True,
            )
            await self.db.log_event(
                run_id=run_id,
                event_type=EventType.ERROR,
                platform=adapter.name,
                detail={"error": str(e), "phase": "dispatch"},
            )

        return task

"""
First-confirm detector and cancel-others executor.

The core differentiating logic of VoiceRide:
  1. Poll all booked platforms concurrently (async tasks, ~4s interval each)
  2. The MOMENT any platform reports DRIVER_CONFIRMED → it's the winner
  3. Immediately signal all other pollers to stop
  4. Cancel all non-winning platforms with retry + backoff
  5. Return the winning platform's status for TTS confirmation

Tiebreaker: if two platforms confirm in the same polling cycle, the one with
the earlier timestamp wins. If timestamps are within 1s, prefer lower fare.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from voiceride.config import settings
from voiceride.orchestrator.models import (
    BookingState,
    CancelResult,
    EventType,
    PlatformName,
    RideStatus,
)
from voiceride.orchestrator.state_machine import BookingStateMachine
from voiceride.platforms.base import PlatformAdapter
from voiceride.storage.database import Database

log = structlog.get_logger()


class CancelExecutor:
    """Handles cancellation of a single platform with retry + exponential backoff."""

    def __init__(self, adapter: PlatformAdapter, db: Database, run_id: str):
        self.adapter = adapter
        self.db = db
        self.run_id = run_id

    async def cancel_with_retry(self) -> CancelResult:
        """
        Attempt to cancel the ride, retrying with exponential backoff on failure.

        Retry schedule (with default backoff_base=2.0):
          Attempt 1: immediate
          Attempt 2: wait 2s
          Attempt 3: wait 4s
          Attempt 4: wait 8s (if max_retries=3, this is the last)
        """
        last_result = None

        for attempt in range(1 + settings.cancel_max_retries):
            if attempt > 0:
                wait = settings.cancel_backoff_base ** attempt
                log.info(
                    "cancel_retry_waiting",
                    platform=self.adapter.name.value,
                    attempt=attempt,
                    wait_seconds=wait,
                )
                await self.db.log_event(
                    run_id=self.run_id,
                    event_type=EventType.CANCEL_RETRY,
                    platform=self.adapter.name,
                    detail={"attempt": attempt, "wait_seconds": wait},
                )
                await asyncio.sleep(wait)

            try:
                result = await self.adapter.cancel_ride()
                last_result = result
                result.retry_count = attempt

                if result.success:
                    log.info(
                        "cancel_success",
                        platform=self.adapter.name.value,
                        attempt=attempt,
                    )
                    await self.db.log_event(
                        run_id=self.run_id,
                        event_type=EventType.CANCEL_SUCCESS,
                        platform=self.adapter.name,
                        detail={"attempt": attempt},
                    )
                    return result
                else:
                    log.warning(
                        "cancel_attempt_failed",
                        platform=self.adapter.name.value,
                        attempt=attempt,
                        reason=result.reason,
                    )

            except Exception as e:
                log.error(
                    "cancel_attempt_exception",
                    platform=self.adapter.name.value,
                    attempt=attempt,
                    error=str(e),
                )
                last_result = CancelResult(
                    platform=self.adapter.name,
                    success=False,
                    reason=str(e),
                    retry_count=attempt,
                )

        # All retries exhausted
        log.error(
            "cancel_all_retries_exhausted",
            platform=self.adapter.name.value,
            total_attempts=1 + settings.cancel_max_retries,
        )
        await self.db.log_event(
            run_id=self.run_id,
            event_type=EventType.CANCEL_FAILED,
            platform=self.adapter.name,
            detail={
                "total_attempts": 1 + settings.cancel_max_retries,
                "last_reason": last_result.reason if last_result else "unknown",
            },
        )

        return last_result or CancelResult(
            platform=self.adapter.name,
            success=False,
            reason="all retries exhausted",
        )


class FirstConfirmDetector:
    """
    Polls all platforms concurrently and detects the first driver confirmation.

    On detection:
    1. Records the winner
    2. Signals other pollers to stop
    3. Cancels all non-winning platforms
    """

    def __init__(
        self,
        adapters: list[PlatformAdapter],
        db: Database,
        run_id: str,
        quotes: dict[PlatformName, dict] | None = None,
    ):
        self.adapters = adapters
        self.db = db
        self.run_id = run_id
        self.quotes = quotes or {}

        # Coordination primitives
        self._stop_event = asyncio.Event()
        self._winner: PlatformName | None = None
        self._winner_status: RideStatus | None = None
        self._results: dict[PlatformName, RideStatus] = {}
        self._cancel_results: dict[PlatformName, CancelResult] = {}

    @property
    def winner(self) -> PlatformName | None:
        return self._winner

    @property
    def winner_status(self) -> RideStatus | None:
        return self._winner_status

    @property
    def cancel_results(self) -> dict[PlatformName, CancelResult]:
        return self._cancel_results

    async def run(self) -> RideStatus | None:
        """
        Start polling all platforms. Returns when:
        - A driver is confirmed on any platform (returns the winning status)
        - All platforms report NO_DRIVER/ERROR (returns None)
        """
        state_machine = BookingStateMachine(self.db, self.run_id)
        await state_machine.transition(BookingState.POLLING)

        log.info(
            "polling_started",
            run_id=self.run_id,
            platforms=[a.name.value for a in self.adapters],
            interval=settings.poll_interval_seconds,
            max_polls=settings.max_poll_count,
        )

        # Launch a poller for each platform
        tasks = [self._poll_one(adapter) for adapter in self.adapters]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle results
        if self._winner:
            # We have a winner — cancel the others
            await self._cancel_others()

            await state_machine.transition(
                BookingState.DRIVER_CONFIRMED,
                winning_platform=self._winner,
                detail={
                    "driver": self._winner_status.driver_name if self._winner_status else None,
                    "eta": self._winner_status.driver_eta_seconds if self._winner_status else None,
                },
            )

            await self.db.log_event(
                run_id=self.run_id,
                event_type=EventType.RUN_COMPLETED,
                platform=self._winner,
                detail={
                    "outcome": "driver_confirmed",
                    "winner": self._winner.value,
                    "cancel_results": {
                        k.value: {"success": v.success, "reason": v.reason}
                        for k, v in self._cancel_results.items()
                    },
                },
            )

            return self._winner_status
        else:
            # No winner — all platforms failed
            await state_machine.transition(
                BookingState.NO_DRIVER,
                detail={"outcome": "all_platforms_no_driver"},
            )

            await self.db.log_event(
                run_id=self.run_id,
                event_type=EventType.RUN_COMPLETED,
                detail={"outcome": "no_driver_found"},
            )

            log.warning("all_platforms_no_driver", run_id=self.run_id)
            return None

    async def _poll_one(self, adapter: PlatformAdapter) -> RideStatus | None:
        """
        Poll a single platform until:
        - Driver found (return the status)
        - No driver / error / timeout (return the last status)
        - Another platform already won (return None)
        """
        platform = adapter.name

        for poll_count in range(1, settings.max_poll_count + 1):
            # Check if another platform already won
            if self._stop_event.is_set():
                log.info("poller_stopped_by_winner", platform=platform.value)
                return None

            try:
                status = await adapter.poll_status()
                self._results[platform] = status

                await self.db.log_event(
                    run_id=self.run_id,
                    event_type=EventType.STATUS_POLLED,
                    platform=platform,
                    detail={
                        "state": status.state.value,
                        "poll_count": poll_count,
                        "driver": status.driver_name,
                        "eta": status.driver_eta_seconds,
                    },
                )

                # Check for driver confirmation
                if status.state == BookingState.DRIVER_CONFIRMED:
                    log.info(
                        "driver_confirmed",
                        platform=platform.value,
                        driver=status.driver_name,
                        eta=status.driver_eta_seconds,
                        poll_count=poll_count,
                    )

                    await self.db.log_event(
                        run_id=self.run_id,
                        event_type=EventType.DRIVER_CONFIRMED,
                        platform=platform,
                        detail={
                            "driver": status.driver_name,
                            "eta": status.driver_eta_seconds,
                            "vehicle": status.vehicle_info,
                            "poll_count": poll_count,
                        },
                    )

                    # Try to claim the win (handles near-simultaneous confirms)
                    self._try_claim_winner(platform, status)
                    return status

                # Check for terminal failure states
                if status.state in (BookingState.NO_DRIVER, BookingState.ERROR):
                    log.info(
                        "platform_gave_up",
                        platform=platform.value,
                        state=status.state.value,
                        poll_count=poll_count,
                    )
                    return status

            except Exception as e:
                log.error(
                    "poll_error",
                    platform=platform.value,
                    poll_count=poll_count,
                    error=str(e),
                )
                await self.db.log_event(
                    run_id=self.run_id,
                    event_type=EventType.ERROR,
                    platform=platform,
                    detail={"error": str(e), "poll_count": poll_count},
                )

            # Wait before next poll
            await asyncio.sleep(settings.poll_interval_seconds)

        # Max polls reached — treat as timeout
        log.warning(
            "poll_timeout",
            platform=platform.value,
            max_polls=settings.max_poll_count,
        )
        await self.db.log_event(
            run_id=self.run_id,
            event_type=EventType.TIMEOUT,
            platform=platform,
            detail={"max_polls": settings.max_poll_count},
        )

        return RideStatus(
            platform=platform,
            state=BookingState.NO_DRIVER,
            timestamp=datetime.now(timezone.utc),
            raw_data={"reason": "poll_timeout"},
        )

    def _try_claim_winner(self, platform: PlatformName, status: RideStatus) -> None:
        """
        Attempt to claim this platform as the winner.

        Handles the near-simultaneous case: if another platform already claimed
        the win, compare timestamps. Earlier timestamp wins. If tied, keep the
        first claimer (arbitrary but deterministic).
        """
        if self._winner is None:
            # First to claim — take it
            self._winner = platform
            self._winner_status = status
            self._stop_event.set()  # Signal other pollers to stop
            log.info("winner_claimed", platform=platform.value)
        else:
            # Another platform already won — compare timestamps (tiebreaker)
            if self._winner_status and status.timestamp < self._winner_status.timestamp:
                old_winner = self._winner
                self._winner = platform
                self._winner_status = status
                log.info(
                    "winner_overridden_by_earlier_timestamp",
                    new_winner=platform.value,
                    old_winner=old_winner.value,
                )
            else:
                log.info(
                    "winner_already_claimed",
                    existing_winner=self._winner.value,
                    rejected=platform.value,
                )

    async def _cancel_others(self) -> None:
        """Cancel all non-winning platforms with retry + backoff."""
        if self._winner is None:
            return

        cancel_tasks = []
        for adapter in self.adapters:
            if adapter.name != self._winner:
                log.info("cancel_triggered", platform=adapter.name.value, run_id=self.run_id)
                await self.db.log_event(
                    run_id=self.run_id,
                    event_type=EventType.CANCEL_TRIGGERED,
                    platform=adapter.name,
                )
                executor = CancelExecutor(adapter, self.db, self.run_id)
                cancel_tasks.append(self._cancel_one(executor, adapter.name))

        if cancel_tasks:
            await asyncio.gather(*cancel_tasks)

    async def _cancel_one(self, executor: CancelExecutor, platform: PlatformName) -> None:
        """Cancel a single platform and store the result."""
        result = await executor.cancel_with_retry()
        self._cancel_results[platform] = result

        if not result.success:
            log.error(
                "cancel_failed_after_retries",
                platform=platform.value,
                reason=result.reason,
                run_id=self.run_id,
            )

"""
SQLite database layer — booking runs, event logging, and state persistence.

Uses aiosqlite for async operations so DB writes never block the polling loops.
The database is the crash-safety net: if VoiceRide dies mid-booking, the DB
knows which bookings are still active so you can manually check and cancel.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import structlog

from voiceride.config import settings
from voiceride.orchestrator.models import (
    BookingRun,
    BookingState,
    EventLog,
    EventType,
    PlatformName,
)

log = structlog.get_logger()

# ─── Schema ──────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS booking_runs (
    id               TEXT PRIMARY KEY,
    pickup           TEXT NOT NULL,
    dropoff          TEXT NOT NULL,
    ride_type        TEXT,
    state            TEXT NOT NULL DEFAULT 'idle',
    platforms        TEXT NOT NULL DEFAULT '[]',
    winning_platform TEXT,
    created_at       TEXT NOT NULL,
    completed_at     TEXT
);

CREATE TABLE IF NOT EXISTS event_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES booking_runs(id),
    platform    TEXT,
    event_type  TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_log_run_id ON event_log(run_id);
CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON event_log(created_at);
CREATE INDEX IF NOT EXISTS idx_booking_runs_state ON booking_runs(state);
"""


class Database:
    """Async SQLite wrapper for VoiceRide state and event persistence."""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or settings.get_db_path()
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database connection and ensure schema exists."""
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        # Enable WAL mode for better concurrent read/write performance
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()
        log.info("database_connected", path=str(self._db_path))

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            log.info("database_closed")

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    # ─── Booking Runs ────────────────────────────────────────────────────

    async def create_booking_run(self, run: BookingRun) -> None:
        """Insert a new booking run."""
        await self.conn.execute(
            """
            INSERT INTO booking_runs (id, pickup, dropoff, ride_type, state, platforms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                run.pickup,
                run.drop,
                run.ride_type,
                run.state.value,
                json.dumps([p.value for p in run.platforms]),
                run.created_at.isoformat(),
            ),
        )
        await self.conn.commit()
        log.info("booking_run_created", run_id=run.id, pickup=run.pickup, drop=run.drop)

    async def update_run_state(
        self,
        run_id: str,
        new_state: BookingState,
        winning_platform: PlatformName | None = None,
    ) -> None:
        """Update the state of a booking run."""
        completed_at = None
        if new_state in (
            BookingState.DRIVER_CONFIRMED,
            BookingState.NO_DRIVER,
            BookingState.CANCELLED,
            BookingState.ERROR,
        ):
            completed_at = datetime.now(timezone.utc).isoformat()

        await self.conn.execute(
            """
            UPDATE booking_runs
            SET state = ?, winning_platform = ?, completed_at = COALESCE(?, completed_at)
            WHERE id = ?
            """,
            (new_state.value, winning_platform.value if winning_platform else None, completed_at, run_id),
        )
        await self.conn.commit()
        log.info("run_state_updated", run_id=run_id, state=new_state.value, winner=winning_platform)

    async def get_booking_run(self, run_id: str) -> BookingRun | None:
        """Fetch a single booking run by ID."""
        cursor = await self.conn.execute("SELECT * FROM booking_runs WHERE id = ?", (run_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_booking_run(row)

    async def get_active_runs(self) -> list[BookingRun]:
        """Fetch all booking runs that are still in-progress (not completed).
        
        Useful for crash recovery: on restart, check if any runs were left in 
        DISPATCHED/POLLING state and alert the user.
        """
        cursor = await self.conn.execute(
            """
            SELECT * FROM booking_runs
            WHERE state IN (?, ?, ?, ?)
            ORDER BY created_at DESC
            """,
            (
                BookingState.REQUESTING.value,
                BookingState.QUOTED.value,
                BookingState.DISPATCHED.value,
                BookingState.POLLING.value,
            ),
        )
        rows = await cursor.fetchall()
        return [self._row_to_booking_run(row) for row in rows]

    async def get_recent_runs(self, limit: int = 20) -> list[BookingRun]:
        """Fetch the most recent booking runs."""
        cursor = await self.conn.execute(
            "SELECT * FROM booking_runs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_booking_run(row) for row in rows]

    # ─── Event Log ───────────────────────────────────────────────────────

    async def log_event(
        self,
        run_id: str,
        event_type: EventType,
        platform: PlatformName | None = None,
        detail: dict | None = None,
    ) -> None:
        """Log an event to the audit trail."""
        now = datetime.now(timezone.utc).isoformat()
        await self.conn.execute(
            """
            INSERT INTO event_log (run_id, platform, event_type, detail, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                platform.value if platform else None,
                event_type.value,
                json.dumps(detail or {}),
                now,
            ),
        )
        await self.conn.commit()
        log.debug(
            "event_logged",
            run_id=run_id,
            platform=platform,
            event_type=event_type.value,
            detail=detail,
        )

    async def get_run_events(self, run_id: str) -> list[EventLog]:
        """Fetch all events for a booking run, ordered chronologically."""
        cursor = await self.conn.execute(
            "SELECT * FROM event_log WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_event_log(row) for row in rows]

    # ─── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_booking_run(row: aiosqlite.Row) -> BookingRun:
        platforms_raw = json.loads(row["platforms"]) if row["platforms"] else []
        return BookingRun(
            id=row["id"],
            pickup=row["pickup"],
            drop=row["dropoff"],
            ride_type=row["ride_type"],
            state=BookingState(row["state"]),
            platforms=[PlatformName(p) for p in platforms_raw],
            winning_platform=PlatformName(row["winning_platform"]) if row["winning_platform"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        )

    @staticmethod
    def _row_to_event_log(row: aiosqlite.Row) -> EventLog:
        return EventLog(
            id=row["id"],
            run_id=row["run_id"],
            platform=PlatformName(row["platform"]) if row["platform"] else None,
            event_type=EventType(row["event_type"]),
            detail=json.loads(row["detail"]) if row["detail"] else {},
            created_at=datetime.fromisoformat(row["created_at"]),
        )

"""
Structured logging configuration.

Sets up dual output:
  1. Pretty, colorized console output (via Rich/structlog)
  2. Machine-readable JSON lines to a rotating log file

Every event gets: timestamp, log level, and all keyword context passed by the caller.

Usage anywhere in the codebase:
    import structlog
    log = structlog.get_logger()
    log.info("status_polled", platform="uber", state="searching", poll_count=3)
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

from voiceride.config import settings


def setup_logging() -> None:
    """Configure structured logging for the entire application. Call once at startup."""

    log_dir = settings.get_log_dir()
    log_file = log_dir / "voiceride.log"

    # ── Standard library root logger (catches logs from third-party libs too) ──
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    # Console handler — human-readable
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    # File handler — JSON lines, rotated at 10 MB, keep 5 backups
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # ── Structlog configuration ──
    # Shared processors: run for both console and file output
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            # For stdlib integration: format the event for stdlib handlers
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Formatter for console: colorized, human-readable
    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
    )

    # Formatter for file: JSON lines
    file_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    console_handler.setFormatter(console_formatter)
    file_handler.setFormatter(file_formatter)

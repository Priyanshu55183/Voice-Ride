"""
Centralized configuration loaded from environment variables and .env file.

All tunable parameters live here — no magic numbers scattered across the codebase.
Import as: `from voiceride.config import settings`
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings. Values are loaded from .env file and environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Polling ──
    poll_interval_seconds: float = 4.0
    """How often (seconds) to check each platform's ride status."""

    max_poll_count: int = 75
    """Maximum number of polls before giving up (~5 min at 4s interval)."""

    # ── Uber ──
    uber_headless: bool = False
    """Run Playwright in headless mode? False = show browser window (useful for debugging)."""

    uber_user_data_dir: str = "./data/uber_session"
    """Directory for Playwright persistent context (cookies/session storage)."""

    uber_base_url: str = "https://m.uber.com"
    """Uber mobile web URL to automate."""

    uber_page_load_timeout: int = 30000
    """Max milliseconds to wait for m.uber.com pages to load."""

    uber_element_timeout: int = 15000
    """Max milliseconds to wait for individual UI elements to appear."""

    # ── Retry (cancel operations) ──
    cancel_max_retries: int = 3
    """Number of cancel retry attempts before alerting the user."""

    cancel_backoff_base: float = 2.0
    """Base for exponential backoff on cancel retries (2.0 → waits of 2s, 4s, 8s)."""

    # ── Logging ──
    log_level: str = "INFO"
    """Minimum log level: DEBUG, INFO, WARNING, ERROR."""

    log_dir: str = "./logs"
    """Directory for log files."""

    # ── Database ──
    database_path: str = "./data/voiceride.db"
    """Path to the SQLite database file."""

    # ── LLM (Phase 2) ──
    llm_provider: str = "openai"
    """Which LLM API to use for NLU: 'openai' or 'anthropic'."""

    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # ── Appium (Phase 3+) ──
    appium_host: str = "http://localhost:4723"
    """Appium server URL for mobile automation."""

    # ── Notifications ──
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    def get_db_path(self) -> Path:
        """Return the database path as a resolved Path object, creating parent dirs."""
        path = Path(self.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_log_dir(self) -> Path:
        """Return the log directory as a resolved Path object, creating it if needed."""
        path = Path(self.log_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_uber_data_dir(self) -> Path:
        """Return the Uber session directory, creating it if needed."""
        path = Path(self.uber_user_data_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


# Singleton instance — import this everywhere
settings = Settings()

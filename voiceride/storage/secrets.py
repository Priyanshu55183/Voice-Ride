"""
Secure credential storage using the OS keyring.

Uses Windows Credential Manager (via the `keyring` library) to store
API keys, session tokens, and other secrets — never in plaintext files.

Usage:
    from voiceride.storage.secrets import SecretStore
    store = SecretStore()
    store.set("openai_api_key", "sk-...")
    key = store.get("openai_api_key")
"""

import keyring
import structlog

log = structlog.get_logger()

SERVICE_NAME = "voiceride"


class SecretStore:
    """Wrapper around OS keyring for secure credential storage."""

    def __init__(self, service_name: str = SERVICE_NAME):
        self.service_name = service_name

    def get(self, key: str) -> str | None:
        """Retrieve a secret. Returns None if not found."""
        value = keyring.get_password(self.service_name, key)
        if value is None:
            log.warning("secret_not_found", key=key)
        return value

    def set(self, key: str, value: str) -> None:
        """Store a secret securely."""
        keyring.set_password(self.service_name, key, value)
        log.info("secret_stored", key=key)

    def delete(self, key: str) -> None:
        """Delete a stored secret."""
        try:
            keyring.delete_password(self.service_name, key)
            log.info("secret_deleted", key=key)
        except keyring.errors.PasswordDeleteError:
            log.warning("secret_delete_failed", key=key, reason="not found")

    def has(self, key: str) -> bool:
        """Check if a secret exists."""
        return self.get(key) is not None

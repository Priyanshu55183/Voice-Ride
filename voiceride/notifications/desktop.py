"""
Desktop notification sender — Windows toast notifications via plyer.

Used as a fallback when TTS isn't audible (e.g., you're in another room).
Sends critical alerts like cancel failures and session expiry warnings.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()


def send_desktop_notification(
    title: str,
    message: str,
    timeout: int = 10,
    app_name: str = "VoiceRide",
) -> bool:
    """
    Send a Windows desktop toast notification.

    Args:
        title: Notification title (e.g., "Driver Found!")
        message: Notification body text
        timeout: How long the notification stays visible (seconds)
        app_name: App name shown in the notification

    Returns:
        True if the notification was sent successfully.
    """
    try:
        from plyer import notification

        notification.notify(
            title=title,
            message=message,
            timeout=timeout,
            app_name=app_name,
        )
        log.info("desktop_notification_sent", title=title)
        return True

    except ImportError:
        log.warning("plyer_not_installed", message="Desktop notifications unavailable")
        return False
    except Exception as e:
        log.error("desktop_notification_error", error=str(e))
        return False


def notify_driver_found(platform: str, driver_name: str | None, eta: int | None) -> bool:
    """Convenience: notify that a driver was found."""
    eta_str = f", ETA {eta // 60}m" if eta else ""
    driver_str = f" ({driver_name})" if driver_name else ""
    return send_desktop_notification(
        title=f"🚗 Driver Found on {platform.title()}!",
        message=f"Driver{driver_str} is on the way{eta_str}. Other platforms cancelled.",
    )


def notify_cancel_failed(platform: str, reason: str | None) -> bool:
    """Convenience: URGENT alert that a cancel failed."""
    return send_desktop_notification(
        title=f"⚠️ CANCEL FAILED — {platform.title()}",
        message=f"Could not cancel ride on {platform.title()}. Please cancel manually! Reason: {reason or 'unknown'}",
        timeout=30,  # Keep visible longer for urgent alerts
    )


def notify_no_drivers() -> bool:
    """Convenience: no drivers found on any platform."""
    return send_desktop_notification(
        title="❌ No Drivers Found",
        message="No drivers available on any platform. Try again later.",
    )


def notify_session_expired(platform: str) -> bool:
    """Convenience: session expired on a platform."""
    return send_desktop_notification(
        title=f"🔑 Session Expired — {platform.title()}",
        message=f"{platform.title()} session expired. Please re-login.",
        timeout=20,
    )

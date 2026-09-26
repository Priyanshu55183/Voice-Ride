"""
Text-to-Speech engine using pyttsx3 (offline, no API required).

Provides spoken confirmations at key moments:
  - "Booking ride from X to Y"
  - "Driver found on Uber. ETA 3 minutes."
  - "No drivers found. Try again later."
  - "Cancel failed on Ola. Please cancel manually."

pyttsx3 uses the OS speech engine (SAPI5 on Windows) and runs synchronously.
This is intentional — TTS announcements happen after key events, not during polling.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()

# Module-level engine (lazy-initialized to avoid import-time side effects)
_engine = None


def _get_engine():
    """Lazy-initialize the pyttsx3 engine."""
    global _engine
    if _engine is None:
        try:
            import pyttsx3
            _engine = pyttsx3.init()
        except ImportError:
            log.warning(
                "pyttsx3_not_installed",
                message="TTS unavailable. Run: pip install voiceride[voice]",
            )
            return None
        except Exception as e:
            log.error("tts_init_failed", error=str(e))
            return None
    return _engine


def configure_voice(rate: int = 175, volume: float = 0.9) -> None:
    """
    Configure TTS voice properties.

    Args:
        rate: Speech rate in words per minute (default 175 — natural pace).
        volume: Volume level 0.0 to 1.0.
    """
    engine = _get_engine()
    if engine is None:
        return

    engine.setProperty("rate", rate)
    engine.setProperty("volume", volume)

    # Try to select a female voice if available (more pleasant for notifications)
    voices = engine.getProperty("voices")
    if voices and len(voices) > 1:
        # On Windows SAPI5, index 1 is typically a female voice
        engine.setProperty("voice", voices[1].id)

    log.info("tts_configured", rate=rate, volume=volume)


def speak(text: str) -> bool:
    """
    Speak the given text aloud using the system TTS engine.

    Args:
        text: The text to speak.

    Returns:
        True if speech was successful, False otherwise.
    """
    engine = _get_engine()
    if engine is None:
        log.warning("tts_unavailable", text=text)
        return False

    try:
        log.info("tts_speaking", text=text)
        engine.say(text)
        engine.runAndWait()
        return True
    except Exception as e:
        log.error("tts_speak_failed", error=str(e), text=text)
        return False


# ─── Convenience Functions ────────────────────────────────────────────────────


def speak_booking_start(pickup: str, drop: str, ride_type: str | None = None) -> bool:
    """Announce that a booking is starting."""
    ride = f" {ride_type}" if ride_type else ""
    return speak(f"Booking{ride} ride from {pickup} to {drop}.")


def speak_listening() -> bool:
    """Announce that we're ready to listen."""
    return speak("I'm listening. Where would you like to go?")


def speak_processing() -> bool:
    """Announce that we're processing the voice command."""
    return speak("Got it. Processing your request.")


def speak_driver_found(
    platform: str,
    driver_name: str | None = None,
    eta_seconds: int | None = None,
) -> bool:
    """Announce that a driver was found."""
    parts = [f"Driver found on {platform}."]
    if driver_name:
        parts.append(f"Your driver is {driver_name}.")
    if eta_seconds:
        minutes = eta_seconds // 60
        if minutes > 0:
            parts.append(f"ETA {minutes} minute{'s' if minutes != 1 else ''}.")
        else:
            parts.append("Arriving very soon.")
    return speak(" ".join(parts))


def speak_no_drivers() -> bool:
    """Announce that no drivers were found."""
    return speak("No drivers found on any platform. Please try again in a few minutes.")


def speak_cancel_failed(platform: str) -> bool:
    """Announce that cancellation failed — needs manual action."""
    return speak(
        f"Warning. Could not cancel ride on {platform}. "
        f"Please open the {platform} app and cancel manually."
    )


def speak_error(message: str) -> bool:
    """Announce a general error."""
    return speak(f"An error occurred. {message}")


def speak_not_understood() -> bool:
    """Announce that the voice command wasn't understood as a booking request."""
    return speak(
        "I didn't catch a booking request. "
        "Please say something like: book a cab from Mekhri Circle to BMSIT College."
    )


def speak_goodbye() -> bool:
    """Announce exit from voice mode."""
    return speak("Goodbye. Voice Ride signing off.")

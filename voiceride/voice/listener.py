"""
Microphone listener — captures speech from the mic with automatic silence detection.

Uses the SpeechRecognition library which handles all the complexity internally:
  - Opens the microphone
  - Waits for you to start speaking
  - Automatically stops when you go silent
  - Returns the audio data ready to send to an API

No manual VAD, no frame processing, no numpy — just `recognizer.listen()`.
"""

from __future__ import annotations

import io
import wave

import structlog

log = structlog.get_logger()


class VoiceListener:
    """
    Captures speech from the microphone.

    Usage:
        listener = VoiceListener()
        wav_bytes = listener.listen_once()  # Blocks until speech is captured
        # wav_bytes is a WAV file in memory, ready to send to OpenAI Whisper API
    """

    def __init__(self, pause_threshold: float = 1.5, energy_threshold: int | None = None):
        """
        Args:
            pause_threshold: Seconds of silence after speech before stopping.
            energy_threshold: Mic sensitivity. None = auto-adjust (recommended).
        """
        self._pause_threshold = pause_threshold
        self._energy_threshold = energy_threshold

    def listen_once(
        self,
        on_speech_start=None,
        on_speech_end=None,
    ) -> bytes | None:
        """
        Listen for a single utterance from the microphone.

        Blocks until speech is detected and then silence follows.

        Returns:
            WAV file bytes (ready to send to Whisper API), or None if interrupted.
        """
        try:
            import speech_recognition as sr
        except ImportError:
            raise ImportError(
                "SpeechRecognition not installed. Run: pip install SpeechRecognition PyAudio"
            )

        recognizer = sr.Recognizer()
        recognizer.pause_threshold = self._pause_threshold

        if self._energy_threshold is not None:
            recognizer.energy_threshold = self._energy_threshold
            recognizer.dynamic_energy_threshold = False

        try:
            with sr.Microphone() as source:
                # Auto-adjust for ambient noise (1 second)
                log.info("listener_adjusting_for_noise")
                recognizer.adjust_for_ambient_noise(source, duration=1)

                log.info("listener_waiting_for_speech")
                if on_speech_start:
                    on_speech_start()

                # This blocks until speech is detected and silence follows
                audio = recognizer.listen(source)

                if on_speech_end:
                    on_speech_end()

                log.info("listener_audio_captured")

                # Convert to WAV bytes (what OpenAI Whisper API expects)
                wav_bytes = audio.get_wav_data()
                return wav_bytes

        except KeyboardInterrupt:
            log.info("listener_interrupted")
            return None
        except Exception as e:
            log.error("listener_error", error=str(e))
            return None

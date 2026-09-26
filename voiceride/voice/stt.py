"""
Speech-to-Text using OpenAI's Whisper API (cloud).

Instead of downloading and running a huge Whisper model locally,
we just send the audio to OpenAI's API — same Whisper model, zero setup.
You already need an OpenAI key for NLU, so this adds no extra credentials.

Usage:
    from voiceride.voice.stt import transcribe_audio
    transcript = await transcribe_audio(wav_bytes)
"""

from __future__ import annotations

import io

import structlog

from voiceride.config import settings

log = structlog.get_logger()


async def transcribe_audio(wav_bytes: bytes) -> str:
    """
    Transcribe audio using OpenAI's Whisper API.

    Args:
        wav_bytes: Audio data as WAV file bytes (from VoiceListener).

    Returns:
        Transcribed text string.
    """
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise ImportError("OpenAI not installed. Run: pip install openai")

    api_key = settings.openai_api_key
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY not set. Add it to your .env file."
        )

    client = AsyncOpenAI(api_key=api_key)

    # Wrap bytes in a file-like object with a name (OpenAI needs the filename)
    audio_file = io.BytesIO(wav_bytes)
    audio_file.name = "recording.wav"

    log.info("whisper_api_transcribing")

    response = await client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        language=settings.whisper_language,  # None = auto-detect
    )

    transcript = response.text.strip()
    log.info("whisper_api_done", transcript=transcript)

    return transcript

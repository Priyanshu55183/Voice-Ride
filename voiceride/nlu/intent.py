"""
LLM-based intent extraction — converts speech transcripts into structured RideRequests.

Supports both OpenAI and Anthropic as LLM backends. The provider is selected via
the LLM_PROVIDER config setting.

The flow:
  1. Receive raw transcript from Whisper
  2. Send it to the LLM with a carefully crafted system prompt
  3. Parse the JSON response into a RideRequest (or reject if not a booking)
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import structlog

from voiceride.config import settings
from voiceride.nlu.prompts import build_messages

log = structlog.get_logger()


@dataclass
class IntentResult:
    """Result of intent extraction from a speech transcript."""

    is_booking: bool
    """Whether the transcript was a valid cab booking request."""

    pickup: str | None = None
    drop: str | None = None
    ride_type: str | None = None

    reason: str | None = None
    """If not a booking: why (e.g., 'user asked about weather')."""

    raw_response: str = ""
    """The raw LLM response for debugging."""


class IntentExtractor:
    """
    Extracts structured booking intent from natural language transcripts.

    Uses OpenAI or Anthropic depending on the LLM_PROVIDER setting.
    """

    def __init__(self):
        self._provider = settings.llm_provider.lower()
        self._client = None

    async def extract(self, transcript: str) -> IntentResult:
        """
        Extract booking intent from a speech transcript.

        Args:
            transcript: Raw text from Whisper STT.

        Returns:
            IntentResult with parsed fields or rejection reason.
        """
        if not transcript or not transcript.strip():
            return IntentResult(is_booking=False, reason="empty transcript")

        log.info("nlu_extracting_intent", transcript=transcript, provider=self._provider)

        try:
            if self._provider == "openai":
                raw = await self._call_openai(transcript)
            elif self._provider == "anthropic":
                raw = await self._call_anthropic(transcript)
            else:
                raise ValueError(f"Unknown LLM provider: {self._provider}")

            return self._parse_response(raw)

        except Exception as e:
            log.error("nlu_extraction_failed", error=str(e), exc_info=True)
            return IntentResult(
                is_booking=False,
                reason=f"LLM call failed: {e}",
            )

    async def _call_openai(self, transcript: str) -> str:
        """Call OpenAI's chat completion API."""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "OpenAI package not installed. Run: pip install voiceride[nlu]"
            )

        api_key = settings.openai_api_key
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY not set. Add it to your .env file or set the environment variable."
            )

        client = AsyncOpenAI(api_key=api_key)
        messages = build_messages(transcript)

        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=0.0,
            max_tokens=256,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or ""
        log.debug("openai_raw_response", content=content)
        return content

    async def _call_anthropic(self, transcript: str) -> str:
        """Call Anthropic's messages API."""
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            raise ImportError(
                "Anthropic package not installed. Run: pip install voiceride[nlu]"
            )

        api_key = settings.anthropic_api_key
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not set. Add it to your .env file or set the environment variable."
            )

        client = AsyncAnthropic(api_key=api_key)
        messages = build_messages(transcript)

        # Anthropic uses system as a separate param, not in messages list
        system_msg = messages[0]["content"]
        user_msgs = [{"role": m["role"], "content": m["content"]} for m in messages[1:]]

        response = await client.messages.create(
            model=settings.llm_model_anthropic,
            system=system_msg,
            messages=user_msgs,
            temperature=0.0,
            max_tokens=256,
        )

        content = response.content[0].text
        log.debug("anthropic_raw_response", content=content)
        return content

    def _parse_response(self, raw: str) -> IntentResult:
        """Parse the LLM's JSON response into an IntentResult."""
        try:
            # Strip markdown fences if the LLM wraps its response
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                # Remove first and last lines (the ``` markers)
                cleaned = "\n".join(lines[1:-1]).strip()

            data = json.loads(cleaned)

            is_booking = data.get("is_booking", False)

            if not is_booking:
                return IntentResult(
                    is_booking=False,
                    reason=data.get("reason", "not a booking request"),
                    raw_response=raw,
                )

            pickup = data.get("pickup")
            drop = data.get("drop")

            if not drop:
                return IntentResult(
                    is_booking=False,
                    reason="no destination found in transcript",
                    raw_response=raw,
                )

            ride_type = data.get("ride_type")
            # Normalize ride_type
            if ride_type and ride_type.lower() in ("auto", "mini", "sedan", "suv", "bike"):
                ride_type = ride_type.lower()
            else:
                ride_type = None

            log.info(
                "nlu_intent_extracted",
                pickup=pickup,
                drop=drop,
                ride_type=ride_type,
            )

            return IntentResult(
                is_booking=True,
                pickup=pickup,
                drop=drop,
                ride_type=ride_type,
                raw_response=raw,
            )

        except json.JSONDecodeError as e:
            log.error("nlu_json_parse_failed", raw=raw, error=str(e))
            return IntentResult(
                is_booking=False,
                reason=f"LLM returned invalid JSON: {e}",
                raw_response=raw,
            )

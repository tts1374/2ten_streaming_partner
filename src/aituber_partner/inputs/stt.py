"""STT transcript input source skeleton for microphone adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from pydantic import BaseModel, Field

from aituber_partner.models import InputEvent


class TranscriptionResult(BaseModel):
    """One completed speech-to-text segment."""

    text: str
    model_name: str
    language: str = "ja"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    duration_seconds: float | None = Field(default=None, ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TranscriptProvider(Protocol):
    def transcripts(self) -> AsyncIterator[TranscriptionResult]:
        """Yield completed microphone transcription segments."""


class STTInputSource:
    """Convert completed STT transcripts into voice InputEvent objects."""

    def __init__(
        self,
        provider: TranscriptProvider,
        *,
        author: str = "microphone",
        min_confidence: float = 0.0,
        max_events: int | None = None,
    ) -> None:
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0.0 and 1.0.")
        if max_events is not None and max_events <= 0:
            raise ValueError("max_events must be greater than 0.")
        self._provider = provider
        self._author = author
        self._min_confidence = min_confidence
        self._max_events = max_events

    async def events(self) -> AsyncIterator[InputEvent]:
        yielded = 0
        async for transcript in self._provider.transcripts():
            text = transcript.text.strip()
            if not text:
                continue
            if (
                transcript.confidence is not None
                and transcript.confidence < self._min_confidence
            ):
                continue

            yield InputEvent(
                source="voice",
                text=text,
                author=self._author,
                metadata={
                    **transcript.metadata,
                    "stt_model": transcript.model_name,
                    "stt_language": transcript.language,
                    "stt_confidence": transcript.confidence,
                    "stt_duration_seconds": transcript.duration_seconds,
                },
            )
            yielded += 1
            if self._max_events is not None and yielded >= self._max_events:
                return

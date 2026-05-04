"""Fake input source for local closed-loop development."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable

from aituber_partner.models import InputEvent


class FakeInputSource:
    def __init__(self, events: Iterable[InputEvent], delay_seconds: float = 0.0) -> None:
        self._events = list(events)
        self._delay_seconds = delay_seconds

    @classmethod
    def from_texts(cls, texts: Iterable[str], delay_seconds: float = 0.0) -> "FakeInputSource":
        return cls(
            (InputEvent(source="youtube_chat", text=text, author="fake-viewer") for text in texts),
            delay_seconds=delay_seconds,
        )

    async def events(self) -> AsyncIterator[InputEvent]:
        for event in self._events:
            if self._delay_seconds > 0:
                await asyncio.sleep(self._delay_seconds)
            yield event

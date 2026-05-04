"""Idle topic input source for inactivity gaps."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from itertools import cycle

from aituber_partner.inputs.base import InputSource
from aituber_partner.models import InputEvent


_END = object()


class IdleTopicInputSource:
    """Yield an idle topic when an upstream input source is quiet for too long."""

    def __init__(
        self,
        source: InputSource,
        *,
        timeout_seconds: float,
        topics: Sequence[str],
        repeat_interval_seconds: float | None = None,
        max_idle_events: int | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0.")
        if repeat_interval_seconds is not None and repeat_interval_seconds <= 0:
            raise ValueError("repeat_interval_seconds must be greater than 0.")
        if not topics:
            raise ValueError("topics must contain at least one idle topic.")
        self._source = source
        self._timeout_seconds = timeout_seconds
        self._repeat_interval_seconds = repeat_interval_seconds or timeout_seconds
        self._topics = cycle(topics)
        self._max_idle_events = max_idle_events

    async def events(self) -> AsyncIterator[InputEvent]:
        queue: asyncio.Queue[InputEvent | object] = asyncio.Queue()
        pump_task = asyncio.create_task(self._pump_source(queue))
        idle_count = 0
        wait_seconds = self._timeout_seconds
        recent_event: InputEvent | None = None

        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=wait_seconds)
                except TimeoutError:
                    if self._max_idle_events is not None and idle_count >= self._max_idle_events:
                        wait_seconds = self._repeat_interval_seconds
                        continue
                    idle_count += 1
                    wait_seconds = self._repeat_interval_seconds
                    yield self._build_idle_event(recent_event)
                    continue

                if item is _END:
                    return

                if isinstance(item, BaseException):
                    raise item

                idle_count = 0
                wait_seconds = self._timeout_seconds
                recent_event = item
                yield item
        finally:
            pump_task.cancel()
            await asyncio.gather(pump_task, return_exceptions=True)

    async def _pump_source(self, queue: asyncio.Queue[InputEvent | object]) -> None:
        try:
            async for event in self._source.events():
                await queue.put(event)
        except Exception as exc:
            await queue.put(exc)
        finally:
            await queue.put(_END)

    def _build_idle_event(self, recent_event: InputEvent | None) -> InputEvent:
        metadata = {
            "reason": "inactivity_timeout",
            "timeout_seconds": self._timeout_seconds,
            "repeat_interval_seconds": self._repeat_interval_seconds,
        }
        if recent_event is not None:
            metadata.update(
                {
                    "recent_input_source": recent_event.source,
                    "recent_input_author": recent_event.author,
                    "recent_input_text": recent_event.text,
                }
            )

        return InputEvent(
            source="idle_topic",
            text=next(self._topics),
            author="idle-topic",
            metadata=metadata,
        )

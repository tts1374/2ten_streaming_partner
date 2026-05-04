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
        max_idle_events: int | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0.")
        if not topics:
            raise ValueError("topics must contain at least one idle topic.")
        self._source = source
        self._timeout_seconds = timeout_seconds
        self._topics = cycle(topics)
        self._max_idle_events = max_idle_events

    async def events(self) -> AsyncIterator[InputEvent]:
        queue: asyncio.Queue[InputEvent | object] = asyncio.Queue()
        pump_task = asyncio.create_task(self._pump_source(queue))
        idle_count = 0

        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=self._timeout_seconds)
                except TimeoutError:
                    if self._max_idle_events is not None and idle_count >= self._max_idle_events:
                        continue
                    idle_count += 1
                    yield self._build_idle_event()
                    continue

                if item is _END:
                    return

                if isinstance(item, BaseException):
                    raise item

                idle_count = 0
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

    def _build_idle_event(self) -> InputEvent:
        return InputEvent(
            source="idle_topic",
            text=next(self._topics),
            author="idle-topic",
            metadata={
                "reason": "inactivity_timeout",
                "timeout_seconds": self._timeout_seconds,
            },
        )

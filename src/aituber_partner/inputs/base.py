"""Common input source protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from aituber_partner.models import InputEvent


class InputSource(Protocol):
    def events(self) -> AsyncIterator[InputEvent]:
        """Yield normalized input events."""


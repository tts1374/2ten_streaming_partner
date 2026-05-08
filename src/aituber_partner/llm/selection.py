"""LLM-backed YouTube chat candidate selection."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from aituber_partner.llm.prompts import SELECTION_SYSTEM_PROMPT, build_chat_selection_prompt
from aituber_partner.llm.router import LLMRouter
from aituber_partner.models import InputEvent


class ChatSelectionDecision(BaseModel):
    """Parsed decision for one poll's chat candidates."""

    selected_index: int | None = Field(default=None, ge=1)
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)


def parse_chat_selection_decision(text: str) -> ChatSelectionDecision | None:
    """Parse selection JSON, failing closed on malformed or invalid output."""

    try:
        payload = json.loads(_strip_json_fence(text))
        return ChatSelectionDecision.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
        return None


class LLMChatSelector:
    """Select the single best YouTube chat candidate using the classifier model."""

    def __init__(self, router: LLMRouter, *, streamer_name: str = "つてん") -> None:
        self._router = router
        self._streamer_name = streamer_name

    async def select(self, events: list[InputEvent]) -> list[InputEvent]:
        if len(events) <= 1:
            return events

        response = await self._router.generate(
            purpose="selection",
            system=SELECTION_SYSTEM_PROMPT,
            prompt=build_chat_selection_prompt(events, streamer_name=self._streamer_name),
        )
        decision = parse_chat_selection_decision(response.text)
        if decision is None or decision.selected_index is None:
            return []

        selected_offset = decision.selected_index - 1
        if selected_offset < 0 or selected_offset >= len(events):
            return []

        selected = events[selected_offset]
        return [
            selected.model_copy(
                update={
                    "metadata": {
                        **selected.metadata,
                        "llm_selection_model": response.model,
                        "llm_selection_reason": decision.reason,
                        "llm_selection_confidence": decision.confidence,
                        "llm_selection_candidate_count": len(events),
                    }
                }
            )
        ]


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped

"""Safety parsing helpers."""

from __future__ import annotations

import json

from pydantic import ValidationError

from aituber_partner.models import SafetyDecision


def parse_safety_decision(text: str) -> SafetyDecision:
    """Parse LLM safety JSON, failing closed on malformed or invalid output."""

    try:
        payload = json.loads(_strip_json_fence(text))
        return SafetyDecision.model_validate(payload)
    except (json.JSONDecodeError, TypeError, ValidationError):
        return SafetyDecision(
            status="block",
            reasons=["malformed_safety_json"],
            confidence=0.0,
        )


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


"""Local output guard for low-latency final reply checks."""

from __future__ import annotations

from aituber_partner.llm.text import strip_thinking_text
from aituber_partner.models import SafetyDecision

_UNSAFE_OUTPUT_MARKERS = (
    "住所",
    "電話番号",
    "殺す",
    "死ね",
    "差別",
    "爆弾",
    "違法",
)


def classify_output_locally(reply_text: str) -> SafetyDecision:
    """Run a small deterministic final guard without an extra LLM call."""

    cleaned = strip_thinking_text(reply_text)
    if not cleaned:
        return SafetyDecision(
            status="block",
            reasons=["empty_after_thinking_strip"],
            confidence=1.0,
        )
    if cleaned != reply_text.strip():
        return SafetyDecision(
            status="block",
            reasons=["thinking_text_detected"],
            confidence=1.0,
        )
    if any(marker in cleaned for marker in _UNSAFE_OUTPUT_MARKERS):
        return SafetyDecision(
            status="block",
            reasons=["unsafe_marker_detected"],
            confidence=0.8,
        )
    return SafetyDecision(status="allow", reasons=["local_output_guard_allow"], confidence=0.7)

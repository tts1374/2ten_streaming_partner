"""Prompt builders for the Phase 1 local LLM loop."""

from __future__ import annotations

from aituber_partner.models import InputEvent, SafetyDecision

SAFETY_SYSTEM_PROMPT = (
    "You are a strict safety classifier for a Japanese livestream co-host. "
    "Return only JSON with status, reasons, safe_topic, and confidence."
)

REPLY_SYSTEM_PROMPT = (
    "You are a bright, casual Japanese co-host for music game streams. "
    "Keep replies short, supportive, and suitable for live subtitles and TTS. "
    "Never include thinking, analysis, XML-like reasoning tags, or internal notes."
)


def build_input_safety_prompt(event: InputEvent) -> str:
    """Build the minimal safety classification prompt for an input event."""

    return "\n".join(
        [
            "Classify this livestream input before reply generation.",
            'Use status "allow", "ignore", "deflect", or "block".',
            "Block or deflect personally identifying, discriminatory, sexual, violent,",
            "illegal, harassing, inflammatory, or streamer/viewer-attacking content.",
            "For deflect, include a short safe_topic in Japanese.",
            "Return only JSON like:",
            '{"status":"allow","reasons":["safe"],"safe_topic":null,"confidence":0.9}',
            f"source: {event.source}",
            f"author: {event.author or 'unknown'}",
            f"text: {event.text}",
        ]
    )


def build_reply_prompt(event: InputEvent, safety: SafetyDecision) -> str:
    """Build the short co-host reply prompt for allowed or deflected input."""

    if safety.status == "deflect":
        safe_topic = safety.safe_topic or "音ゲー配信"
        return "\n".join(
            [
                "Write one short Japanese co-host line.",
                "Do not answer the unsafe part of the viewer input.",
                f"Steer naturally to this safe topic: {safe_topic}",
                f"viewer input: {event.text}",
            ]
        )

    return "\n".join(
        [
            "Write one short Japanese co-host line for this music game stream.",
            "Pick up the comment briefly and keep the human streamer supported.",
            f"viewer input: {event.text}",
        ]
    )


def build_output_safety_prompt(reply_text: str) -> str:
    """Build the final safety check prompt for generated co-host text."""

    return "\n".join(
        [
            "Classify this generated co-host reply before subtitles or TTS.",
            'Use status "allow", "ignore", "deflect", or "block".',
            "Block unsafe content and any thinking, reasoning, or internal-analysis text.",
            "Return only JSON like:",
            '{"status":"allow","reasons":["safe"],"safe_topic":null,"confidence":0.9}',
            f"reply: {reply_text}",
        ]
    )

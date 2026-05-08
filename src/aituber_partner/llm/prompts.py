"""Prompt builders for the Phase 1 local LLM loop."""

from __future__ import annotations

from aituber_partner.models import InputEvent, SafetyDecision

SAFETY_SYSTEM_PROMPT = (
    "You are a strict safety classifier for a Japanese livestream co-host. "
    "Return only JSON with status, reasons, safe_topic, and confidence."
)

REPLY_SYSTEM_PROMPT = (
    "You are a bright, casual Japanese co-host for music game streams. "
    "The main conversation partner is the human streamer. "
    "Reply as a co-host beside the human streamer, not as a generic chatbot or a chat commenter. "
    "Keep replies short, concrete, supportive, and suitable for live subtitles and TTS. "
    "Do not invent stream state, score, chart details, or player intent that is not in the input. "
    "When the comment is vague, acknowledge it lightly or ask a compact follow-up. "
    "Never include thinking, analysis, XML-like reasoning tags, or internal notes."
)

SELECTION_SYSTEM_PROMPT = (
    "You select one useful Japanese YouTube Live Chat comment for a music-game co-host. "
    "Return only JSON with selected_index, reason, and confidence."
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


def build_reply_prompt(
    event: InputEvent,
    safety: SafetyDecision,
    *,
    streamer_name: str = "つてん",
) -> str:
    """Build the short co-host reply prompt for allowed or deflected input."""

    if safety.status == "deflect":
        safe_topic = safety.safe_topic or "音ゲー配信"
        return "\n".join(
            [
                "Write one short Japanese co-host line.",
                f"Address the human streamer as {streamer_name}.",
                "Do not answer the unsafe part of the viewer input.",
                f"Steer naturally to this safe topic: {safe_topic}",
                "Keep it to 1 sentence and under 45 Japanese characters when possible.",
                f"viewer input: {event.text}",
            ]
        )

    return "\n".join(
        _reply_goal_lines(event)
        + [
            "Keep it to 1 sentence and under 45 Japanese characters when possible.",
            "Avoid stock phrases like 頑張って, いい流れ, 流石 unless the input specifically supports them.",
            f"streamer name: {streamer_name}",
            f"input source: {event.source}",
            f"input author: {event.author or 'unknown'}",
            f"input text: {event.text}",
        ]
    )


def _reply_goal_lines(event: InputEvent) -> list[str]:
    if event.source == "voice":
        return [
            "Write one short Japanese line addressed directly to the human streamer.",
            "Treat the input as the streamer's speech and continue that conversation naturally.",
            "Answer the streamer directly instead of summarizing for viewers.",
        ]

    if event.source == "youtube_chat":
        return [
            "Write one short Japanese line addressed to the human streamer.",
            "Treat the input as a viewer comment that you are relaying to the streamer.",
            "Briefly mention the comment's point, then expand only if it gives the streamer a useful topic.",
            "Do not answer as if you are replying directly to the viewer.",
            "If the input is a status check, answer the check directly.",
            "If the input mentions sound, visibility, latency, or setup, respond about that setup point.",
            "Use the viewer input as the main anchor; do not drift to a generic cheer.",
        ]

    if event.source == "idle_topic":
        lines = [
            "Write one short Japanese question or topic prompt addressed to the human streamer.",
            "Use this as an idle gap filler, not a standalone monologue.",
            "If recent input metadata is present, connect the topic to that recent input.",
        ]
        recent_source = event.metadata.get("recent_input_source")
        recent_author = event.metadata.get("recent_input_author")
        recent_text = event.metadata.get("recent_input_text")
        if recent_text:
            lines.extend(
                [
                    f"recent input source: {recent_source or 'unknown'}",
                    f"recent input author: {recent_author or 'unknown'}",
                    f"recent input text: {recent_text}",
                ]
            )
        return lines

    return [
        "Write one short Japanese co-host line for this music game stream.",
        "Use the input as the main anchor; do not drift to a generic cheer.",
    ]


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


def build_chat_selection_prompt(
    events: list[InputEvent],
    *,
    streamer_name: str = "つてん",
) -> str:
    """Build a compact JSON-only selection prompt for filtered chat candidates."""

    candidate_lines = []
    for index, event in enumerate(events, start=1):
        candidate_lines.append(
            "\n".join(
                [
                    f"{index}. author: {event.author or 'unknown'}",
                    f"   owner: {bool(event.metadata.get('is_chat_owner'))}",
                    f"   moderator: {bool(event.metadata.get('is_chat_moderator'))}",
                    f"   verified: {bool(event.metadata.get('is_verified'))}",
                    f"   lightweight_score: {event.metadata.get('selection_score', 0)}",
                    f"   text: {event.text}",
                ]
            )
        )

    return "\n".join(
        [
            f"Choose the single comment most worth passing to the streamer {streamer_name}.",
            "Prefer safe, concrete comments that help the stream move forward.",
            "Good picks include questions, setup/status checks, play-related observations,",
            "and comments that are easy for a co-host to relay briefly.",
            "Do not pick harassment, sexual/violent/illegal content, personal information,",
            "bait, viewer attacks, streamer attacks, spam, or comments with no useful hook.",
            "If no candidate is worth using, set selected_index to null.",
            "Return only JSON like:",
            '{"selected_index":2,"reason":"音量確認で配信運用に役立つ","confidence":0.82}',
            "Candidates:",
            *candidate_lines,
        ]
    )

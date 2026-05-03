"""Local closed-loop orchestration for the first PoC."""

from __future__ import annotations

from collections.abc import AsyncIterator

from aituber_partner.config import AppConfig
from aituber_partner.inputs.base import InputSource
from aituber_partner.models import GeneratedReply, OverlayState, ProcessedEvent, SafetyDecision


class LocalClosedLoopOrchestrator:
    """Process normalized input events with deterministic placeholder decisions."""

    def __init__(self, config: AppConfig, input_source: InputSource) -> None:
        self._config = config
        self._input_source = input_source
        self.overlay_state = OverlayState()

    async def run_once_per_event(self) -> AsyncIterator[ProcessedEvent]:
        async for event in self._input_source.events():
            self.overlay_state = OverlayState(status="thinking", text="")
            safety = self._classify_safety(event.text)

            if safety.status in {"ignore", "block"}:
                self.overlay_state = OverlayState(status="idle", text="")
                yield ProcessedEvent(
                    input_event=event,
                    safety=safety,
                    reply=None,
                    overlay=self.overlay_state,
                )
                continue

            reply_text = self._build_placeholder_reply(event.text, safety)
            reply = GeneratedReply(
                text=reply_text,
                generation_model=self._config.models.reply,
                latency_ms=0,
            )
            self.overlay_state = OverlayState(status="speaking", text=reply.text)
            yield ProcessedEvent(
                input_event=event,
                safety=safety,
                reply=reply,
                overlay=self.overlay_state,
            )

    def _classify_safety(self, text: str) -> SafetyDecision:
        unsafe_markers = ("住所", "電話番号", "殺す", "死ね")
        if any(marker in text for marker in unsafe_markers):
            return SafetyDecision(
                status="block",
                reasons=["unsafe_marker_detected"],
                confidence=0.8,
            )
        return SafetyDecision(status="allow", reasons=["placeholder_allow"], confidence=0.5)

    @staticmethod
    def _build_placeholder_reply(text: str, safety: SafetyDecision) -> str:
        if safety.status == "deflect" and safety.safe_topic:
            return f"{safety.safe_topic}の話に戻そっか。"
        trimmed = text.strip()
        if len(trimmed) > 42:
            trimmed = f"{trimmed[:41]}..."
        return f"コメントありがとう！「{trimmed}」いい視点だね。"


"""Local closed-loop orchestration for the first PoC."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from aituber_partner.config import AppConfig
from aituber_partner.inputs.base import InputSource
from aituber_partner.llm.prompts import (
    REPLY_SYSTEM_PROMPT,
    SAFETY_SYSTEM_PROMPT,
    build_input_safety_prompt,
    build_output_safety_prompt,
    build_reply_prompt,
)
from aituber_partner.llm.output_guard import classify_output_locally
from aituber_partner.llm.router import LLMRouter
from aituber_partner.llm.safety import parse_safety_decision
from aituber_partner.models import (
    GeneratedReply,
    InputEvent,
    OverlayState,
    ProcessedEvent,
    SafetyDecision,
)


class ProcessedEventRecorder(Protocol):
    def record_processed_event(self, processed: ProcessedEvent) -> None:
        """Persist a completed event processing result."""


class LocalClosedLoopOrchestrator:
    """Process normalized input events through the local closed loop."""

    def __init__(
        self,
        config: AppConfig,
        input_source: InputSource,
        llm_router: LLMRouter | None = None,
        recorder: ProcessedEventRecorder | None = None,
        use_local_output_guard: bool = False,
    ) -> None:
        self._config = config
        self._input_source = input_source
        self._llm_router = llm_router
        self._recorder = recorder
        self._use_local_output_guard = use_local_output_guard
        self.overlay_state = OverlayState()

    async def run_once_per_event(self) -> AsyncIterator[ProcessedEvent]:
        async for event in self._input_source.events():
            self.overlay_state = OverlayState(status="thinking", text="")
            safety = await self._classify_safety(event)

            if safety.status in {"ignore", "block"}:
                self.overlay_state = OverlayState(status="idle", text="")
                processed = ProcessedEvent(
                    input_event=event,
                    safety=safety,
                    reply=None,
                    overlay=self.overlay_state,
                )
                self._record_processed_event(processed)
                yield processed
                continue

            reply = await self._generate_reply(event, safety)
            output_safety = await self._classify_output_safety(reply.text)
            if output_safety.status in {"ignore", "block"}:
                self.overlay_state = OverlayState(status="idle", text="")
                processed = ProcessedEvent(
                    input_event=event,
                    safety=safety,
                    output_safety=output_safety,
                    reply=None,
                    overlay=self.overlay_state,
                )
                self._record_processed_event(processed)
                yield processed
                continue

            if output_safety.status == "deflect":
                reply = GeneratedReply(
                    text=self._build_safe_deflection(output_safety),
                    generation_model=reply.generation_model,
                    latency_ms=reply.latency_ms,
                )

            self.overlay_state = OverlayState(status="speaking", text=reply.text)
            processed = ProcessedEvent(
                input_event=event,
                safety=safety,
                output_safety=output_safety,
                reply=reply,
                overlay=self.overlay_state,
            )
            self._record_processed_event(processed)
            yield processed

    async def _classify_safety(self, event: InputEvent) -> SafetyDecision:
        if self._llm_router is None:
            return self._classify_placeholder_safety(event.text)

        response = await self._llm_router.generate(
            purpose="safety",
            system=SAFETY_SYSTEM_PROMPT,
            prompt=build_input_safety_prompt(event),
        )
        return parse_safety_decision(response.text)

    async def _generate_reply(self, event: InputEvent, safety: SafetyDecision) -> GeneratedReply:
        if self._llm_router is None:
            reply_text = self._build_placeholder_reply(event.text, safety)
            reply = GeneratedReply(
                text=reply_text,
                generation_model=self._config.models.reply,
                latency_ms=0,
            )
            return reply

        response = await self._llm_router.generate(
            purpose="reply",
            system=REPLY_SYSTEM_PROMPT,
            prompt=build_reply_prompt(event, safety),
        )
        return GeneratedReply(
            text=response.text,
            generation_model=response.model,
            latency_ms=response.latency_ms,
        )

    async def _classify_output_safety(self, reply_text: str) -> SafetyDecision:
        if self._use_local_output_guard:
            return classify_output_locally(reply_text)

        if self._llm_router is None:
            return SafetyDecision(status="allow", reasons=["placeholder_allow"], confidence=0.5)

        response = await self._llm_router.generate(
            purpose="safety",
            system=SAFETY_SYSTEM_PROMPT,
            prompt=build_output_safety_prompt(reply_text),
        )
        return parse_safety_decision(response.text)

    def _classify_placeholder_safety(self, text: str) -> SafetyDecision:
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

    @staticmethod
    def _build_safe_deflection(safety: SafetyDecision) -> str:
        safe_topic = safety.safe_topic or "音ゲー配信"
        return f"{safe_topic}の話に戻そっか。"

    def _record_processed_event(self, processed: ProcessedEvent) -> None:
        if self._recorder is not None:
            self._recorder.record_processed_event(processed)

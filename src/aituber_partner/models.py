"""Shared runtime data models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


InputSourceName = Literal["youtube_chat", "voice", "idle_topic"]
SafetyStatus = Literal["allow", "ignore", "deflect", "block"]
OverlayStatus = Literal["idle", "listening", "thinking", "speaking", "error"]
SpeechJobStatus = Literal["created", "played", "failed"]


class InputEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("input"))
    source: InputSourceName
    text: str
    author: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
    image_ref: str | None = None


class SafetyDecision(BaseModel):
    status: SafetyStatus
    reasons: list[str] = Field(default_factory=list)
    safe_topic: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class GeneratedReply(BaseModel):
    id: str = Field(default_factory=lambda: new_id("reply"))
    text: str
    persona_version: str = "phase1-default"
    memory_refs: list[str] = Field(default_factory=list)
    generation_model: str
    latency_ms: int = Field(ge=0)


class OverlayState(BaseModel):
    status: OverlayStatus = "idle"
    text: str = ""
    speaker_name: str = "2ten"
    show_detail: bool = False
    updated_at: datetime = Field(default_factory=utc_now)
    detail: str | None = None


class SpeechJob(BaseModel):
    id: str = Field(default_factory=lambda: new_id("speech"))
    reply_id: str
    text: str
    voice_id: int
    status: SpeechJobStatus
    audio_path: str | None = None
    error: str | None = None
    latency_ms: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class ProcessedEvent(BaseModel):
    input_event: InputEvent
    safety: SafetyDecision
    output_safety: SafetyDecision | None = None
    reply: GeneratedReply | None
    speech_job: SpeechJob | None = None
    overlay: OverlayState

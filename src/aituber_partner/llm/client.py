"""Thin Ollama client and shared request/response models."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol
from urllib import error, request

from pydantic import BaseModel, Field


class LLMRequest(BaseModel):
    model: str
    prompt: str
    purpose: str
    system: str | None = None
    images: list[str] = Field(default_factory=list)
    think: bool | None = None
    keep_alive: str | None = None
    stream: bool = False


class LLMResponse(BaseModel):
    model: str
    text: str
    latency_ms: int = Field(default=0, ge=0)
    raw: dict[str, Any] = Field(default_factory=dict)


class LLMClient(Protocol):
    async def generate(self, llm_request: LLMRequest) -> LLMResponse:
        """Generate text for a prepared LLM request."""


class LLMCallRecorder(Protocol):
    def record_llm_call(
        self,
        llm_request: LLMRequest,
        *,
        response: LLMResponse | None = None,
        error: str | None = None,
    ) -> None:
        """Persist one model call attempt."""


class RecordingLLMClient:
    """Wrap an LLM client and persist success/failure metadata."""

    def __init__(self, client: LLMClient, recorder: LLMCallRecorder) -> None:
        self._client = client
        self._recorder = recorder

    async def generate(self, llm_request: LLMRequest) -> LLMResponse:
        try:
            response = await self._client.generate(llm_request)
        except Exception as exc:
            self._recorder.record_llm_call(llm_request, error=str(exc))
            raise
        self._recorder.record_llm_call(llm_request, response=response)
        return response


class OllamaClient:
    """Small async wrapper around Ollama's generate endpoint."""

    def __init__(self, base_url: str, timeout_seconds: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def generate(self, llm_request: LLMRequest) -> LLMResponse:
        return await asyncio.to_thread(self._generate_sync, llm_request)

    def _generate_sync(self, llm_request: LLMRequest) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": llm_request.model,
            "prompt": llm_request.prompt,
            "stream": llm_request.stream,
        }
        if llm_request.system is not None:
            payload["system"] = llm_request.system
        if llm_request.images:
            payload["images"] = llm_request.images
        if llm_request.keep_alive is not None:
            payload["keep_alive"] = llm_request.keep_alive
        if llm_request.think is not None:
            payload["think"] = llm_request.think

        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            f"{self._base_url}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            raise ConnectionError(f"Ollama request failed: {exc}") from exc

        return LLMResponse(
            model=str(data.get("model", llm_request.model)),
            text=str(data.get("response", "")),
            latency_ms=_ollama_latency_ms(data),
            raw=data,
        )


def _ollama_latency_ms(data: dict[str, Any]) -> int:
    total_duration = data.get("total_duration")
    if isinstance(total_duration, int):
        return max(0, total_duration // 1_000_000)
    return 0

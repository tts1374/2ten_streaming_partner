"""AivisSpeech API client for local TTS generation."""

from __future__ import annotations

import asyncio
import json
from time import perf_counter
from urllib import error, parse, request

from aituber_partner.config import AivisConfig, StorageConfig
from aituber_partner.models import GeneratedReply, SpeechJob, new_id


class AivisSpeechClient:
    """Small async wrapper for AivisSpeech's VOICEVOX-compatible endpoints."""

    def __init__(self, config: AivisConfig, storage: StorageConfig) -> None:
        self._base_url = config.base_url.rstrip("/")
        self._voice_id = config.voice_id
        self._timeout_seconds = config.timeout_seconds
        self._audio_dir = storage.audio_dir

    async def synthesize(self, reply: GeneratedReply) -> SpeechJob:
        return await asyncio.to_thread(self._synthesize_sync, reply)

    def _synthesize_sync(self, reply: GeneratedReply) -> SpeechJob:
        started = perf_counter()
        audio_path = self._audio_dir / f"{new_id('audio')}.wav"
        try:
            audio_query = self._create_audio_query(reply.text)
            wav_bytes = self._synthesis(audio_query)
            self._audio_dir.mkdir(parents=True, exist_ok=True)
            audio_path.write_bytes(wav_bytes)
        except Exception as exc:
            return SpeechJob(
                reply_id=reply.id,
                text=reply.text,
                voice_id=self._voice_id,
                status="failed",
                error=str(exc),
                latency_ms=_elapsed_ms(started),
            )

        return SpeechJob(
            reply_id=reply.id,
            text=reply.text,
            voice_id=self._voice_id,
            status="created",
            audio_path=str(audio_path),
            latency_ms=_elapsed_ms(started),
        )

    def _create_audio_query(self, text: str) -> dict[str, object]:
        query = parse.urlencode({"text": text, "speaker": self._voice_id})
        http_request = request.Request(
            f"{self._base_url}/audio_query?{query}",
            data=b"",
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            raise ConnectionError(f"AivisSpeech audio_query failed: {exc}") from exc

    def _synthesis(self, audio_query: dict[str, object]) -> bytes:
        query = parse.urlencode({"speaker": self._voice_id})
        body = json.dumps(audio_query, ensure_ascii=False).encode("utf-8")
        http_request = request.Request(
            f"{self._base_url}/synthesis?{query}",
            data=body,
            headers={"Accept": "audio/wav", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                return response.read()
        except error.URLError as exc:
            raise ConnectionError(f"AivisSpeech synthesis failed: {exc}") from exc


def _elapsed_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))

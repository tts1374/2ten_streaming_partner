"""SQLite persistence for Phase 1 runtime events and model calls."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from aituber_partner.llm.client import LLMRequest, LLMResponse
from aituber_partner.models import ProcessedEvent, SafetyDecision, utc_now


class SQLiteStore:
    """Small synchronous SQLite adapter for local durable history."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._initialized = False

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS input_events (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    text TEXT NOT NULL,
                    author TEXT,
                    timestamp TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    image_ref TEXT
                );

                CREATE TABLE IF NOT EXISTS safety_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    input_event_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reasons_json TEXT NOT NULL,
                    safe_topic TEXT,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS generated_replies (
                    id TEXT PRIMARY KEY,
                    input_event_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    persona_version TEXT NOT NULL,
                    memory_refs_json TEXT NOT NULL,
                    generation_model TEXT NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS overlay_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    input_event_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    text TEXT NOT NULL,
                    detail TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS llm_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    think INTEGER,
                    latency_ms INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    error TEXT,
                    prompt_preview TEXT NOT NULL,
                    output_preview TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    response_json TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
        self._initialized = True

    def record_processed_event(self, processed: ProcessedEvent) -> None:
        self._ensure_initialized()
        now = _to_json_timestamp(utc_now())
        event = processed.input_event
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO input_events (
                    id, source, text, author, timestamp, metadata_json, image_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.source,
                    event.text,
                    event.author,
                    _to_json_timestamp(event.timestamp),
                    _json(event.metadata),
                    event.image_ref,
                ),
            )
            self._insert_safety_decision(
                connection,
                input_event_id=event.id,
                stage="input",
                decision=processed.safety,
                created_at=now,
            )
            if processed.output_safety is not None:
                self._insert_safety_decision(
                    connection,
                    input_event_id=event.id,
                    stage="output",
                    decision=processed.output_safety,
                    created_at=now,
                )
            if processed.reply is not None:
                reply = processed.reply
                connection.execute(
                    """
                    INSERT OR REPLACE INTO generated_replies (
                        id, input_event_id, text, persona_version, memory_refs_json,
                        generation_model, latency_ms, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reply.id,
                        event.id,
                        reply.text,
                        reply.persona_version,
                        _json(reply.memory_refs),
                        reply.generation_model,
                        reply.latency_ms,
                        now,
                    ),
                )
            overlay = processed.overlay
            connection.execute(
                """
                INSERT INTO overlay_events (
                    input_event_id, status, text, detail, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    overlay.status,
                    overlay.text,
                    overlay.detail,
                    _to_json_timestamp(overlay.updated_at),
                ),
            )

    def record_llm_call(
        self,
        llm_request: LLMRequest,
        *,
        response: LLMResponse | None = None,
        error: str | None = None,
    ) -> None:
        self._ensure_initialized()
        success = response is not None and error is None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO llm_calls (
                    model, purpose, think, latency_ms, success, error,
                    prompt_preview, output_preview, request_json, response_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    llm_request.model,
                    llm_request.purpose,
                    _bool_to_int(llm_request.think),
                    response.latency_ms if response is not None else 0,
                    1 if success else 0,
                    error,
                    _preview(llm_request.prompt),
                    _preview(response.text if response is not None else ""),
                    _json(llm_request.model_dump(mode="json")),
                    _json(response.model_dump(mode="json") if response is not None else None),
                    _to_json_timestamp(utc_now()),
                ),
            )

    def fetch_recent_llm_calls(self, *, limit: int = 20) -> list[dict[str, Any]]:
        self._ensure_initialized()
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT
                    id, model, purpose, think, latency_ms, success, error, created_at
                FROM llm_calls
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _insert_safety_decision(
        self,
        connection: sqlite3.Connection,
        *,
        input_event_id: str,
        stage: str,
        decision: SafetyDecision,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO safety_decisions (
                input_event_id, stage, status, reasons_json, safe_topic, confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                input_event_id,
                stage,
                decision.status,
                _json(decision.reasons),
                decision.safe_topic,
                decision.confidence,
                created_at,
            ),
        )

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _to_json_timestamp(value: Any) -> str:
    return value.isoformat()


def _preview(text: str, *, limit: int = 240) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


def _bool_to_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0

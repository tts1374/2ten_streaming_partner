import json
import sqlite3

from aituber_partner.llm.client import LLMRequest, LLMResponse
from aituber_partner.models import (
    GeneratedReply,
    InputEvent,
    OverlayState,
    ProcessedEvent,
    SafetyDecision,
    SpeechJob,
)
from aituber_partner.storage.sqlite_store import SQLiteStore


def fetch_one(db_path, query: str):
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(query).fetchone()


def fetch_all(db_path, query: str):
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(query).fetchall()


def test_record_processed_event_persists_runtime_tables(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    event = InputEvent(source="youtube_chat", text="ナイス精度！", author="viewer")
    reply = GeneratedReply(text="いい流れ！", generation_model="qwen3:8b", latency_ms=123)
    processed = ProcessedEvent(
        input_event=event,
        safety=SafetyDecision(status="allow", reasons=["safe"], confidence=0.9),
        output_safety=SafetyDecision(status="allow", reasons=["safe"], confidence=0.95),
        reply=reply,
        speech_job=SpeechJob(
            reply_id=reply.id,
            text=reply.text,
            voice_id=888753760,
            status="created",
            audio_path="data/audio/reply.wav",
            latency_ms=321,
        ),
        overlay=OverlayState(status="speaking", text=reply.text),
    )

    store.record_processed_event(processed)

    input_row = fetch_one(db_path, "SELECT * FROM input_events")
    assert input_row["id"] == event.id
    assert input_row["text"] == "ナイス精度！"

    safety_rows = fetch_all(db_path, "SELECT * FROM safety_decisions ORDER BY stage")
    assert [row["stage"] for row in safety_rows] == ["input", "output"]
    assert [row["status"] for row in safety_rows] == ["allow", "allow"]
    assert json.loads(safety_rows[0]["reasons_json"]) == ["safe"]

    reply_row = fetch_one(db_path, "SELECT * FROM generated_replies")
    assert reply_row["id"] == reply.id
    assert reply_row["generation_model"] == "qwen3:8b"
    assert reply_row["latency_ms"] == 123

    overlay_row = fetch_one(db_path, "SELECT * FROM overlay_events")
    assert overlay_row["status"] == "speaking"
    assert overlay_row["text"] == "いい流れ！"

    speech_row = fetch_one(db_path, "SELECT * FROM speech_jobs")
    assert speech_row["reply_id"] == reply.id
    assert speech_row["voice_id"] == 888753760
    assert speech_row["status"] == "created"
    assert speech_row["audio_path"] == "data/audio/reply.wav"
    assert speech_row["latency_ms"] == 321


def test_record_llm_call_persists_model_purpose_think_and_latency(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    request = LLMRequest(
        model="qwen3.5:4b",
        purpose="safety",
        prompt="check this",
        think=False,
        keep_alive="30m",
    )
    response = LLMResponse(model="qwen3.5:4b", text='{"status":"allow"}', latency_ms=456)

    store.record_llm_call(request, response=response)

    row = fetch_one(db_path, "SELECT * FROM llm_calls")
    assert row["model"] == "qwen3.5:4b"
    assert row["purpose"] == "safety"
    assert row["think"] == 0
    assert row["latency_ms"] == 456
    assert row["success"] == 1
    assert row["prompt_preview"] == "check this"
    assert json.loads(row["request_json"])["keep_alive"] == "30m"


def test_record_processed_idle_topic_event_persists_source_and_metadata(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    event = InputEvent(
        source="idle_topic",
        text="静かな間に、次の譜面の見どころを話す",
        author="idle-topic",
        metadata={"reason": "inactivity_timeout", "timeout_seconds": 30.0},
    )
    reply = GeneratedReply(
        text="次の配置も見どころだね！",
        generation_model="qwen3:8b",
        latency_ms=0,
    )
    processed = ProcessedEvent(
        input_event=event,
        safety=SafetyDecision(status="allow", reasons=["safe"], confidence=0.9),
        output_safety=SafetyDecision(status="allow", reasons=["safe"], confidence=0.9),
        reply=reply,
        overlay=OverlayState(status="speaking", text=reply.text),
    )

    store.record_processed_event(processed)

    input_row = fetch_one(db_path, "SELECT * FROM input_events")
    assert input_row["source"] == "idle_topic"
    assert json.loads(input_row["metadata_json"]) == {
        "reason": "inactivity_timeout",
        "timeout_seconds": 30.0,
    }


def test_record_llm_call_persists_failures_closed_for_diagnostics(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    request = LLMRequest(model="qwen3:8b", purpose="reply", prompt="reply", think=False)

    store.record_llm_call(request, error="connection failed")

    row = fetch_one(db_path, "SELECT * FROM llm_calls")
    assert row["success"] == 0
    assert row["error"] == "connection failed"
    assert row["latency_ms"] == 0


def test_fetch_recent_llm_calls_returns_newest_first_with_limit(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    for index in range(3):
        request = LLMRequest(
            model="qwen3.5:4b",
            purpose=f"safety-{index}",
            prompt="check",
            think=False,
        )
        response = LLMResponse(model="qwen3.5:4b", text="{}", latency_ms=100 + index)
        store.record_llm_call(request, response=response)

    rows = store.fetch_recent_llm_calls(limit=2)

    assert [row["purpose"] for row in rows] == ["safety-2", "safety-1"]
    assert [row["latency_ms"] for row in rows] == [102, 101]
    assert rows[0]["think"] == 0
    assert rows[0]["success"] == 1


def test_fetch_recent_input_events_returns_newest_first_with_limit(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    for index in range(3):
        event = InputEvent(source="youtube_chat", text=f"コメント{index}", author="viewer")
        processed = ProcessedEvent(
            input_event=event,
            safety=SafetyDecision(status="allow", reasons=["safe"], confidence=0.9),
            reply=None,
            overlay=OverlayState(status="idle", text=""),
        )
        store.record_processed_event(processed)

    rows = store.fetch_recent_input_events(limit=2)

    assert [row["text"] for row in rows] == ["コメント2", "コメント1"]
    assert rows[0]["source"] == "youtube_chat"
    assert rows[0]["author"] == "viewer"


def test_fetch_recent_generated_replies_includes_input_context(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    event = InputEvent(source="youtube_chat", text="音量大丈夫？", author="viewer")
    reply = GeneratedReply(text="つてん、音量どうかな？", generation_model="qwen3:8b", latency_ms=123)
    processed = ProcessedEvent(
        input_event=event,
        safety=SafetyDecision(status="allow", reasons=["safe"], confidence=0.9),
        output_safety=SafetyDecision(status="allow", reasons=["safe"], confidence=0.9),
        reply=reply,
        overlay=OverlayState(status="speaking", text=reply.text),
    )
    store.record_processed_event(processed)

    rows = store.fetch_recent_generated_replies(limit=1)

    assert rows[0]["id"] == reply.id
    assert rows[0]["input_event_id"] == event.id
    assert rows[0]["input_source"] == "youtube_chat"
    assert rows[0]["input_text"] == "音量大丈夫？"
    assert rows[0]["text"] == "つてん、音量どうかな？"
    assert rows[0]["generation_model"] == "qwen3:8b"


def test_fetch_recent_speech_jobs_returns_status_and_error(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    event = InputEvent(source="youtube_chat", text="聞こえてる？", author="viewer")
    reply = GeneratedReply(text="声の聞こえ方どう？", generation_model="qwen3:8b", latency_ms=123)
    speech_job = SpeechJob(
        reply_id=reply.id,
        text=reply.text,
        voice_id=888753760,
        status="failed",
        error="AivisSpeech is not running",
    )
    processed = ProcessedEvent(
        input_event=event,
        safety=SafetyDecision(status="allow", reasons=["safe"], confidence=0.9),
        output_safety=SafetyDecision(status="allow", reasons=["safe"], confidence=0.9),
        reply=reply,
        speech_job=speech_job,
        overlay=OverlayState(status="speaking", text=reply.text),
    )
    store.record_processed_event(processed)

    rows = store.fetch_recent_speech_jobs(limit=1)

    assert rows[0]["id"] == speech_job.id
    assert rows[0]["reply_id"] == reply.id
    assert rows[0]["input_event_id"] == event.id
    assert rows[0]["status"] == "failed"
    assert rows[0]["voice_id"] == 888753760
    assert rows[0]["error"] == "AivisSpeech is not running"


def test_fetch_recent_safety_decisions_includes_input_context(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    event = InputEvent(source="youtube_chat", text="これは拾える？", author="viewer")
    processed = ProcessedEvent(
        input_event=event,
        safety=SafetyDecision(status="allow", reasons=["safe"], confidence=0.9),
        output_safety=SafetyDecision(status="deflect", reasons=["too_long"], confidence=0.7),
        reply=None,
        overlay=OverlayState(status="idle", text=""),
    )
    store.record_processed_event(processed)

    rows = store.fetch_recent_safety_decisions(limit=2)

    assert [row["stage"] for row in rows] == ["output", "input"]
    assert rows[0]["input_event_id"] == event.id
    assert rows[0]["input_source"] == "youtube_chat"
    assert rows[0]["input_text"] == "これは拾える？"
    assert rows[0]["status"] == "deflect"
    assert json.loads(rows[0]["reasons_json"]) == ["too_long"]


def test_fetch_recent_overlay_events_includes_input_context(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    store = SQLiteStore(db_path)
    event = InputEvent(source="idle_topic", text="次の話題", author="idle-topic")
    processed = ProcessedEvent(
        input_event=event,
        safety=SafetyDecision(status="allow", reasons=["safe"], confidence=0.9),
        reply=None,
        overlay=OverlayState(status="idle", text="", detail="waiting"),
    )
    store.record_processed_event(processed)

    rows = store.fetch_recent_overlay_events(limit=1)

    assert rows[0]["input_event_id"] == event.id
    assert rows[0]["input_source"] == "idle_topic"
    assert rows[0]["status"] == "idle"
    assert rows[0]["text"] == ""
    assert rows[0]["detail"] == "waiting"

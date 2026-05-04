"""Command-line entry point for the local closed-loop PoC."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from aituber_partner.config import AppConfig, load_config
from aituber_partner.inputs.base import InputSource
from aituber_partner.inputs.fake import FakeInputSource
from aituber_partner.inputs.idle_topic import IdleTopicInputSource
from aituber_partner.inputs.youtube_chat import YouTubeChatInputSource
from aituber_partner.llm.client import LLMCallRecorder, OllamaClient, RecordingLLMClient
from aituber_partner.llm.router import LLMRouter
from aituber_partner.orchestrator import LocalClosedLoopOrchestrator
from aituber_partner.overlay.server import OverlayServerRunner, OverlayStateBroadcaster
from aituber_partner.models import OverlayState
from aituber_partner.speech.aivis import AivisSpeechClient
from aituber_partner.speech.player import WaveAudioPlayer
from aituber_partner.storage.sqlite_store import SQLiteStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local AITuber partner PoC.")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional TOML config path, such as config/local.toml.",
    )
    parser.add_argument(
        "--use-ollama",
        action="store_true",
        help="Use the configured Ollama LLM route instead of deterministic placeholder replies.",
    )
    parser.add_argument(
        "--fast-output-safety",
        action="store_true",
        help="Use a local final output guard instead of an extra LLM safety call.",
    )
    parser.add_argument(
        "--use-aivis",
        action="store_true",
        help="Generate reply audio with local AivisSpeech and store speech job results.",
    )
    parser.add_argument(
        "--serve-overlay",
        action="store_true",
        help="Serve the OBS subtitle overlay and stream OverlayState over SSE.",
    )
    parser.add_argument(
        "--use-youtube-chat",
        action="store_true",
        help="Read YouTube Live Chat from youtube_chat config instead of fake comments.",
    )
    parser.add_argument(
        "--youtube-video-id",
        default=None,
        help="Resolve youtube_chat.live_chat_id from a YouTube video ID for this run.",
    )
    subparsers = parser.add_subparsers(dest="command")
    inspect_parser = subparsers.add_parser(
        "inspect-latency",
        help="Show recent LLM call latency records from SQLite.",
    )
    inspect_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of recent LLM calls to display.",
    )
    inspect_events_parser = subparsers.add_parser(
        "inspect-events",
        help="Show recent normalized input events from SQLite.",
    )
    inspect_events_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of recent input events to display.",
    )
    inspect_replies_parser = subparsers.add_parser(
        "inspect-replies",
        help="Show recent generated co-host replies from SQLite.",
    )
    inspect_replies_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of recent replies to display.",
    )
    inspect_speech_parser = subparsers.add_parser(
        "inspect-speech",
        help="Show recent AivisSpeech jobs from SQLite.",
    )
    inspect_speech_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of recent speech jobs to display.",
    )
    inspect_safety_parser = subparsers.add_parser(
        "inspect-safety",
        help="Show recent input/output safety decisions from SQLite.",
    )
    inspect_safety_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of recent safety decisions to display.",
    )
    inspect_overlay_parser = subparsers.add_parser(
        "inspect-overlay",
        help="Show recent subtitle overlay events from SQLite.",
    )
    inspect_overlay_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of recent overlay events to display.",
    )
    demo_parser = subparsers.add_parser(
        "demo-overlay",
        help="Serve the OBS overlay and show a demo subtitle for visual adjustment.",
    )
    demo_parser.add_argument(
        "--text",
        default="OBS表示テスト中です！この字幕が見えていればOKです。",
        help="Subtitle text to show in the overlay.",
    )
    demo_parser.add_argument(
        "--seconds",
        type=float,
        default=10.0,
        help="How long to keep the demo subtitle visible.",
    )
    demo_parser.add_argument(
        "--keep-visible",
        action="store_true",
        help="Keep the demo subtitle visible while the overlay server stays open.",
    )
    return parser


def build_llm_router(
    config: AppConfig,
    *,
    use_ollama: bool,
    recorder: LLMCallRecorder | None = None,
) -> LLMRouter | None:
    if not use_ollama:
        return None

    client = OllamaClient(base_url=config.ollama.base_url)
    if recorder is not None:
        client = RecordingLLMClient(client=client, recorder=recorder)
    return LLMRouter(config=config, client=client)


def build_input_source(
    config: AppConfig,
    *,
    use_youtube_chat: bool,
    youtube_video_id: str | None = None,
) -> InputSource:
    if use_youtube_chat:
        api_key = os.environ.get(config.youtube_chat.api_key_env, "")
        youtube_chat_config = config.youtube_chat
        if youtube_video_id:
            youtube_chat_config = youtube_chat_config.model_copy(
                update={"live_chat_id": None, "video_id": youtube_video_id}
            )
        source: InputSource = YouTubeChatInputSource(youtube_chat_config, api_key=api_key)
    else:
        source = FakeInputSource.from_texts(
            [
                "今日の判定、かなり光ってますね！",
                "この曲のサビ、リズム取りやすいですか？",
            ]
        )

    return IdleTopicInputSource(
        source,
        timeout_seconds=config.runtime.idle_timeout_seconds,
        repeat_interval_seconds=config.runtime.idle_repeat_interval_seconds,
        topics=config.runtime.idle_topics,
    )


async def run(
    config: AppConfig,
    *,
    use_ollama: bool = False,
    fast_output_safety: bool = False,
    use_aivis: bool = False,
    serve_overlay: bool = False,
    use_youtube_chat: bool = False,
    youtube_video_id: str | None = None,
) -> None:
    store = SQLiteStore(config.storage.sqlite_path)
    store.initialize()
    source = build_input_source(
        config,
        use_youtube_chat=use_youtube_chat,
        youtube_video_id=youtube_video_id,
    )
    broadcaster = OverlayStateBroadcaster()
    runner = OverlayServerRunner(config.overlay, broadcaster) if serve_overlay else None
    if runner is not None:
        runner.start()
        print(f"OBS subtitle overlay: {runner.url}")
    try:
        orchestrator = LocalClosedLoopOrchestrator(
            config=config,
            input_source=source,
            llm_router=build_llm_router(config, use_ollama=use_ollama, recorder=store),
            speech_synthesizer=AivisSpeechClient(config.aivis, config.storage) if use_aivis else None,
            audio_player=WaveAudioPlayer() if use_aivis else None,
            recorder=store,
            overlay_publisher=broadcaster if serve_overlay else None,
            use_local_output_guard=fast_output_safety,
        )

        async for result in orchestrator.run_once_per_event():
            print(f"[{result.overlay.status}] {result.overlay.text}")
        if runner is not None:
            print("Overlay server is still running. Press Ctrl+C to stop.")
            await asyncio.Event().wait()
    finally:
        if runner is not None:
            runner.stop()


def inspect_latency(config: AppConfig, *, limit: int) -> None:
    store = SQLiteStore(config.storage.sqlite_path)
    rows = store.fetch_recent_llm_calls(limit=max(1, limit))
    if not rows:
        print(f"No LLM calls found in {store.path}.")
        return

    headers = ["id", "model", "purpose", "latency_ms", "think", "success", "error"]
    widths = {
        "id": 4,
        "model": 24,
        "purpose": 14,
        "latency_ms": 10,
        "think": 5,
        "success": 7,
        "error": 32,
    }
    _print_table(
        headers,
        widths,
        [
            {
                "id": str(row["id"]),
                "model": row["model"],
                "purpose": row["purpose"],
                "latency_ms": str(row["latency_ms"]),
                "think": _format_bool(row["think"]),
                "success": _format_bool(row["success"]),
                "error": _truncate(row["error"] or "", widths["error"]),
            }
            for row in rows
        ],
    )


def inspect_events(config: AppConfig, *, limit: int) -> None:
    store = SQLiteStore(config.storage.sqlite_path)
    rows = store.fetch_recent_input_events(limit=max(1, limit))
    if not rows:
        print(f"No input events found in {store.path}.")
        return

    headers = ["source", "author", "text", "metadata", "timestamp"]
    widths = {"source": 12, "author": 16, "text": 40, "metadata": 36, "timestamp": 25}
    _print_table(
        headers,
        widths,
        [
            {
                "source": row["source"],
                "author": _truncate(row["author"] or "", widths["author"]),
                "text": _truncate(row["text"], widths["text"]),
                "metadata": _truncate(row["metadata_json"], widths["metadata"]),
                "timestamp": row["timestamp"],
            }
            for row in rows
        ],
    )


def inspect_replies(config: AppConfig, *, limit: int) -> None:
    store = SQLiteStore(config.storage.sqlite_path)
    rows = store.fetch_recent_generated_replies(limit=max(1, limit))
    if not rows:
        print(f"No generated replies found in {store.path}.")
        return

    headers = ["source", "input", "reply", "model", "latency_ms", "created_at"]
    widths = {
        "source": 12,
        "input": 36,
        "reply": 44,
        "model": 18,
        "latency_ms": 10,
        "created_at": 25,
    }
    _print_table(
        headers,
        widths,
        [
            {
                "source": row["input_source"] or "",
                "input": _truncate(row["input_text"] or "", widths["input"]),
                "reply": _truncate(row["text"], widths["reply"]),
                "model": row["generation_model"],
                "latency_ms": str(row["latency_ms"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ],
    )


def inspect_speech(config: AppConfig, *, limit: int) -> None:
    store = SQLiteStore(config.storage.sqlite_path)
    rows = store.fetch_recent_speech_jobs(limit=max(1, limit))
    if not rows:
        print(f"No speech jobs found in {store.path}.")
        return

    headers = ["status", "voice_id", "text", "latency_ms", "audio_path", "error"]
    widths = {
        "status": 8,
        "voice_id": 10,
        "text": 40,
        "latency_ms": 10,
        "audio_path": 32,
        "error": 32,
    }
    _print_table(
        headers,
        widths,
        [
            {
                "status": row["status"],
                "voice_id": str(row["voice_id"]),
                "text": _truncate(row["text"], widths["text"]),
                "latency_ms": str(row["latency_ms"]),
                "audio_path": _truncate(row["audio_path"] or "", widths["audio_path"]),
                "error": _truncate(row["error"] or "", widths["error"]),
            }
            for row in rows
        ],
    )


def inspect_safety(config: AppConfig, *, limit: int) -> None:
    store = SQLiteStore(config.storage.sqlite_path)
    rows = store.fetch_recent_safety_decisions(limit=max(1, limit))
    if not rows:
        print(f"No safety decisions found in {store.path}.")
        return

    headers = ["stage", "status", "source", "input", "reasons", "confidence", "created_at"]
    widths = {
        "stage": 8,
        "status": 10,
        "source": 12,
        "input": 32,
        "reasons": 36,
        "confidence": 10,
        "created_at": 25,
    }
    _print_table(
        headers,
        widths,
        [
            {
                "stage": row["stage"],
                "status": row["status"],
                "source": row["input_source"] or "",
                "input": _truncate(row["input_text"] or "", widths["input"]),
                "reasons": _truncate(row["reasons_json"], widths["reasons"]),
                "confidence": f"{row['confidence']:.2f}",
                "created_at": row["created_at"],
            }
            for row in rows
        ],
    )


def inspect_overlay(config: AppConfig, *, limit: int) -> None:
    store = SQLiteStore(config.storage.sqlite_path)
    rows = store.fetch_recent_overlay_events(limit=max(1, limit))
    if not rows:
        print(f"No overlay events found in {store.path}.")
        return

    headers = ["status", "source", "text", "detail", "updated_at"]
    widths = {"status": 10, "source": 12, "text": 44, "detail": 32, "updated_at": 25}
    _print_table(
        headers,
        widths,
        [
            {
                "status": row["status"],
                "source": row["input_source"] or "",
                "text": _truncate(row["text"], widths["text"]),
                "detail": _truncate(row["detail"] or "", widths["detail"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ],
    )


def _print_table(
    headers: list[str],
    widths: dict[str, int],
    rows: list[dict[str, str]],
) -> None:
    print(" ".join(header.ljust(widths[header]) for header in headers))
    print(" ".join("-" * widths[header] for header in headers))
    for row in rows:
        print(" ".join(row[header].ljust(widths[header]) for header in headers))


async def demo_overlay(
    config: AppConfig,
    *,
    text: str,
    seconds: float,
    keep_visible: bool = False,
) -> None:
    broadcaster = OverlayStateBroadcaster(
        OverlayState(
            speaker_name=config.overlay.speaker_name,
            show_detail=config.overlay.show_detail,
        )
    )
    runner = OverlayServerRunner(config.overlay, broadcaster)
    runner.start()
    try:
        print(f"OBS subtitle overlay: {runner.url}")
        broadcaster.publish(
            OverlayState(
                status="speaking",
                text=text,
                speaker_name=config.overlay.speaker_name,
                show_detail=config.overlay.show_detail,
            )
        )
        if keep_visible:
            print("Showing demo subtitle until Ctrl+C.")
        else:
            print(f"Showing demo subtitle for {seconds:g} seconds.")
            await asyncio.sleep(max(0.0, seconds))
            broadcaster.publish(
                OverlayState(
                    status="idle",
                    text="",
                    speaker_name=config.overlay.speaker_name,
                    show_detail=config.overlay.show_detail,
                )
            )
            print("Demo subtitle cleared. Overlay server is still running. Press Ctrl+C to stop.")
        await asyncio.Event().wait()
    finally:
        runner.stop()


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)
    if args.command == "inspect-latency":
        inspect_latency(config, limit=args.limit)
        return
    if args.command == "inspect-events":
        inspect_events(config, limit=args.limit)
        return
    if args.command == "inspect-replies":
        inspect_replies(config, limit=args.limit)
        return
    if args.command == "inspect-speech":
        inspect_speech(config, limit=args.limit)
        return
    if args.command == "inspect-safety":
        inspect_safety(config, limit=args.limit)
        return
    if args.command == "inspect-overlay":
        inspect_overlay(config, limit=args.limit)
        return
    if args.command == "demo-overlay":
        asyncio.run(
            demo_overlay(
                config,
                text=args.text,
                seconds=args.seconds,
                keep_visible=args.keep_visible,
            )
        )
        return

    asyncio.run(
        run(
            config,
            use_ollama=args.use_ollama,
            fast_output_safety=args.fast_output_safety,
            use_aivis=args.use_aivis,
            serve_overlay=args.serve_overlay,
            use_youtube_chat=args.use_youtube_chat,
            youtube_video_id=args.youtube_video_id,
        )
    )


def _format_bool(value: int | None) -> str:
    if value is None:
        return "-"
    return "yes" if value else "no"


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


if __name__ == "__main__":
    main()

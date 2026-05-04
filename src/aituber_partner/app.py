"""Command-line entry point for the local closed-loop PoC."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from aituber_partner.config import AppConfig, load_config
from aituber_partner.inputs.fake import FakeInputSource
from aituber_partner.inputs.idle_topic import IdleTopicInputSource
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


async def run(
    config: AppConfig,
    *,
    use_ollama: bool = False,
    fast_output_safety: bool = False,
    use_aivis: bool = False,
    serve_overlay: bool = False,
) -> None:
    store = SQLiteStore(config.storage.sqlite_path)
    store.initialize()
    source = FakeInputSource.from_texts(
        [
            "今日の判定、かなり光ってますね！",
            "この曲のサビ、リズム取りやすいですか？",
        ]
    )
    source = IdleTopicInputSource(
        source,
        timeout_seconds=config.runtime.idle_timeout_seconds,
        topics=config.runtime.idle_topics,
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
    print(" ".join(header.ljust(widths[header]) for header in headers))
    print(" ".join("-" * widths[header] for header in headers))
    for row in rows:
        values = {
            "id": str(row["id"]),
            "model": row["model"],
            "purpose": row["purpose"],
            "latency_ms": str(row["latency_ms"]),
            "think": _format_bool(row["think"]),
            "success": _format_bool(row["success"]),
            "error": _truncate(row["error"] or "", widths["error"]),
        }
        print(" ".join(values[header].ljust(widths[header]) for header in headers))


async def demo_overlay(config: AppConfig, *, text: str, seconds: float) -> None:
    broadcaster = OverlayStateBroadcaster()
    runner = OverlayServerRunner(config.overlay, broadcaster)
    runner.start()
    try:
        print(f"OBS subtitle overlay: {runner.url}")
        print(f"Showing demo subtitle for {seconds:g} seconds.")
        broadcaster.publish(OverlayState(status="speaking", text=text))
        await asyncio.sleep(max(0.0, seconds))
        broadcaster.publish(OverlayState(status="idle", text=""))
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
    if args.command == "demo-overlay":
        asyncio.run(demo_overlay(config, text=args.text, seconds=args.seconds))
        return

    asyncio.run(
        run(
            config,
            use_ollama=args.use_ollama,
            fast_output_safety=args.fast_output_safety,
            use_aivis=args.use_aivis,
            serve_overlay=args.serve_overlay,
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

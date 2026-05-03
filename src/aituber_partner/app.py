"""Command-line entry point for the local closed-loop PoC."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from aituber_partner.config import AppConfig, load_config
from aituber_partner.inputs.fake import FakeInputSource
from aituber_partner.llm.client import LLMCallRecorder, OllamaClient, RecordingLLMClient
from aituber_partner.llm.router import LLMRouter
from aituber_partner.orchestrator import LocalClosedLoopOrchestrator
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
) -> None:
    store = SQLiteStore(config.storage.sqlite_path)
    store.initialize()
    source = FakeInputSource.from_texts(
        [
            "今日の判定、かなり光ってますね！",
            "この曲のサビ、リズム取りやすいですか？",
        ]
    )
    orchestrator = LocalClosedLoopOrchestrator(
        config=config,
        input_source=source,
        llm_router=build_llm_router(config, use_ollama=use_ollama, recorder=store),
        recorder=store,
        use_local_output_guard=fast_output_safety,
    )

    async for result in orchestrator.run_once_per_event():
        print(f"[{result.overlay.status}] {result.overlay.text}")


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)
    asyncio.run(
        run(
            config,
            use_ollama=args.use_ollama,
            fast_output_safety=args.fast_output_safety,
        )
    )


if __name__ == "__main__":
    main()

"""Command-line entry point for the local closed-loop PoC."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from aituber_partner.config import AppConfig, load_config
from aituber_partner.inputs.fake import FakeInputSource
from aituber_partner.llm.client import OllamaClient
from aituber_partner.llm.router import LLMRouter
from aituber_partner.orchestrator import LocalClosedLoopOrchestrator


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
    return parser


def build_llm_router(config: AppConfig, *, use_ollama: bool) -> LLMRouter | None:
    if not use_ollama:
        return None

    client = OllamaClient(base_url=config.ollama.base_url)
    return LLMRouter(config=config, client=client)


async def run(config: AppConfig, *, use_ollama: bool = False) -> None:
    source = FakeInputSource.from_texts(
        [
            "今日の判定、かなり光ってますね！",
            "この曲のサビ、リズム取りやすいですか？",
        ]
    )
    orchestrator = LocalClosedLoopOrchestrator(
        config=config,
        input_source=source,
        llm_router=build_llm_router(config, use_ollama=use_ollama),
    )

    async for result in orchestrator.run_once_per_event():
        print(f"[{result.overlay.status}] {result.overlay.text}")


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)
    asyncio.run(run(config, use_ollama=args.use_ollama))


if __name__ == "__main__":
    main()

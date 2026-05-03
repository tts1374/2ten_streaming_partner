"""Application configuration loading."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


class OllamaConfig(BaseModel):
    base_url: str = "http://127.0.0.1:11434"
    keep_alive: str = "30m"


class ModelConfig(BaseModel):
    classifier: str = "qwen3.5:4b"
    reply: str = "qwen3:8b"
    vision: str = "qwen3.5:9b"
    review: str = "pakachan/elyza-llama3-8b"


class AivisConfig(BaseModel):
    base_url: str = "http://127.0.0.1:10101"
    voice_id: str = "default"


class OverlayConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787


class StorageConfig(BaseModel):
    sqlite_path: Path = Path("data/app.db")
    lancedb_path: Path = Path("data/lancedb")
    audio_dir: Path = Path("data/audio")


class RuntimeConfig(BaseModel):
    idle_timeout_seconds: float = Field(default=30.0, gt=0)


class AppConfig(BaseModel):
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    models: ModelConfig = Field(default_factory=ModelConfig)
    aivis: AivisConfig = Field(default_factory=AivisConfig)
    overlay: OverlayConfig = Field(default_factory=OverlayConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)


def load_config(path: Path | None = None) -> AppConfig:
    """Load optional TOML configuration, falling back to safe local defaults."""

    if path is None:
        return AppConfig()

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("rb") as config_file:
        data = tomllib.load(config_file)
    return AppConfig.model_validate(data)


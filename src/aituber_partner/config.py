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
    voice_id: int = 888753760
    timeout_seconds: float = Field(default=30.0, gt=0)


class OverlayConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787
    speaker_name: str = Field(default="2ten", min_length=1)
    show_detail: bool = False
    clear_after_speech_seconds: float = Field(default=2.5, ge=0)


class YouTubeChatConfig(BaseModel):
    live_chat_id: str | None = None
    video_id: str | None = None
    api_key_env: str = Field(default="YOUTUBE_API_KEY", min_length=1)
    poll_interval_seconds: float = Field(default=5.0, gt=0)
    min_poll_interval_seconds: float = Field(default=1.0, gt=0)
    request_timeout_seconds: float = Field(default=10.0, gt=0)
    max_results: int = Field(default=200, ge=200, le=2000)
    max_selected_per_poll: int = Field(default=3, ge=1, le=20)
    max_message_length: int = Field(default=160, ge=1, le=1000)
    drop_symbol_heavy_messages: bool = True
    symbol_heavy_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    drop_duplicate_text_per_poll: bool = True
    recent_duplicate_text_window_seconds: float = Field(default=30.0, ge=0.0)
    drop_repetitive_messages: bool = True
    repetitive_text_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    repetitive_text_min_length: int = Field(default=8, ge=1, le=200)
    skip_initial_history: bool = True


class STTConfig(BaseModel):
    model_name: str = "small"
    language: str = "ja"
    device: str = "auto"
    compute_type: str = "auto"
    microphone_device: str | None = None
    sample_rate: int = Field(default=16000, gt=0)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class StorageConfig(BaseModel):
    sqlite_path: Path = Path("data/app.db")
    lancedb_path: Path = Path("data/lancedb")
    audio_dir: Path = Path("data/audio")


class RuntimeConfig(BaseModel):
    streamer_name: str = Field(default="つてん", min_length=1)
    idle_timeout_seconds: float = Field(default=30.0, gt=0)
    idle_repeat_interval_seconds: float = Field(default=120.0, gt=0)
    idle_topics: list[str] = Field(
        default_factory=lambda: [
            "最近プレイした音ゲー曲で、判定が光った瞬間の話",
            "今日の配信で次に注目したい譜面の見どころ",
            "リズムに乗りやすい曲の好きなポイント",
        ],
        min_length=1,
    )


class AppConfig(BaseModel):
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    models: ModelConfig = Field(default_factory=ModelConfig)
    aivis: AivisConfig = Field(default_factory=AivisConfig)
    overlay: OverlayConfig = Field(default_factory=OverlayConfig)
    youtube_chat: YouTubeChatConfig = Field(default_factory=YouTubeChatConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
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

from pathlib import Path

import pytest

from aituber_partner.config import AppConfig, load_config


def test_default_config_uses_phase1_model_roles() -> None:
    config = AppConfig()

    assert config.models.classifier == "qwen3.5:4b"
    assert config.models.reply == "qwen3:8b"
    assert config.models.vision == "qwen3.5:9b"
    assert config.models.review == "pakachan/elyza-llama3-8b"
    assert config.aivis.base_url == "http://127.0.0.1:10101"
    assert isinstance(config.aivis.voice_id, int)
    assert config.overlay.speaker_name == "2ten"
    assert config.overlay.show_detail is False
    assert config.overlay.clear_after_speech_seconds == 2.5
    assert config.youtube_chat.live_chat_id is None
    assert config.youtube_chat.video_id is None
    assert config.youtube_chat.api_key_env == "YOUTUBE_API_KEY"
    assert config.youtube_chat.skip_initial_history is True
    assert config.runtime.idle_timeout_seconds == 30.0
    assert config.runtime.streamer_name == "つてん"
    assert config.runtime.idle_repeat_interval_seconds == 120.0
    assert config.runtime.idle_topics


def test_load_config_overrides_toml_values(tmp_path: Path) -> None:
    config_path = tmp_path / "local.toml"
    config_path.write_text(
        """
[overlay]
port = 9999
speaker_name = "てん"
show_detail = true
clear_after_speech_seconds = 1.25

[youtube_chat]
live_chat_id = "live-chat-1"
video_id = "video-1"
api_key_env = "YT_TEST_KEY"
poll_interval_seconds = 3.0
min_poll_interval_seconds = 2.0
request_timeout_seconds = 4.0
max_results = 200
skip_initial_history = false

[runtime]
streamer_name = "配信者"
idle_timeout_seconds = 12.5
idle_repeat_interval_seconds = 75.0
idle_topics = ["判定が光った話", "次の曲の見どころ"]
""".lstrip(),
        encoding="utf-8",
        newline="\n",
    )

    config = load_config(config_path)

    assert config.overlay.port == 9999
    assert config.overlay.speaker_name == "てん"
    assert config.overlay.show_detail is True
    assert config.overlay.clear_after_speech_seconds == 1.25
    assert config.youtube_chat.live_chat_id == "live-chat-1"
    assert config.youtube_chat.video_id == "video-1"
    assert config.youtube_chat.api_key_env == "YT_TEST_KEY"
    assert config.youtube_chat.poll_interval_seconds == 3.0
    assert config.youtube_chat.min_poll_interval_seconds == 2.0
    assert config.youtube_chat.request_timeout_seconds == 4.0
    assert config.youtube_chat.max_results == 200
    assert config.youtube_chat.skip_initial_history is False
    assert config.runtime.idle_timeout_seconds == 12.5
    assert config.runtime.streamer_name == "配信者"
    assert config.runtime.idle_repeat_interval_seconds == 75.0
    assert config.runtime.idle_topics == ["判定が光った話", "次の曲の見どころ"]


def test_load_config_requires_existing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.toml")

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
    assert config.overlay.clear_after_speech_seconds == 2.5
    assert config.runtime.idle_timeout_seconds == 30.0
    assert config.runtime.idle_topics


def test_load_config_overrides_toml_values(tmp_path: Path) -> None:
    config_path = tmp_path / "local.toml"
    config_path.write_text(
        """
[overlay]
port = 9999
clear_after_speech_seconds = 1.25

[runtime]
idle_timeout_seconds = 12.5
idle_topics = ["判定が光った話", "次の曲の見どころ"]
""".lstrip(),
        encoding="utf-8",
        newline="\n",
    )

    config = load_config(config_path)

    assert config.overlay.port == 9999
    assert config.overlay.clear_after_speech_seconds == 1.25
    assert config.runtime.idle_timeout_seconds == 12.5
    assert config.runtime.idle_topics == ["判定が光った話", "次の曲の見どころ"]


def test_load_config_requires_existing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.toml")

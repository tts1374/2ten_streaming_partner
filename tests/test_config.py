from pathlib import Path

import pytest

from aituber_partner.config import AppConfig, load_config


def test_default_config_uses_phase1_model_roles() -> None:
    config = AppConfig()

    assert config.models.classifier == "qwen3.5:4b"
    assert config.models.reply == "qwen3:8b"
    assert config.models.vision == "qwen3.5:9b"
    assert config.models.review == "pakachan/elyza-llama3-8b"


def test_load_config_overrides_toml_values(tmp_path: Path) -> None:
    config_path = tmp_path / "local.toml"
    config_path.write_text(
        """
[overlay]
port = 9999

[runtime]
idle_timeout_seconds = 12.5
""".lstrip(),
        encoding="utf-8",
        newline="\n",
    )

    config = load_config(config_path)

    assert config.overlay.port == 9999
    assert config.runtime.idle_timeout_seconds == 12.5


def test_load_config_requires_existing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.toml")


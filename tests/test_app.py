from aituber_partner.app import build_input_source, build_llm_router, build_parser
from aituber_partner.config import AppConfig, YouTubeChatConfig
from aituber_partner.llm.router import LLMRouter


def test_parser_defaults_to_placeholder_route() -> None:
    args = build_parser().parse_args([])

    assert args.use_ollama is False
    assert args.fast_output_safety is False
    assert args.use_aivis is False
    assert args.serve_overlay is False
    assert args.use_youtube_chat is False
    assert args.youtube_video_id is None


def test_parser_accepts_use_ollama_switch() -> None:
    args = build_parser().parse_args(["--use-ollama"])

    assert args.use_ollama is True


def test_parser_accepts_fast_output_safety_switch() -> None:
    args = build_parser().parse_args(["--fast-output-safety"])

    assert args.fast_output_safety is True


def test_parser_accepts_use_aivis_switch() -> None:
    args = build_parser().parse_args(["--use-aivis"])

    assert args.use_aivis is True


def test_parser_accepts_serve_overlay_switch() -> None:
    args = build_parser().parse_args(["--serve-overlay"])

    assert args.serve_overlay is True


def test_parser_accepts_use_youtube_chat_switch() -> None:
    args = build_parser().parse_args(["--use-youtube-chat"])

    assert args.use_youtube_chat is True


def test_parser_accepts_youtube_video_id_override() -> None:
    args = build_parser().parse_args(["--use-youtube-chat", "--youtube-video-id", "video-1"])

    assert args.youtube_video_id == "video-1"


def test_parser_accepts_inspect_latency_command() -> None:
    args = build_parser().parse_args(["inspect-latency", "--limit", "5"])

    assert args.command == "inspect-latency"
    assert args.limit == 5


def test_parser_accepts_demo_overlay_command() -> None:
    args = build_parser().parse_args(
        ["demo-overlay", "--text", "OBS表示テスト", "--seconds", "8.5", "--keep-visible"]
    )

    assert args.command == "demo-overlay"
    assert args.text == "OBS表示テスト"
    assert args.seconds == 8.5
    assert args.keep_visible is True


def test_build_llm_router_returns_none_without_ollama_switch() -> None:
    router = build_llm_router(AppConfig(), use_ollama=False)

    assert router is None


def test_build_llm_router_uses_configured_models_with_ollama_switch() -> None:
    router = build_llm_router(AppConfig(), use_ollama=True)

    assert isinstance(router, LLMRouter)
    request = router.build_request(purpose="reply", prompt="hello")
    assert request.model == "qwen3:8b"
    assert request.think is False


def test_build_input_source_requires_youtube_api_key(monkeypatch) -> None:
    monkeypatch.delenv("YT_TEST_KEY", raising=False)
    config = AppConfig(
        youtube_chat=YouTubeChatConfig(live_chat_id="live-chat-1", api_key_env="YT_TEST_KEY")
    )

    try:
        build_input_source(config, use_youtube_chat=True)
    except ValueError as exc:
        assert "API key" in str(exc)
        return

    raise AssertionError("YouTube chat input should require an API key")

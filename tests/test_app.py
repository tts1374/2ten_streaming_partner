from aituber_partner.app import build_llm_router, build_parser
from aituber_partner.config import AppConfig
from aituber_partner.llm.router import LLMRouter


def test_parser_defaults_to_placeholder_route() -> None:
    args = build_parser().parse_args([])

    assert args.use_ollama is False
    assert args.fast_output_safety is False
    assert args.use_aivis is False
    assert args.serve_overlay is False


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


def test_parser_accepts_inspect_latency_command() -> None:
    args = build_parser().parse_args(["inspect-latency", "--limit", "5"])

    assert args.command == "inspect-latency"
    assert args.limit == 5


def test_parser_accepts_demo_overlay_command() -> None:
    args = build_parser().parse_args(
        ["demo-overlay", "--text", "OBS表示テスト", "--seconds", "8.5"]
    )

    assert args.command == "demo-overlay"
    assert args.text == "OBS表示テスト"
    assert args.seconds == 8.5


def test_build_llm_router_returns_none_without_ollama_switch() -> None:
    router = build_llm_router(AppConfig(), use_ollama=False)

    assert router is None


def test_build_llm_router_uses_configured_models_with_ollama_switch() -> None:
    router = build_llm_router(AppConfig(), use_ollama=True)

    assert isinstance(router, LLMRouter)
    request = router.build_request(purpose="reply", prompt="hello")
    assert request.model == "qwen3:8b"
    assert request.think is False

from aituber_partner.app import build_llm_router, build_parser
from aituber_partner.config import AppConfig
from aituber_partner.llm.router import LLMRouter


def test_parser_defaults_to_placeholder_route() -> None:
    args = build_parser().parse_args([])

    assert args.use_ollama is False


def test_parser_accepts_use_ollama_switch() -> None:
    args = build_parser().parse_args(["--use-ollama"])

    assert args.use_ollama is True


def test_build_llm_router_returns_none_without_ollama_switch() -> None:
    router = build_llm_router(AppConfig(), use_ollama=False)

    assert router is None


def test_build_llm_router_uses_configured_models_with_ollama_switch() -> None:
    router = build_llm_router(AppConfig(), use_ollama=True)

    assert isinstance(router, LLMRouter)
    request = router.build_request(purpose="reply", prompt="hello")
    assert request.model == "qwen3:8b"
    assert request.think is False

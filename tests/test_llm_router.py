import pytest

from aituber_partner.config import AppConfig
from aituber_partner.llm.client import LLMRequest, LLMResponse
from aituber_partner.llm.router import LLMRouter


class FakeLLMClient:
    def __init__(self, text: str = "返答です") -> None:
        self.text = text
        self.requests: list[LLMRequest] = []

    async def generate(self, llm_request: LLMRequest) -> LLMResponse:
        self.requests.append(llm_request)
        return LLMResponse(model=llm_request.model, text=self.text)


def test_safety_uses_classifier_model_with_qwen_think_false() -> None:
    router = LLMRouter(config=AppConfig(), client=FakeLLMClient())

    request = router.build_request(purpose="safety", prompt="check")

    assert request.model == "qwen3.5:4b"
    assert request.think is False
    assert request.keep_alive == "30m"


def test_reply_uses_reply_model_not_vision_model_without_images() -> None:
    router = LLMRouter(config=AppConfig(), client=FakeLLMClient())

    request = router.build_request(purpose="reply", prompt="reply")

    assert request.model == "qwen3:8b"
    assert request.model != "qwen3.5:9b"
    assert request.think is False
    assert request.images == []


def test_vision_requires_images_before_using_vision_model() -> None:
    router = LLMRouter(config=AppConfig(), client=FakeLLMClient())

    with pytest.raises(ValueError, match="requires image"):
        router.build_request(purpose="vision", prompt="look")

    request = router.build_request(purpose="vision", prompt="look", images=["base64-image"])

    assert request.model == "qwen3.5:9b"
    assert request.think is False
    assert request.images == ["base64-image"]


def test_review_uses_non_realtime_review_model_without_qwen_think_flag() -> None:
    router = LLMRouter(config=AppConfig(), client=FakeLLMClient())

    request = router.build_request(purpose="review", prompt="review")

    assert request.model == "pakachan/elyza-llama3-8b"
    assert request.think is None


@pytest.mark.asyncio
async def test_generate_strips_thinking_text_from_response() -> None:
    client = FakeLLMClient("<think>内部メモ</think>\nいい感じに拾っていこう！")
    router = LLMRouter(config=AppConfig(), client=client)

    response = await router.generate(purpose="reply", prompt="hello")

    assert response.text == "いい感じに拾っていこう！"
    assert client.requests[0].think is False


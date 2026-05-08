import pytest

from aituber_partner.config import AppConfig
from aituber_partner.llm.client import LLMRequest, LLMResponse
from aituber_partner.llm.router import LLMRouter
from aituber_partner.llm.selection import LLMChatSelector, parse_chat_selection_decision
from aituber_partner.models import InputEvent


class FakeLLMClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[LLMRequest] = []

    async def generate(self, llm_request: LLMRequest) -> LLMResponse:
        self.requests.append(llm_request)
        return LLMResponse(model=llm_request.model, text=self.text, latency_ms=10)


def test_parse_chat_selection_decision_accepts_valid_json() -> None:
    decision = parse_chat_selection_decision(
        '{"selected_index":2,"reason":"音量確認","confidence":0.8}'
    )

    assert decision is not None
    assert decision.selected_index == 2
    assert decision.reason == "音量確認"
    assert decision.confidence == 0.8


def test_parse_chat_selection_decision_fails_closed_on_malformed_json() -> None:
    assert parse_chat_selection_decision("not json") is None


@pytest.mark.asyncio
async def test_llm_chat_selector_selects_one_candidate_with_metadata() -> None:
    client = FakeLLMClient('{"selected_index":2,"reason":"配信状態の確認","confidence":0.86}')
    router = LLMRouter(config=AppConfig(), client=client)
    selector = LLMChatSelector(router, streamer_name="配信者")
    events = [
        InputEvent(source="youtube_chat", text="w", metadata={"selection_score": -1}),
        InputEvent(source="youtube_chat", text="音量大丈夫？", metadata={"selection_score": 9}),
    ]

    selected = await selector.select(events)

    assert [event.text for event in selected] == ["音量大丈夫？"]
    assert selected[0].metadata["llm_selection_model"] == "qwen3.5:4b"
    assert selected[0].metadata["llm_selection_reason"] == "配信状態の確認"
    assert selected[0].metadata["llm_selection_confidence"] == 0.86
    assert selected[0].metadata["llm_selection_candidate_count"] == 2
    assert client.requests[0].purpose == "selection"
    assert client.requests[0].model == "qwen3.5:4b"
    assert client.requests[0].think is False
    assert "streamer 配信者" in client.requests[0].prompt


@pytest.mark.asyncio
async def test_llm_chat_selector_fails_closed_on_malformed_json() -> None:
    client = FakeLLMClient("not json")
    router = LLMRouter(config=AppConfig(), client=client)
    selector = LLMChatSelector(router)
    events = [
        InputEvent(source="youtube_chat", text="音量大丈夫？"),
        InputEvent(source="youtube_chat", text="次なにやる？"),
    ]

    selected = await selector.select(events)

    assert selected == []

import pytest

from aituber_partner.llm.client import LLMRequest, LLMResponse, RecordingLLMClient


class FakeLLMClient:
    def __init__(self, *, response: LLMResponse | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error

    async def generate(self, llm_request: LLMRequest) -> LLMResponse:
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class FakeRecorder:
    def __init__(self) -> None:
        self.calls = []

    def record_llm_call(self, llm_request, *, response=None, error=None) -> None:
        self.calls.append((llm_request, response, error))


@pytest.mark.asyncio
async def test_recording_llm_client_records_success() -> None:
    request = LLMRequest(model="qwen3:8b", purpose="reply", prompt="hello", think=False)
    response = LLMResponse(model="qwen3:8b", text="こんにちは", latency_ms=12)
    recorder = FakeRecorder()
    client = RecordingLLMClient(FakeLLMClient(response=response), recorder=recorder)

    result = await client.generate(request)

    assert result == response
    assert recorder.calls == [(request, response, None)]


@pytest.mark.asyncio
async def test_recording_llm_client_records_failure_before_reraising() -> None:
    request = LLMRequest(model="qwen3:8b", purpose="reply", prompt="hello", think=False)
    recorder = FakeRecorder()
    client = RecordingLLMClient(FakeLLMClient(error=ConnectionError("down")), recorder=recorder)

    with pytest.raises(ConnectionError, match="down"):
        await client.generate(request)

    assert recorder.calls[0][0] == request
    assert recorder.calls[0][1] is None
    assert recorder.calls[0][2] == "down"

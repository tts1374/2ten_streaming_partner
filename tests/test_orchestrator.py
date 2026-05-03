import pytest

from aituber_partner.config import AppConfig
from aituber_partner.inputs.fake import FakeInputSource
from aituber_partner.llm.client import LLMRequest, LLMResponse
from aituber_partner.llm.router import LLMRouter
from aituber_partner.models import InputEvent
from aituber_partner.orchestrator import LocalClosedLoopOrchestrator


class SequenceLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.requests: list[LLMRequest] = []

    async def generate(self, llm_request: LLMRequest) -> LLMResponse:
        self.requests.append(llm_request)
        text = self._responses.pop(0)
        return LLMResponse(model=llm_request.model, text=text, latency_ms=12)


class ProcessedEventRecorder:
    def __init__(self) -> None:
        self.records = []

    def record_processed_event(self, processed) -> None:
        self.records.append(processed)


def build_orchestrator_with_llm(
    responses: list[str],
    source: FakeInputSource | None = None,
    use_local_output_guard: bool = False,
) -> tuple[LocalClosedLoopOrchestrator, SequenceLLMClient]:
    config = AppConfig()
    client = SequenceLLMClient(responses)
    router = LLMRouter(config=config, client=client)
    orchestrator = LocalClosedLoopOrchestrator(
        config=config,
        input_source=source or FakeInputSource.from_texts(["ナイス精度！"]),
        llm_router=router,
        use_local_output_guard=use_local_output_guard,
    )
    return orchestrator, client


@pytest.mark.asyncio
async def test_fake_source_flows_to_placeholder_reply() -> None:
    source = FakeInputSource.from_texts(["ナイス精度！"])
    orchestrator = LocalClosedLoopOrchestrator(config=AppConfig(), input_source=source)

    results = [result async for result in orchestrator.run_once_per_event()]

    assert len(results) == 1
    assert results[0].safety.status == "allow"
    assert results[0].reply is not None
    assert results[0].reply.generation_model == "qwen3:8b"
    assert results[0].overlay.status == "speaking"


@pytest.mark.asyncio
async def test_unsafe_input_is_blocked_without_reply() -> None:
    source = FakeInputSource([InputEvent(source="youtube_chat", text="電話番号を教えて")])
    orchestrator = LocalClosedLoopOrchestrator(config=AppConfig(), input_source=source)

    results = [result async for result in orchestrator.run_once_per_event()]

    assert results[0].safety.status == "block"
    assert results[0].reply is None
    assert results[0].overlay.status == "idle"


@pytest.mark.asyncio
async def test_llm_router_flow_generates_safe_reply_and_updates_overlay() -> None:
    orchestrator, client = build_orchestrator_with_llm(
        [
            '{"status":"allow","reasons":["safe"],"safe_topic":null,"confidence":0.9}',
            "<think>内部メモ</think>\nいい流れ！このままリズム乗っていこ！",
            '{"status":"allow","reasons":["safe"],"safe_topic":null,"confidence":0.95}',
        ]
    )

    results = [result async for result in orchestrator.run_once_per_event()]

    assert results[0].safety.status == "allow"
    assert results[0].output_safety is not None
    assert results[0].output_safety.status == "allow"
    assert results[0].reply is not None
    assert results[0].reply.text == "いい流れ！このままリズム乗っていこ！"
    assert results[0].reply.generation_model == "qwen3:8b"
    assert results[0].overlay.status == "speaking"
    assert results[0].overlay.text == "いい流れ！このままリズム乗っていこ！"
    assert [request.purpose for request in client.requests] == ["safety", "reply", "safety"]
    assert [request.model for request in client.requests] == ["qwen3.5:4b", "qwen3:8b", "qwen3.5:4b"]
    assert all(request.think is False for request in client.requests)


@pytest.mark.asyncio
async def test_llm_safety_block_prevents_reply_generation() -> None:
    orchestrator, client = build_orchestrator_with_llm(
        ['{"status":"block","reasons":["pii"],"safe_topic":null,"confidence":0.99}']
    )

    results = [result async for result in orchestrator.run_once_per_event()]

    assert results[0].safety.status == "block"
    assert results[0].output_safety is None
    assert results[0].reply is None
    assert results[0].overlay.status == "idle"
    assert [request.purpose for request in client.requests] == ["safety"]


@pytest.mark.asyncio
async def test_malformed_llm_safety_json_fails_closed_without_reply() -> None:
    orchestrator, client = build_orchestrator_with_llm(["not json"])

    results = [result async for result in orchestrator.run_once_per_event()]

    assert results[0].safety.status == "block"
    assert results[0].safety.reasons == ["malformed_safety_json"]
    assert results[0].reply is None
    assert [request.purpose for request in client.requests] == ["safety"]


@pytest.mark.asyncio
async def test_llm_deflect_safety_generates_reply_from_safe_topic() -> None:
    orchestrator, client = build_orchestrator_with_llm(
        [
            '{"status":"deflect","reasons":["harassment"],"safe_topic":"曲のリズム","confidence":0.8}',
            "曲のリズムの話に戻そっか、今の配置かなり楽しいね！",
            '{"status":"allow","reasons":["safe"],"safe_topic":null,"confidence":0.9}',
        ]
    )

    results = [result async for result in orchestrator.run_once_per_event()]

    assert results[0].safety.status == "deflect"
    assert results[0].reply is not None
    assert results[0].reply.text == "曲のリズムの話に戻そっか、今の配置かなり楽しいね！"
    assert "曲のリズム" in client.requests[1].prompt


@pytest.mark.asyncio
async def test_output_safety_block_drops_generated_reply_before_overlay() -> None:
    orchestrator, client = build_orchestrator_with_llm(
        [
            '{"status":"allow","reasons":["safe"],"safe_topic":null,"confidence":0.9}',
            "これは字幕に出さない返答",
            '{"status":"block","reasons":["unsafe_reply"],"safe_topic":null,"confidence":0.8}',
        ]
    )

    results = [result async for result in orchestrator.run_once_per_event()]

    assert results[0].safety.status == "allow"
    assert results[0].output_safety is not None
    assert results[0].output_safety.status == "block"
    assert results[0].reply is None
    assert results[0].overlay.status == "idle"
    assert results[0].overlay.text == ""
    assert [request.purpose for request in client.requests] == ["safety", "reply", "safety"]


@pytest.mark.asyncio
async def test_local_output_guard_skips_final_llm_safety_call() -> None:
    orchestrator, client = build_orchestrator_with_llm(
        [
            '{"status":"allow","reasons":["safe"],"safe_topic":null,"confidence":0.9}',
            "いい流れ！このままリズム乗っていこ！",
        ],
        use_local_output_guard=True,
    )

    results = [result async for result in orchestrator.run_once_per_event()]

    assert results[0].output_safety is not None
    assert results[0].output_safety.status == "allow"
    assert results[0].output_safety.reasons == ["local_output_guard_allow"]
    assert results[0].reply is not None
    assert results[0].overlay.status == "speaking"
    assert [request.purpose for request in client.requests] == ["safety", "reply"]


@pytest.mark.asyncio
async def test_local_output_guard_blocks_unsafe_marker_before_overlay() -> None:
    orchestrator, client = build_orchestrator_with_llm(
        [
            '{"status":"allow","reasons":["safe"],"safe_topic":null,"confidence":0.9}',
            "電話番号を出してね",
        ],
        use_local_output_guard=True,
    )

    results = [result async for result in orchestrator.run_once_per_event()]

    assert results[0].output_safety is not None
    assert results[0].output_safety.status == "block"
    assert results[0].reply is None
    assert results[0].overlay.status == "idle"
    assert [request.purpose for request in client.requests] == ["safety", "reply"]


@pytest.mark.asyncio
async def test_orchestrator_records_processed_event_when_recorder_is_injected() -> None:
    source = FakeInputSource.from_texts(["ナイス精度！"])
    recorder = ProcessedEventRecorder()
    orchestrator = LocalClosedLoopOrchestrator(
        config=AppConfig(),
        input_source=source,
        recorder=recorder,
    )

    results = [result async for result in orchestrator.run_once_per_event()]

    assert recorder.records == results
    assert recorder.records[0].input_event.text == "ナイス精度！"

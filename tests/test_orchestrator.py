import asyncio

import pytest

from aituber_partner.config import AppConfig
from aituber_partner.inputs.fake import FakeInputSource
from aituber_partner.inputs.idle_topic import IdleTopicInputSource
from aituber_partner.llm.client import LLMRequest, LLMResponse
from aituber_partner.llm.router import LLMRouter
from aituber_partner.models import GeneratedReply, InputEvent, SpeechJob
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


class OverlayPublisher:
    def __init__(self) -> None:
        self.states = []

    def publish(self, state) -> None:
        self.states.append(state)


class SleepRecorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)


class FakeSpeechSynthesizer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.replies: list[GeneratedReply] = []

    async def synthesize(self, reply: GeneratedReply) -> SpeechJob:
        self.replies.append(reply)
        if self.fail:
            raise ConnectionError("AivisSpeech is not running")
        return SpeechJob(
            reply_id=reply.id,
            text=reply.text,
            voice_id=888753760,
            status="created",
            audio_path="data/audio/test.wav",
            latency_ms=42,
        )


class FakeAudioPlayer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.paths: list[str] = []

    async def play(self, audio_path: str) -> None:
        self.paths.append(audio_path)
        if self.fail:
            raise RuntimeError("audio device unavailable")


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
async def test_idle_topic_event_flows_to_placeholder_reply() -> None:
    source = IdleTopicInputSource(
        FakeInputSource.from_texts(["通常コメント"], delay_seconds=0.02),
        timeout_seconds=0.001,
        topics=["静かな間に、次の譜面の見どころを話す"],
        max_idle_events=1,
    )
    orchestrator = LocalClosedLoopOrchestrator(config=AppConfig(), input_source=source)

    results = []
    async for result in orchestrator.run_once_per_event():
        results.append(result)
        if len(results) == 1:
            break

    assert results[0].input_event.source == "idle_topic"
    assert results[0].safety.status == "allow"
    assert results[0].reply is not None
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


@pytest.mark.asyncio
async def test_orchestrator_publishes_overlay_state_changes() -> None:
    source = FakeInputSource.from_texts(["ナイス精度！"])
    publisher = OverlayPublisher()
    orchestrator = LocalClosedLoopOrchestrator(
        config=AppConfig(),
        input_source=source,
        overlay_publisher=publisher,
    )

    results = [result async for result in orchestrator.run_once_per_event()]

    assert [state.status for state in publisher.states] == ["idle", "thinking", "speaking"]
    assert publisher.states[-1].text == results[0].reply.text


@pytest.mark.asyncio
async def test_orchestrator_clears_overlay_after_configured_speech_delay() -> None:
    source = FakeInputSource.from_texts(["ナイス精度！"])
    publisher = OverlayPublisher()
    sleeper = SleepRecorder()
    orchestrator = LocalClosedLoopOrchestrator(
        config=AppConfig(),
        input_source=source,
        overlay_publisher=publisher,
        sleep=sleeper.sleep,
    )

    results = [result async for result in orchestrator.run_once_per_event()]
    await asyncio.sleep(0)

    assert results[0].overlay.status == "speaking"
    assert sleeper.delays == [2.5]
    assert [state.status for state in publisher.states] == [
        "idle",
        "thinking",
        "speaking",
        "idle",
    ]
    assert publisher.states[-1].text == ""


@pytest.mark.asyncio
async def test_speech_synthesizer_runs_after_safe_reply() -> None:
    source = FakeInputSource.from_texts(["ナイス精度！"])
    speech = FakeSpeechSynthesizer()
    orchestrator = LocalClosedLoopOrchestrator(
        config=AppConfig(),
        input_source=source,
        speech_synthesizer=speech,
    )

    results = [result async for result in orchestrator.run_once_per_event()]

    assert len(speech.replies) == 1
    assert results[0].speech_job is not None
    assert results[0].speech_job.status == "created"
    assert results[0].speech_job.audio_path == "data/audio/test.wav"
    assert results[0].overlay.status == "speaking"
    assert results[0].overlay.text == results[0].reply.text


@pytest.mark.asyncio
async def test_audio_player_runs_after_speech_generation() -> None:
    source = FakeInputSource.from_texts(["ナイス精度！"])
    speech = FakeSpeechSynthesizer()
    player = FakeAudioPlayer()
    orchestrator = LocalClosedLoopOrchestrator(
        config=AppConfig(),
        input_source=source,
        speech_synthesizer=speech,
        audio_player=player,
    )

    results = [result async for result in orchestrator.run_once_per_event()]

    assert player.paths == ["data/audio/test.wav"]
    assert results[0].speech_job is not None
    assert results[0].speech_job.status == "played"
    assert results[0].overlay.status == "speaking"


@pytest.mark.asyncio
async def test_audio_playback_failure_keeps_subtitle_overlay_state() -> None:
    source = FakeInputSource.from_texts(["ナイス精度！"])
    speech = FakeSpeechSynthesizer()
    player = FakeAudioPlayer(fail=True)
    orchestrator = LocalClosedLoopOrchestrator(
        config=AppConfig(),
        input_source=source,
        speech_synthesizer=speech,
        audio_player=player,
    )

    results = [result async for result in orchestrator.run_once_per_event()]

    assert results[0].speech_job is not None
    assert results[0].speech_job.status == "failed"
    assert "audio device unavailable" in (results[0].speech_job.error or "")
    assert results[0].overlay.status == "speaking"
    assert results[0].overlay.text == results[0].reply.text
    assert "Audio playback failed" in (results[0].overlay.detail or "")


@pytest.mark.asyncio
async def test_tts_failure_keeps_subtitle_overlay_state() -> None:
    source = FakeInputSource.from_texts(["ナイス精度！"])
    speech = FakeSpeechSynthesizer(fail=True)
    orchestrator = LocalClosedLoopOrchestrator(
        config=AppConfig(),
        input_source=source,
        speech_synthesizer=speech,
    )

    results = [result async for result in orchestrator.run_once_per_event()]

    assert results[0].speech_job is not None
    assert results[0].speech_job.status == "failed"
    assert "AivisSpeech is not running" in (results[0].speech_job.error or "")
    assert results[0].overlay.status == "speaking"
    assert results[0].overlay.text == results[0].reply.text
    assert "TTS failed" in (results[0].overlay.detail or "")

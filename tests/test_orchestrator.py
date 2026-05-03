import pytest

from aituber_partner.config import AppConfig
from aituber_partner.inputs.fake import FakeInputSource
from aituber_partner.models import InputEvent
from aituber_partner.orchestrator import LocalClosedLoopOrchestrator


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


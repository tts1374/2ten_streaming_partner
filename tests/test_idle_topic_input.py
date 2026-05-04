import pytest

from aituber_partner.inputs.fake import FakeInputSource
from aituber_partner.inputs.idle_topic import IdleTopicInputSource


class FailingInputSource:
    async def events(self):
        raise RuntimeError("upstream failed")
        yield


@pytest.mark.asyncio
async def test_idle_topic_source_emits_topic_after_inactivity() -> None:
    source = IdleTopicInputSource(
        FakeInputSource.from_texts(["通常コメント"], delay_seconds=0.02),
        timeout_seconds=0.001,
        topics=["次の曲の見どころを話す"],
        max_idle_events=1,
    )

    events = []
    async for event in source.events():
        events.append(event)
        if len(events) == 2:
            break

    assert events[0].source == "idle_topic"
    assert events[0].text == "次の曲の見どころを話す"
    assert events[0].metadata["reason"] == "inactivity_timeout"
    assert events[1].source == "youtube_chat"
    assert events[1].text == "通常コメント"


@pytest.mark.asyncio
async def test_idle_topic_source_stops_when_upstream_finishes() -> None:
    source = IdleTopicInputSource(
        FakeInputSource.from_texts(["すぐ来るコメント"]),
        timeout_seconds=0.01,
        topics=["静かな時の話題"],
    )

    events = [event async for event in source.events()]

    assert [event.source for event in events] == ["youtube_chat"]


def test_idle_topic_source_requires_topics() -> None:
    with pytest.raises(ValueError):
        IdleTopicInputSource(
            FakeInputSource.from_texts([]),
            timeout_seconds=0.01,
            topics=[],
        )


@pytest.mark.asyncio
async def test_idle_topic_source_propagates_upstream_errors() -> None:
    source = IdleTopicInputSource(
        FailingInputSource(),
        timeout_seconds=0.01,
        topics=["静かな時の話題"],
    )

    with pytest.raises(RuntimeError, match="upstream failed"):
        _ = [event async for event in source.events()]

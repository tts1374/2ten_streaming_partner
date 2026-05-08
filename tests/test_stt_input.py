from collections.abc import AsyncIterator

import pytest

from aituber_partner.inputs.stt import STTInputSource, TranscriptionResult


class FakeTranscriptProvider:
    def __init__(self, transcripts: list[TranscriptionResult]) -> None:
        self._transcripts = transcripts

    async def transcripts(self) -> AsyncIterator[TranscriptionResult]:
        for transcript in self._transcripts:
            yield transcript


@pytest.mark.asyncio
async def test_stt_input_source_yields_voice_events_with_metadata() -> None:
    source = STTInputSource(
        FakeTranscriptProvider(
            [
                TranscriptionResult(
                    text=" この曲むずいね ",
                    model_name="faster-whisper-small",
                    confidence=0.82,
                    duration_seconds=1.4,
                    metadata={"segment_index": 1},
                )
            ]
        ),
        author="streamer-mic",
    )

    events = [event async for event in source.events()]

    assert len(events) == 1
    assert events[0].source == "voice"
    assert events[0].text == "この曲むずいね"
    assert events[0].author == "streamer-mic"
    assert events[0].metadata["stt_model"] == "faster-whisper-small"
    assert events[0].metadata["stt_language"] == "ja"
    assert events[0].metadata["stt_confidence"] == 0.82
    assert events[0].metadata["stt_duration_seconds"] == 1.4
    assert events[0].metadata["segment_index"] == 1


@pytest.mark.asyncio
async def test_stt_input_source_skips_blank_and_low_confidence_transcripts() -> None:
    source = STTInputSource(
        FakeTranscriptProvider(
            [
                TranscriptionResult(text="   ", model_name="small"),
                TranscriptionResult(text="聞き取れない", model_name="small", confidence=0.2),
                TranscriptionResult(text="次いこう", model_name="small", confidence=0.7),
            ]
        ),
        min_confidence=0.5,
    )

    events = [event async for event in source.events()]

    assert [event.text for event in events] == ["次いこう"]


@pytest.mark.asyncio
async def test_stt_input_source_stops_after_max_events() -> None:
    source = STTInputSource(
        FakeTranscriptProvider(
            [
                TranscriptionResult(text="ひとつめ", model_name="small"),
                TranscriptionResult(text="ふたつめ", model_name="small"),
            ]
        ),
        max_events=1,
    )

    events = [event async for event in source.events()]

    assert [event.text for event in events] == ["ひとつめ"]


def test_stt_input_source_validates_min_confidence() -> None:
    with pytest.raises(ValueError, match="min_confidence"):
        STTInputSource(FakeTranscriptProvider([]), min_confidence=1.1)

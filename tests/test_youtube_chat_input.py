import pytest

from aituber_partner.config import YouTubeChatConfig
from aituber_partner.inputs.youtube_chat import YouTubeChatInputSource


def _message(message_id: str, text: str, author: str = "viewer") -> dict:
    return {
        "id": message_id,
        "snippet": {
            "type": "textMessageEvent",
            "displayMessage": text,
            "publishedAt": "2026-05-04T12:34:56Z",
        },
        "authorDetails": {
            "displayName": author,
            "channelId": f"channel-{author}",
            "isChatOwner": False,
            "isChatModerator": False,
            "isChatSponsor": False,
            "isVerified": False,
        },
    }


@pytest.mark.asyncio
async def test_youtube_chat_source_yields_normalized_events() -> None:
    payloads = [
        {
            "nextPageToken": "page-2",
            "pollingIntervalMillis": 1000,
            "items": [_message("msg-1", "ナイス精度！", "alice")],
            "offlineAt": "2026-05-04T12:35:00Z",
        }
    ]

    source = YouTubeChatInputSource(
        YouTubeChatConfig(live_chat_id="live-chat-1", skip_initial_history=False),
        api_key="api-key",
        fetch_json=lambda _url, _timeout: payloads.pop(0),
    )

    events = [event async for event in source.events()]

    assert len(events) == 1
    assert events[0].source == "youtube_chat"
    assert events[0].text == "ナイス精度！"
    assert events[0].author == "alice"
    assert events[0].metadata["youtube_message_id"] == "msg-1"
    assert events[0].metadata["live_chat_id"] == "live-chat-1"
    assert events[0].metadata["message_type"] == "textMessageEvent"


@pytest.mark.asyncio
async def test_youtube_chat_source_skips_initial_history_and_deduplicates() -> None:
    payloads = [
        {
            "nextPageToken": "page-2",
            "pollingIntervalMillis": 1,
            "items": [_message("old-1", "初回履歴")],
        },
        {
            "nextPageToken": "page-3",
            "pollingIntervalMillis": 1,
            "items": [_message("old-1", "重複"), _message("new-1", "新しいコメント")],
            "offlineAt": "2026-05-04T12:35:00Z",
        },
    ]

    source = YouTubeChatInputSource(
        YouTubeChatConfig(
            live_chat_id="live-chat-1",
            min_poll_interval_seconds=0.001,
            skip_initial_history=True,
        ),
        api_key="api-key",
        fetch_json=lambda _url, _timeout: payloads.pop(0),
    )

    events = [event async for event in source.events()]

    assert [event.text for event in events] == ["新しいコメント"]


def test_youtube_chat_source_requires_live_chat_id() -> None:
    with pytest.raises(ValueError):
        YouTubeChatInputSource(YouTubeChatConfig(), api_key="api-key")

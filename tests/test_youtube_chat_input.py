import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from aituber_partner.config import YouTubeChatConfig
from aituber_partner.inputs import youtube_chat
from aituber_partner.inputs.youtube_chat import YouTubeChatError, YouTubeChatInputSource


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


@pytest.mark.asyncio
async def test_youtube_chat_source_resolves_live_chat_id_from_video_id() -> None:
    requested_urls = []
    payloads = [
        {
            "items": [
                {
                    "liveStreamingDetails": {
                        "activeLiveChatId": "resolved-live-chat-1",
                    }
                }
            ]
        },
        {
            "nextPageToken": "page-2",
            "pollingIntervalMillis": 1000,
            "items": [_message("msg-1", "動画IDから拾えた！")],
            "offlineAt": "2026-05-04T12:35:00Z",
        },
    ]

    def fetch_json(url: str, _timeout: float) -> dict:
        requested_urls.append(url)
        return payloads.pop(0)

    source = YouTubeChatInputSource(
        YouTubeChatConfig(video_id="video-1", skip_initial_history=False),
        api_key="api-key",
        fetch_json=fetch_json,
    )

    events = [event async for event in source.events()]

    videos_query = parse_qs(urlparse(requested_urls[0]).query)
    chat_query = parse_qs(urlparse(requested_urls[1]).query)
    assert videos_query["id"] == ["video-1"]
    assert chat_query["liveChatId"] == ["resolved-live-chat-1"]
    assert events[0].metadata["live_chat_id"] == "resolved-live-chat-1"
    assert events[0].metadata["video_id"] == "video-1"


@pytest.mark.asyncio
async def test_youtube_chat_source_fails_when_video_has_no_active_chat() -> None:
    source = YouTubeChatInputSource(
        YouTubeChatConfig(video_id="video-1"),
        api_key="api-key",
        fetch_json=lambda _url, _timeout: {"items": [{"liveStreamingDetails": {}}]},
    )

    with pytest.raises(YouTubeChatError, match="no active live chat"):
        _ = [event async for event in source.events()]


def test_youtube_chat_http_error_formats_known_reason(monkeypatch) -> None:
    detail = json.dumps(
        {
            "error": {
                "message": "The live chat is no longer live.",
                "errors": [{"reason": "liveChatEnded"}],
            }
        }
    ).encode("utf-8")
    error = HTTPError(
        url="https://example.test",
        code=403,
        msg="Forbidden",
        hdrs={},
        fp=_BytesResponse(detail),
    )

    def raise_http_error(_url: str, timeout: float):
        assert timeout == 10.0
        raise error

    monkeypatch.setattr(youtube_chat, "urlopen", raise_http_error)

    with pytest.raises(YouTubeChatError, match="live chat has ended"):
        YouTubeChatInputSource._fetch_json_with_urllib("https://example.test", 10.0)


def test_youtube_chat_source_requires_live_chat_id() -> None:
    with pytest.raises(ValueError):
        YouTubeChatInputSource(YouTubeChatConfig(), api_key="api-key")


class _BytesResponse:
    def __init__(self, value: bytes) -> None:
        self._value = value

    def read(self) -> bytes:
        return self._value

    def close(self) -> None:
        pass

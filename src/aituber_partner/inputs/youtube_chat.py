"""YouTube Live Chat input source."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from aituber_partner.config import YouTubeChatConfig
from aituber_partner.models import InputEvent


FetchJson = Callable[[str, float], dict[str, Any]]


class YouTubeChatError(RuntimeError):
    """Raised when YouTube Live Chat polling cannot continue."""


class YouTubeChatInputSource:
    """Poll YouTube Live Chat and yield new chat messages as InputEvent objects."""

    _BASE_URL = "https://www.googleapis.com/youtube/v3/liveChat/messages"

    def __init__(
        self,
        config: YouTubeChatConfig,
        *,
        api_key: str,
        fetch_json: FetchJson | None = None,
        max_pages: int | None = None,
        seen_cache_size: int = 4096,
    ) -> None:
        if not config.live_chat_id:
            raise ValueError("youtube_chat.live_chat_id is required for YouTube chat input.")
        if not api_key:
            raise ValueError("YouTube API key is required for YouTube chat input.")
        if seen_cache_size <= 0:
            raise ValueError("seen_cache_size must be greater than 0.")

        self._config = config
        self._api_key = api_key
        self._fetch_json = fetch_json or self._fetch_json_with_urllib
        self._max_pages = max_pages
        self._seen_ids: deque[str] = deque(maxlen=seen_cache_size)
        self._seen_lookup: set[str] = set()

    async def events(self) -> AsyncIterator[InputEvent]:
        page_token: str | None = None
        page_count = 0

        while self._max_pages is None or page_count < self._max_pages:
            payload = await asyncio.to_thread(
                self._fetch_json,
                self._build_url(page_token),
                self._config.request_timeout_seconds,
            )
            page_count += 1
            page_token = payload.get("nextPageToken") or page_token
            messages = list(self._iter_message_events(payload))

            if not (self._config.skip_initial_history and page_count == 1):
                for event in messages:
                    yield event

            if payload.get("offlineAt"):
                return

            if self._max_pages is not None and page_count >= self._max_pages:
                return

            await asyncio.sleep(self._next_poll_delay(payload))

    def _build_url(self, page_token: str | None) -> str:
        params = {
            "part": "id,snippet,authorDetails",
            "liveChatId": self._config.live_chat_id,
            "key": self._api_key,
            "maxResults": str(self._config.max_results),
        }
        if page_token:
            params["pageToken"] = page_token
        return f"{self._BASE_URL}?{urlencode(params)}"

    def _iter_message_events(self, payload: dict[str, Any]) -> Iterator[InputEvent]:
        for item in payload.get("items", []):
            event = self._build_event(item)
            if event is not None:
                yield event

    def _build_event(self, item: dict[str, Any]) -> InputEvent | None:
        message_id = item.get("id")
        if not isinstance(message_id, str) or self._is_seen(message_id):
            return None

        snippet = item.get("snippet") or {}
        author_details = item.get("authorDetails") or {}
        text = snippet.get("displayMessage")
        if not isinstance(text, str) or not text.strip():
            self._remember(message_id)
            return None

        self._remember(message_id)
        return InputEvent(
            source="youtube_chat",
            text=text.strip(),
            author=author_details.get("displayName"),
            timestamp=_parse_youtube_timestamp(snippet.get("publishedAt")),
            metadata={
                "youtube_message_id": message_id,
                "live_chat_id": self._config.live_chat_id,
                "message_type": snippet.get("type"),
                "author_channel_id": author_details.get("channelId"),
                "is_chat_owner": author_details.get("isChatOwner"),
                "is_chat_moderator": author_details.get("isChatModerator"),
                "is_chat_sponsor": author_details.get("isChatSponsor"),
                "is_verified": author_details.get("isVerified"),
            },
        )

    def _is_seen(self, message_id: str) -> bool:
        return message_id in self._seen_lookup

    def _remember(self, message_id: str) -> None:
        if len(self._seen_ids) == self._seen_ids.maxlen:
            evicted = self._seen_ids.popleft()
            self._seen_lookup.discard(evicted)
        self._seen_ids.append(message_id)
        self._seen_lookup.add(message_id)

    def _next_poll_delay(self, payload: dict[str, Any]) -> float:
        interval_ms = payload.get("pollingIntervalMillis")
        if isinstance(interval_ms, (int, float)) and interval_ms > 0:
            delay = interval_ms / 1000.0
        else:
            delay = self._config.poll_interval_seconds
        return max(delay, self._config.min_poll_interval_seconds)

    @staticmethod
    def _fetch_json_with_urllib(url: str, timeout_seconds: float) -> dict[str, Any]:
        try:
            with urlopen(url, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise YouTubeChatError(f"YouTube chat API returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise YouTubeChatError(f"YouTube chat API request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise YouTubeChatError("YouTube chat API returned malformed JSON.") from exc


def _parse_youtube_timestamp(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(tz=UTC)

"""YouTube Live Chat input source."""

from __future__ import annotations

import asyncio
import json
import unicodedata
from collections import deque
from collections.abc import Awaitable, AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from aituber_partner.config import YouTubeChatConfig
from aituber_partner.models import InputEvent


FetchJson = Callable[[str, float], dict[str, Any]]
ChatCandidateSelector = Callable[[list[InputEvent]], Awaitable[list[InputEvent]]]


class YouTubeChatError(RuntimeError):
    """Raised when YouTube Live Chat polling cannot continue."""


class YouTubeChatInputSource:
    """Poll YouTube Live Chat and yield new chat messages as InputEvent objects."""

    _CHAT_MESSAGES_URL = "https://www.googleapis.com/youtube/v3/liveChat/messages"
    _VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

    def __init__(
        self,
        config: YouTubeChatConfig,
        *,
        api_key: str,
        fetch_json: FetchJson | None = None,
        candidate_selector: ChatCandidateSelector | None = None,
        max_pages: int | None = None,
        seen_cache_size: int = 4096,
    ) -> None:
        if not config.live_chat_id and not config.video_id:
            raise ValueError(
                "youtube_chat.live_chat_id or youtube_chat.video_id is required for YouTube chat input."
            )
        if not api_key:
            raise ValueError("YouTube API key is required for YouTube chat input.")
        if seen_cache_size <= 0:
            raise ValueError("seen_cache_size must be greater than 0.")

        self._config = config
        self._api_key = api_key
        self._fetch_json = fetch_json or self._fetch_json_with_urllib
        self._candidate_selector = candidate_selector
        self._max_pages = max_pages
        self._live_chat_id = config.live_chat_id
        self._seen_ids: deque[str] = deque(maxlen=seen_cache_size)
        self._seen_lookup: set[str] = set()
        self._recent_text_seen_at: dict[str, datetime] = {}

    async def events(self) -> AsyncIterator[InputEvent]:
        live_chat_id = await self._resolve_live_chat_id()
        page_token: str | None = None
        page_count = 0

        while self._max_pages is None or page_count < self._max_pages:
            payload = await asyncio.to_thread(
                self._fetch_json,
                self._build_chat_messages_url(live_chat_id, page_token),
                self._config.request_timeout_seconds,
            )
            page_count += 1
            page_token = payload.get("nextPageToken") or page_token
            messages = list(self._iter_message_events(payload))
            filtered_messages = self._filter_message_events(messages)
            selected_messages = self._select_message_events(filtered_messages)
            should_yield_messages = not (self._config.skip_initial_history and page_count == 1)
            if should_yield_messages and self._candidate_selector is not None:
                selected_messages = await self._candidate_selector(selected_messages)

            if should_yield_messages:
                for event in selected_messages:
                    yield event

            if payload.get("offlineAt"):
                return

            if self._max_pages is not None and page_count >= self._max_pages:
                return

            await asyncio.sleep(self._next_poll_delay(payload))

    async def _resolve_live_chat_id(self) -> str:
        if self._live_chat_id:
            return self._live_chat_id

        if not self._config.video_id:
            raise YouTubeChatError("YouTube video ID is missing, so live chat ID cannot be resolved.")

        payload = await asyncio.to_thread(
            self._fetch_json,
            self._build_videos_url(self._config.video_id),
            self._config.request_timeout_seconds,
        )
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            raise YouTubeChatError(
                "YouTube video was not found. Check youtube_chat.video_id and API key access."
            )

        details = items[0].get("liveStreamingDetails") if isinstance(items[0], dict) else None
        live_chat_id = details.get("activeLiveChatId") if isinstance(details, dict) else None
        if not isinstance(live_chat_id, str) or not live_chat_id:
            raise YouTubeChatError(
                "YouTube video has no active live chat. The stream may be offline, ended, or chat may be disabled."
            )

        self._live_chat_id = live_chat_id
        return live_chat_id

    def _build_chat_messages_url(self, live_chat_id: str, page_token: str | None) -> str:
        params = {
            "part": "id,snippet,authorDetails",
            "liveChatId": live_chat_id,
            "key": self._api_key,
            "maxResults": str(self._config.max_results),
        }
        if page_token:
            params["pageToken"] = page_token
        return f"{self._CHAT_MESSAGES_URL}?{urlencode(params)}"

    def _build_videos_url(self, video_id: str) -> str:
        params = {
            "part": "liveStreamingDetails",
            "id": video_id,
            "key": self._api_key,
        }
        return f"{self._VIDEOS_URL}?{urlencode(params)}"

    def _iter_message_events(self, payload: dict[str, Any]) -> Iterator[InputEvent]:
        for item in payload.get("items", []):
            event = self._build_event(item)
            if event is not None:
                yield event

    def _filter_message_events(self, events: list[InputEvent]) -> list[InputEvent]:
        filtered_events: list[InputEvent] = []
        seen_texts: set[str] = set()

        for event in events:
            normalized_text = _normalize_chat_text(event.text)
            if len(event.text) > self._config.max_message_length:
                continue
            if self._is_recent_duplicate_text(normalized_text, event.timestamp):
                continue
            if (
                self._config.drop_duplicate_text_per_poll
                and normalized_text
                and normalized_text in seen_texts
            ):
                continue
            if (
                self._config.drop_symbol_heavy_messages
                and _symbol_ratio(event.text) >= self._config.symbol_heavy_threshold
            ):
                continue
            if (
                self._config.drop_repetitive_messages
                and _is_repetitive_text(
                    normalized_text,
                    threshold=self._config.repetitive_text_threshold,
                    min_length=self._config.repetitive_text_min_length,
                )
            ):
                continue

            if normalized_text:
                seen_texts.add(normalized_text)
                self._remember_recent_text(normalized_text, event.timestamp)
            filtered_events.append(event)

        return filtered_events

    def _is_recent_duplicate_text(self, normalized_text: str, timestamp: datetime) -> bool:
        if (
            not self._config.drop_duplicate_text_per_poll
            or not normalized_text
            or self._config.recent_duplicate_text_window_seconds <= 0
        ):
            return False

        self._prune_recent_texts(timestamp)
        seen_at = self._recent_text_seen_at.get(normalized_text)
        if seen_at is None:
            return False
        return (timestamp - seen_at).total_seconds() <= self._config.recent_duplicate_text_window_seconds

    def _remember_recent_text(self, normalized_text: str, timestamp: datetime) -> None:
        if (
            self._config.drop_duplicate_text_per_poll
            and normalized_text
            and self._config.recent_duplicate_text_window_seconds > 0
        ):
            self._recent_text_seen_at[normalized_text] = timestamp

    def _prune_recent_texts(self, timestamp: datetime) -> None:
        cutoff = timestamp - timedelta(seconds=self._config.recent_duplicate_text_window_seconds)
        expired_texts = [
            text for text, seen_at in self._recent_text_seen_at.items() if seen_at < cutoff
        ]
        for text in expired_texts:
            self._recent_text_seen_at.pop(text, None)

    def _select_message_events(self, events: list[InputEvent]) -> list[InputEvent]:
        if len(events) <= self._config.max_selected_per_poll:
            return [
                event.model_copy(
                    update={
                        "metadata": {
                            **event.metadata,
                            "selection_rank": index + 1,
                            "selection_score": _score_chat_event(event),
                            "selection_dropped_count": 0,
                        }
                    }
                )
                for index, event in enumerate(events)
            ]

        scored_events = [
            (_score_chat_event(event), index, event) for index, event in enumerate(events)
        ]
        selected = sorted(scored_events, key=lambda item: (-item[0], item[1]))[
            : self._config.max_selected_per_poll
        ]
        dropped_count = len(events) - len(selected)
        return [
            event.model_copy(
                update={
                    "metadata": {
                        **event.metadata,
                        "selection_rank": rank,
                        "selection_score": score,
                        "selection_dropped_count": dropped_count,
                    }
                }
            )
            for rank, (score, _index, event) in enumerate(selected, start=1)
        ]

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
                "live_chat_id": self._live_chat_id,
                "video_id": self._config.video_id,
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
            raise YouTubeChatError(_format_youtube_http_error(exc.code, detail)) from exc
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


def _score_chat_event(event: InputEvent) -> int:
    text = event.text.strip()
    metadata = event.metadata
    score = 0

    if metadata.get("is_chat_owner"):
        score += 8
    if metadata.get("is_chat_moderator"):
        score += 5
    if metadata.get("is_verified"):
        score += 3
    if metadata.get("is_chat_sponsor"):
        score += 2
    if any(marker in text for marker in ("?", "？", "どう", "なに", "何", "教えて")):
        score += 4
    if any(marker in text for marker in ("音量", "聞こえ", "見え", "映像", "遅延", "ラグ")):
        score += 3
    if 4 <= len(text) <= 80:
        score += 2
    if len(text) <= 2:
        score -= 3
    return score


def _normalize_chat_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text.casefold())
    return "".join(
        char
        for char in normalized
        if not char.isspace() and not unicodedata.category(char).startswith("C")
    )


def _symbol_ratio(text: str) -> float:
    visible_chars = [char for char in text if not char.isspace()]
    if not visible_chars:
        return 1.0
    symbol_count = sum(1 for char in visible_chars if not char.isalnum())
    return symbol_count / len(visible_chars)


def _is_repetitive_text(text: str, *, threshold: float, min_length: int) -> bool:
    if len(text) < min_length:
        return False
    most_common_count = max(text.count(char) for char in set(text))
    return most_common_count / len(text) >= threshold


def _format_youtube_http_error(status_code: int, detail: str) -> str:
    reason, message = _extract_youtube_error(detail)
    reason_help = {
        "pageTokenInvalid": (
            "YouTube chat page token expired or became invalid. Restart the input source to resume polling."
        ),
        "liveChatEnded": "YouTube live chat has ended. Stop the run or switch to another active stream.",
        "liveChatDisabled": "YouTube live chat is disabled for this video. Enable chat or choose another stream.",
        "liveChatNotFound": "YouTube live chat was not found. Check live_chat_id or use video_id resolution.",
        "forbidden": "YouTube API access was forbidden. Check API key permissions and quota.",
        "quotaExceeded": "YouTube API quota was exceeded. Wait for quota reset or use another API project.",
        "keyInvalid": "YouTube API key is invalid. Check the configured api_key_env value.",
    }.get(reason)

    parts = [f"YouTube chat API returned HTTP {status_code}"]
    if reason:
        parts.append(f"reason={reason}")
    if reason_help:
        parts.append(reason_help)
    elif message:
        parts.append(message)
    else:
        parts.append(detail)
    return ": ".join(parts)


def _extract_youtube_error(detail: str) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return None, None

    error = payload.get("error")
    if not isinstance(error, dict):
        return None, None

    message = error.get("message") if isinstance(error.get("message"), str) else None
    errors = error.get("errors")
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict) and isinstance(item.get("reason"), str):
                return item["reason"], message

    status = error.get("status")
    return status if isinstance(status, str) else None, message

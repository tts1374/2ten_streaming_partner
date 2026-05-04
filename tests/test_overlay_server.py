import urllib.request

from aituber_partner.config import OverlayConfig
from aituber_partner.models import OverlayState
from aituber_partner.overlay.server import (
    OverlayServerRunner,
    OverlayStateBroadcaster,
    _format_sse_state,
)


def test_broadcaster_replays_current_state_to_new_subscriber() -> None:
    broadcaster = OverlayStateBroadcaster()
    state = OverlayState(status="speaking", text="いい流れ！")

    broadcaster.publish(state)
    client = broadcaster.subscribe()

    assert client.get(timeout=1) == state
    broadcaster.unsubscribe(client)


def test_sse_state_format_uses_overlay_state_event() -> None:
    state = OverlayState(status="speaking", text="いい流れ！")

    payload = _format_sse_state(state)

    assert payload.startswith("event: overlay_state\n")
    assert '"status":"speaking"' in payload
    assert '"text":"いい流れ！"' in payload
    assert payload.endswith("\n\n")


def test_overlay_server_serves_index_html() -> None:
    broadcaster = OverlayStateBroadcaster()
    with OverlayServerRunner(OverlayConfig(port=0), broadcaster) as runner:
        with urllib.request.urlopen(runner.url, timeout=2) as response:
            body = response.read().decode("utf-8")

    assert response.status == 200
    assert "EventSource(\"/events\")" in body
    assert "subtitle" in body

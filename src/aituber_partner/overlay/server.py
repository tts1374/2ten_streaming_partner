"""Small SSE overlay server for OBS browser sources."""

from __future__ import annotations

import queue
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from aituber_partner.config import OverlayConfig
from aituber_partner.models import OverlayState

_CLIENT_DONE = object()


class OverlayStateBroadcaster:
    """Fan out the latest overlay state to SSE clients."""

    def __init__(self, initial_state: OverlayState | None = None) -> None:
        self._state = initial_state or OverlayState()
        self._clients: set[queue.Queue[OverlayState | object]] = set()
        self._lock = threading.Lock()

    @property
    def current_state(self) -> OverlayState:
        with self._lock:
            return self._state

    def publish(self, state: OverlayState) -> None:
        with self._lock:
            self._state = state
            clients = list(self._clients)
        for client in clients:
            client.put(state)

    def subscribe(self) -> queue.Queue[OverlayState | object]:
        client: queue.Queue[OverlayState | object] = queue.Queue()
        with self._lock:
            self._clients.add(client)
            client.put(self._state)
        return client

    def unsubscribe(self, client: queue.Queue[OverlayState | object]) -> None:
        with self._lock:
            self._clients.discard(client)
        client.put(_CLIENT_DONE)


class OverlayHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        broadcaster: OverlayStateBroadcaster,
        static_root: Path,
    ) -> None:
        super().__init__(server_address, OverlayRequestHandler)
        self.broadcaster = broadcaster
        self.static_root = static_root


class OverlayRequestHandler(BaseHTTPRequestHandler):
    server: OverlayHTTPServer

    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            self._send_index()
            return
        if self.path == "/events":
            self._send_events()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_index(self) -> None:
        index_path = self.server.static_root / "index.html"
        try:
            body = index_path.read_bytes()
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND, "overlay/index.html not found")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_events(self) -> None:
        client = self.server.broadcaster.subscribe()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                try:
                    item = client.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    continue
                if item is _CLIENT_DONE:
                    return
                self.wfile.write(_format_sse_state(item).encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        finally:
            self.server.broadcaster.unsubscribe(client)


class OverlayServerRunner:
    """Run the overlay server on a background thread."""

    def __init__(
        self,
        config: OverlayConfig,
        broadcaster: OverlayStateBroadcaster | None = None,
        static_root: Path | None = None,
    ) -> None:
        self.broadcaster = broadcaster or OverlayStateBroadcaster()
        self.static_root = static_root or _default_static_root()
        self.server = OverlayHTTPServer(
            (config.host, config.port),
            self.broadcaster,
            self.static_root,
        )
        self.url = f"http://{config.host}:{self.server.server_port}/"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=2)

    def __enter__(self) -> OverlayServerRunner:
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()


def _format_sse_state(state: OverlayState) -> str:
    return f"event: overlay_state\ndata: {state.model_dump_json()}\n\n"


def _default_static_root() -> Path:
    return Path(__file__).resolve().parents[3] / "overlay"

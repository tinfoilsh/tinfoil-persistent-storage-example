"""Tiny HTTP server exposing /health and /status.

Sim updates a shared dict via update(); the handler reads it under a lock.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

_state = {
    "run_id": None,
    "step": 0,
    "phase": None,
    "phase_index": -1,
    "checkpoints_written": 0,
    "done": False,
}
_lock = threading.Lock()


def update(**kwargs) -> None:
    with _lock:
        _state.update(kwargs)


def snapshot() -> dict:
    with _lock:
        return dict(_state)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self._json({"ok": True})
        elif self.path == "/status":
            self._json(snapshot())
        else:
            self.send_error(404)

    def log_message(self, format, *args):  # noqa: A002 — name dictated by parent class
        return

    def _json(self, payload, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_in_thread(port: int) -> None:
    httpd = HTTPServer(("0.0.0.0", port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

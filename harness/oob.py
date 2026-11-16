"""Out-of-band canary receiver.

The signature capability: prove that data left the target, without trusting the
target's own logs and without needing access to its infrastructure. The payload makes
the agent call a tool with an attacker-controlled URL; this server is that URL, and it
records what actually arrived.

Runs in-process on 127.0.0.1 by default. For a real engagement you point it at a
public host you control (or a Burp Collaborator-style service) - the code is the same,
only the address changes.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class CanaryHit:
    method: str
    path: str
    headers: dict[str, str]
    body: str
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"method": self.method, "path": self.path,
                "headers": self.headers, "body": self.body, "at": self.at}


class _Handler(BaseHTTPRequestHandler):
    server_version = "canary/1.0"

    def _record(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        hits: list[CanaryHit] = self.server.hits  # type: ignore[attr-defined]
        hits.append(CanaryHit(self.command, self.path, dict(self.headers), body))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    do_GET = _record
    do_POST = _record
    do_PUT = _record

    def log_message(self, *args: object) -> None:  # keep the run output clean
        pass


class CanaryServer:
    """Context manager: start a listener, collect hits, stop it."""

    def __init__(self, port: int = 8899) -> None:
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.hits: list[CanaryHit] = []

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/collect"

    def __enter__(self) -> "CanaryServer":
        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        self._httpd.hits = self.hits  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=2)

    def wait(self, seconds: float = 1.0) -> None:
        """Give an in-flight tool call a moment to arrive."""
        time.sleep(seconds)

    def summary(self) -> str:
        if not self.hits:
            return "no callbacks received"
        return json.dumps([h.to_dict() for h in self.hits], ensure_ascii=False)[:1500]

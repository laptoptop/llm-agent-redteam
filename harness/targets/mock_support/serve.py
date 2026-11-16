"""Serve the mock support agent over an OpenAI-compatible endpoint.

Why: to compare tools fairly, both the scanner and this harness must hit the SAME
target. HackMyAgent speaks OpenAI chat-completions; the harness drives the agent
in-process. This wrapper exposes the identical agent over HTTP so a scanner can be
pointed at it.

  python3 serve.py --port 8811

Then:
  hackmyagent attack http://127.0.0.1:8811/v1/chat/completions --api-format openai
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HARNESS_DIR = os.path.dirname(  # harness/ (three levels up from this file)
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _HARNESS_DIR)

from target import MockSupportTarget, TargetConfig  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    target = None  # set in main()
    server_version = "mock-support/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("/health", "/v1/models"):
            self._json({"status": "ok",
                        "data": [{"id": "mock-support", "object": "model"}]})
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages") or []
        prompt = messages[-1].get("content", "") if messages else ""

        started = time.time()
        trace = self.target.run("http", prompt)
        content = trace.final_answer or (trace.error or "")

        # Tool calls are surfaced in a non-standard field so a scanner ignores them:
        # the point of the comparison is what a text-only scanner can and cannot see.
        self._json({
            "id": f"chatcmpl-{int(started)}",
            "object": "chat.completion",
            "created": int(started),
            "model": "mock-support",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "tool_trace": [c.to_dict() for c in trace.tool_calls],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    def _json(self, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args: object) -> None:
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8811)
    ap.add_argument("--model", default=os.getenv("MODEL", "openai/gemma4-12b-local"))
    ap.add_argument("--api-base", default=os.getenv("OPENAI_API_BASE",
                                                    "http://localhost:8081/v1"))
    args = ap.parse_args()

    Handler.target = MockSupportTarget(TargetConfig(
        model=args.model, api_base=args.api_base, max_tokens=1200))
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"mock agent on http://127.0.0.1:{args.port}/v1/chat/completions", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()

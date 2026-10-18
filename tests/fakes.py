"""A local stand-in for the Anthropic Messages API: the shape of the documented endpoint, nothing else."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeAnthropic:
    def __init__(self, reply: str = "", statuses: list[int] | None = None) -> None:
        self.reply = reply
        self.statuses = list(statuses or [])  # one status per request, then 200
        self.requests: list[dict] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # noqa: ANN002
                pass

            def do_POST(self) -> None:  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                owner.requests.append(
                    {
                        "path": self.path,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "body": body,
                    }
                )
                status = owner.statuses.pop(0) if owner.statuses else 200
                if status != 200:
                    data = json.dumps(
                        {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
                    ).encode()
                else:
                    data = json.dumps(
                        {
                            "id": "msg_test",
                            "type": "message",
                            "role": "assistant",
                            "model": "fake",
                            "content": [{"type": "text", "text": owner.reply}],
                            "stop_reason": "end_turn",
                        }
                    ).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(
            target=lambda: self.httpd.serve_forever(poll_interval=0.01), daemon=True
        )
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def last_json(self) -> dict:
        return json.loads(self.requests[-1]["body"])

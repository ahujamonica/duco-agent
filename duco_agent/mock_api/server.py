"""A dependency-free HTTP server for the two mock insurer APIs.

Run it with::

    python -m duco_agent.mock_api.server --port 8765

It uses only the Python standard library so the assessment demo runs on any
machine without extra services.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .service import HANDLERS


class InsurerAPIHandler(BaseHTTPRequestHandler):
    server_version = "DuCOMockInsurer/1.0"

    def _respond(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        if route not in {"/plans", "/eligibility", "/benefits", "/claim/status"}:
            self._respond({"error": f"unknown route {route}"}, status=404)
            return
        handler_name = {
            "/plans": "plans",
            "/eligibility": "eligibility",
            "/benefits": "benefits",
            "/claim/status": "claim_status",
        }[route]
        try:
            self._respond(HANDLERS[handler_name](**query))
        except TypeError as exc:
            self._respond({"error": f"bad request: {exc}"}, status=400)

    def do_POST(self) -> None:  # noqa: N802 (stdlib naming)
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._respond({"error": "invalid JSON body"}, status=400)
            return
        if route == "/preauth":
            self._respond(
                HANDLERS["preauth"](
                    plan_id=payload.get("plan_id"),
                    member_id=payload.get("member_id"),
                    claim_id=payload.get("claim_id"),
                    payload=payload,
                )
            )
        elif route == "/claim":
            self._respond(HANDLERS["claim"](payload=payload))
        else:
            self._respond({"error": f"unknown route {route}"}, status=404)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        print(f"[mock-insurer] {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock insurer API server")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), InsurerAPIHandler)
    print(f"Mock insurer API listening on http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

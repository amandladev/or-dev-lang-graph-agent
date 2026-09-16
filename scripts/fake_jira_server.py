#!/usr/bin/env python3
"""Local Jira REST API simulator for Autopilot E2E tests.

Serves a user story from a JSON file using the same endpoints the real
JiraTool consumes, so the full tool code path (HTTP, Basic auth, JSON
parsing, ADF/text extraction) is exercised without a real Jira instance.

Endpoints:
    GET  /rest/api/3/issue/{key}          -> the story (get_ticket)
    GET  /rest/api/2/issue/{key}/transitions
    POST /rest/api/2/issue/{key}/transitions
    POST /rest/api/2/issue/{key}/comment

Usage:
    fake_jira_server.py --story story.json [--port 0] [--log interactions.jsonl]
"""

import argparse
import base64
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

TRANSITIONS = [
    {"id": "11", "name": "In Progress"},
    {"id": "21", "name": "Code Review"},
    {"id": "31", "name": "Done"},
]


def load_story(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "fields" not in data:
        sys.exit(f"story file must contain Jira issue JSON with 'fields': {path}")
    return data


def make_handler(story: dict, log_path: Path | None):
    story_key = story.get("key", "").upper()

    class Handler(BaseHTTPRequestHandler):
        def _log(self, method: str, path: str, body: dict | None = None) -> None:
            record = {"method": method, "path": path, "body": body}
            line = json.dumps(record)
            print(line, file=sys.stderr, flush=True)
            if log_path:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")

        def _send(self, code: int, payload: dict | None = None) -> None:
            data = json.dumps(payload).encode() if payload is not None else b""
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            if not length:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _auth_ok(self) -> bool:
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Basic "):
                return False
            try:
                base64.b64decode(auth[len("Basic "):])
                return True
            except Exception:
                return False

        def _route(self) -> tuple[str, dict]:
            parsed = urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]
            if (
                len(parts) < 5
                or parts[0] != "rest"
                or parts[1] != "api"
                or parts[3] != "issue"
            ):
                return "not_found", {}
            version = parts[2]
            key = parts[4].upper()
            sub = parts[5] if len(parts) > 5 else ""

            if version == "3" and not sub:
                return ("get_ticket", {"key": key})
            if sub == "transitions":
                return ("transitions", {"key": key})
            if sub == "comment":
                return ("comment", {"key": key})
            return "not_found", {}

        def _handle(self) -> None:
            if not self._auth_ok():
                self._send(401, {"errorMessages": ["Basic auth required"]})
                return
            route, ctx = self._route()
            key = ctx.get("key", "")
            if route == "not_found":
                self._send(404, {"errorMessages": ["Not found"]})
                return
            if route == "get_ticket":
                if key != story_key:
                    self._send(404, {"errorMessages": [f"Ticket not found: {key}"]})
                    return
                self._log("GET", self.path)
                self._send(200, story)
                return
            if route == "transitions":
                if self.command == "GET":
                    self._log("GET", self.path)
                    self._send(200, {"transitions": TRANSITIONS})
                    return
                if self.command == "POST":
                    self._log("POST", self.path, self._read_body())
                    self._send(204)
                    return
            if route == "comment" and self.command == "POST":
                self._log("POST", self.path, self._read_body())
                self._send(201, {"id": "10000", "created": {"displayName": "Autopilot"}})
                return
            self._send(405, {"errorMessages": ["Method not allowed"]})

        do_GET = _handle
        do_POST = _handle
        do_PUT = _handle

        def log_message(self, format, *args) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--story", required=True, type=Path, help="Story JSON file")
    parser.add_argument("--port", type=int, default=0, help="Port (0 = free port)")
    parser.add_argument("--log", type=Path, default=None, help="JSONL interaction log")
    args = parser.parse_args()

    story = load_story(args.story)
    handler = make_handler(story, args.log)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    port = server.server_address[1]
    print(f"FAKE_JIRA_PORT={port}", flush=True)
    print(f"FAKE_JIRA_URL=http://127.0.0.1:{port}", flush=True)
    print(f"serving story {story.get('key', '?')} on http://127.0.0.1:{port}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
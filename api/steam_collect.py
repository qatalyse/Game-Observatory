"""Vercel function: authenticated, manual Steam player-count diagnostics."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import secrets
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collector"))
from game_observatory.steam import collect, validate_app_ids  # noqa: E402

MAX_REQUEST_BYTES = 2048
PATHS = ("/api/dev/steam-collect", "/api/steam_collect", "/api/steam_collect.py")


class handler(BaseHTTPRequestHandler):
    def respond(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if status == 405:
            self.send_header("Allow", "POST")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.respond(405, {"error": "Use POST with X-Dev-Token to run a manual diagnostic"})

    def do_POST(self):
        if self.path.split("?")[0] not in PATHS:
            return self.respond(404, {"error": "Not found"})
        expected = os.getenv("DEV_COLLECT_TOKEN", "")
        supplied = self.headers.get("X-Dev-Token", "")
        if not expected:
            return self.respond(503, {"error": "Dev collection is disabled. Set DEV_COLLECT_TOKEN in Vercel and redeploy."})
        if not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
            return self.respond(401, {"error": "Invalid dev token"})
        try:
            if self.headers.get("Transfer-Encoding"):
                return self.respond(400, {"error": "Transfer-Encoding is not supported"})
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0:
                raise ValueError("Negative body length")
            if length > MAX_REQUEST_BYTES:
                return self.respond(413, {"error": "Diagnostic request too large"})
            raw = self.rfile.read(length)
            options = json.loads(raw.decode("utf-8"))
            if not isinstance(options, dict) or set(options) != {"app_ids"}:
                raise ValueError("Expected an object containing only app_ids")
            selected = validate_app_ids(options["app_ids"])
        except (ValueError, UnicodeDecodeError):
            return self.respond(400, {"error": "Send app_ids as a non-empty list of unique configured Steam App ID strings (maximum nine)."})
        try:
            result = collect(selected)
        except Exception:
            traceback.print_exc()
            return self.respond(502, {"error": "Steam diagnostic failed"})
        # Per-app failures stay in the results, including when no app has data.
        self.respond(200, result)

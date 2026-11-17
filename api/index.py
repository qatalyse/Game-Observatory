"""Vercel function: token-protected one-feed Apple legacy RSS diagnostic."""
from __future__ import annotations

import json
import os
import secrets
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collector"))
from game_observatory.apple import collect, CHARTS, GENRES  # noqa: E402

COMPACT_FIELDS = (
    "position", "position_semantics", "app_id", "title", "developer",
    "release_date", "store_url", "artwork_url", "price_amount",
    "price_currency", "category_id", "category_label",
)


class handler(BaseHTTPRequestHandler):
    def respond(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?")[0] not in ("/api/dev/apple-collect", "/api/index.py"):
            return self.respond(404, {"error": "Not found"})
        self.respond(200, {
            "status": "function_ready",
            "token_configured": bool(os.getenv("DEV_COLLECT_TOKEN")),
            "feed_types": list(CHARTS),
            "genres": list(GENRES),
        })

    def do_POST(self):
        if self.path.split("?")[0] not in ("/api/dev/apple-collect", "/api/index.py"):
            return self.respond(404, {"error": "Not found"})
        expected = os.getenv("DEV_COLLECT_TOKEN", "")
        supplied = self.headers.get("X-Dev-Token", "")
        if not expected:
            return self.respond(503, {"error": "Dev collection is disabled. Set DEV_COLLECT_TOKEN in Vercel environment variables."})
        if not secrets.compare_digest(supplied, expected):
            return self.respond(401, {"error": "Invalid dev token"})

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1024:
                return self.respond(413, {"error": "Diagnostic request too large"})
            request_data = self.rfile.read(length) if length else b"{}"
            options = json.loads(request_data.decode("utf-8"))
            feed_type = options.get("feed_type", "top-grossing")
            genre = options.get("genre", "games")
            if feed_type not in CHARTS or genre not in GENRES:
                return self.respond(400, {"error": "Unsupported feed type or genre"})
        except (ValueError, UnicodeDecodeError, AttributeError):
            return self.respond(400, {"error": "Invalid diagnostic request"})

        try:
            rows, statuses = collect(
                countries=("SG",), genres=(genre,),
                feed_types=(feed_type,), depth=20,
            )
        except Exception as exc:
            traceback.print_exc()
            return self.respond(502, {"error": f"Collection failed: {type(exc).__name__}"})

        compact_rows = [{key: row.get(key, "") for key in COMPACT_FIELDS} for row in rows]
        self.respond(200, {
            "feed_type": CHARTS[feed_type],
            "genre": genre,
            "rankings": compact_rows,
            "statuses": statuses,
            "request_count": 1,
        })

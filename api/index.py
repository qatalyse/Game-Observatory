"""Vercel Python Function: authenticated, bounded, ephemeral Apple chart preview."""
from __future__ import annotations

import csv
from io import StringIO
import json
import os
from pathlib import Path
import secrets
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collector"))
from game_observatory.apple import collect, FIELDS, STATUS_FIELDS  # noqa: E402


def csv_text(rows, fields):
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


class handler(BaseHTTPRequestHandler):
    def respond(self, status, payload, content_type="application/json; charset=utf-8"):
        data = (json.dumps(payload) if isinstance(payload, dict) else payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        # Vercel rewrites may expose either the original URL or function path.
        if self.path.split("?")[0] not in ("/api/dev/apple-collect", "/api/index.py"):
            return self.respond(404, {"error": "Not found"})
        expected = os.getenv("DEV_COLLECT_TOKEN", "")
        supplied = self.headers.get("X-Dev-Token", "")
        if not expected:
            return self.respond(503, {"error": "Dev collection is disabled. Set DEV_COLLECT_TOKEN in Vercel environment variables."})
        if not secrets.compare_digest(supplied, expected):
            return self.respond(401, {"error": "Invalid dev token"})
        try:
            rows, statuses = collect(countries=("SG",), depth=20, pause_seconds=0.1)
        except Exception:
            return self.respond(502, {"error": "Collection failed unexpectedly"})
        self.respond(200, {
            "rankings": rows,
            "statuses": statuses,
            "rankings_csv": csv_text(rows, FIELDS),
            "statuses_csv": csv_text(statuses, STATUS_FIELDS),
        })

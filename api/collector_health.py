"""Isolate whether Vercel can package/import the Apple collector."""
from http.server import BaseHTTPRequestHandler
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collector"))
from game_observatory.apple import CHARTS, GENRES, MARKETS


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps({
            "status": "collector_import_ok",
            "market_count": len(MARKETS),
            "feed_types": list(CHARTS.values()),
            "genre_count": len(GENRES),
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

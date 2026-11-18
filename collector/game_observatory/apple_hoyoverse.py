"""Manual App-ID matching against Apple genre charts; CSV artifacts only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.resources import files
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from uuid import uuid4

from .apple import CHARTS, GENRES, MARKETS, SOURCE, feed_url, fetch_json, parse_entries, write_csv

COMMON_FIELDS = (
    "run_id", "snapshot_id", "retrieved_at_utc", "country", "store",
    "feed_type", "genre", "genre_id", "requested_depth", "coverage_depth",
    "chart_status", "http_status", "error", "source", "source_url",
    "feed_updated_at", "feed_fields", "entry_fields",
)
FIELDS = COMMON_FIELDS + (
    "app_id", "title", "observed_title", "rank", "status", "store_url",
)
STATUS_FIELDS = COMMON_FIELDS + ("source_count", "chart_complete")


def load_config(path: Path | None = None) -> dict:
    resource = path if path is not None else files(__package__).joinpath("apple_hoyoverse.json")
    config = json.loads(resource.read_text(encoding="utf-8"))
    validate_config(config)
    return config


def validate_config(config: dict) -> None:
    if not isinstance(config, dict) or type(config.get("requested_depth")) is not int:
        raise ValueError("Config requires an integer requested_depth")
    if not 1 <= config["requested_depth"] <= 100:
        raise ValueError("requested_depth must be between 1 and 100")
    genres = config.get("genres")
    if not isinstance(genres, list) or not genres:
        raise ValueError("Config requires nonempty genres")
    seen_genres = set()
    for spec in genres:
        if not isinstance(spec, dict):
            raise ValueError("Invalid genre specification")
        genre = spec.get("genre")
        if not isinstance(genre, str) or genre not in GENRES or spec.get("genre_id") != GENRES[genre]:
            raise ValueError("Genre ID must match existing Apple GENRES mapping")
        if genre in seen_genres:
            raise ValueError("Duplicate genre")
        seen_genres.add(genre)
        games = spec.get("games")
        if not isinstance(games, list) or not games:
            raise ValueError("Each genre requires games")
        seen_ids = set()
        for game in games:
            if not isinstance(game, dict):
                raise ValueError("Invalid game specification")
            app_id, title = game.get("app_id"), game.get("title")
            if not isinstance(app_id, str) or not app_id.isascii() or not app_id.isdigit() or int(app_id) <= 0:
                raise ValueError("App IDs must be positive numeric strings")
            if not isinstance(title, str) or not title.strip() or app_id in seen_ids:
                raise ValueError("Game titles must be nonempty and IDs unique per genre")
            seen_ids.add(app_id)


def collect(config: dict | None = None, *, fetch=None, clock=None, run_id: str | None = None):
    """One fetch per market/genre; no lookup requests, storage clients or writes."""
    config = load_config() if config is None else config
    validate_config(config)
    fetch = fetch_json if fetch is None else fetch
    clock = (lambda: datetime.now(timezone.utc)) if clock is None else clock
    run_id = run_id or uuid4().hex
    depth = config["requested_depth"]
    rows, statuses = [], []
    for country in MARKETS:
        for spec in config["genres"]:
            genre = spec["genre"]
            url = feed_url(country, genre, depth, "top-grossing")
            http_status, entries, error = None, [], ""
            meta = {"feed_updated_at": "", "feed_fields": "", "entry_fields": ""}
            chart_status = "error"
            try:
                payload, http_status = fetch(url)
                if not isinstance(http_status, int) or not 200 <= http_status < 300:
                    raise ValueError(f"Unexpected HTTP status: {http_status}")
                entries, meta = parse_entries(payload, depth, "top-grossing")
                if any(not e["app_id"].isascii() or not e["app_id"].isdigit() for e in entries):
                    raise ValueError("Non-numeric app ID in chart")
                chart_status = "complete" if len(entries) == depth else "partial" if entries else "empty"
            except HTTPError as exc:
                http_status = exc.code
                error = f"HTTPError: HTTP {exc.code}"
                entries = []
            except (ValueError, KeyError, TypeError, AttributeError, URLError, OSError, TimeoutError) as exc:
                error = f"{type(exc).__name__}: {exc}"
                entries = []
            # Retrieval/attempt completion time, including failed attempts, is always UTC.
            stamp = clock().astimezone(timezone.utc).isoformat()
            common = {
                "run_id": run_id, "snapshot_id": uuid4().hex,
                "retrieved_at_utc": stamp, "country": country, "store": "ios",
                "feed_type": CHARTS["top-grossing"], "genre": genre,
                "genre_id": spec["genre_id"], "requested_depth": depth,
                "coverage_depth": len(entries), "chart_status": chart_status,
                "http_status": http_status, "error": error, "source": SOURCE,
                "source_url": url, **meta,
            }
            statuses.append({
                **common, "source_count": len(entries),
                "chart_complete": chart_status == "complete",
            })
            by_id = {entry["app_id"]: entry for entry in entries}
            for game in spec["games"]:
                entry = by_id.get(game["app_id"])
                state = ("ranked" if entry else "outside-chart" if chart_status == "complete"
                         else "error" if chart_status == "error" else "unknown")
                rows.append({
                    **common, "app_id": game["app_id"], "title": game["title"],
                    "observed_title": entry["title"] if entry else "",
                    "rank": entry["position"] if entry else None, "status": state,
                    "store_url": entry["store_url"] if entry else "",
                })
    return rows, statuses


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Alternative dedicated roster JSON")
    parser.add_argument("--output", type=Path, default=Path("data/apple-hoyoverse"))
    args = parser.parse_args(argv)
    # Include attempt so a rerun cannot be confused with its earlier artifacts.
    github_id = os.environ.get("GITHUB_RUN_ID")
    run_id = (f"github-{github_id}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
              if github_id else uuid4().hex)
    rows, statuses = collect(load_config(args.config), run_id=run_id)
    write_csv(args.output / "apple_hoyoverse_rankings.csv", rows, FIELDS)
    write_csv(args.output / "apple_hoyoverse_chart_statuses.csv", statuses, STATUS_FIELDS)
    print(json.dumps({
        "run_id": run_id, "observations": len(rows), "chart_requests": len(statuses),
        "chart_statuses": {state: sum(s["chart_status"] == state for s in statuses)
                           for state in ("complete", "partial", "empty", "error")},
        "output_directory": str(args.output),
    }))
    return int(any(s["chart_status"] == "error" for s in statuses))


if __name__ == "__main__":
    raise SystemExit(main())

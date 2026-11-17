"""Collect Apple legacy iTunes RSS chart snapshots without choosing a database.

The source is live-only: fetched_at is a sampling timestamp, NOT an Apple chart
publication timestamp. Missing entries must never be given synthetic ranks.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

MARKETS = ("SG", "US", "JP", "KR", "CN", "MY", "TH", "ID", "PH", "VN")
GENRES = {"adventure": 7002, "role-playing": 7014, "action": 7001, "strategy": 7017}
CHARTS = {"free": "topfreeapplications"}
DEFAULT_DEPTH = 20
FIELDS = (
    "snapshot_id", "retrieved_at_utc", "country", "store", "chart",
    "genre", "genre_id", "chart_depth", "rank", "app_id", "title",
    "developer", "release_date", "store_url", "source",
)
STATUS_FIELDS = (
    "snapshot_id", "retrieved_at_utc", "country", "chart", "genre",
    "requested_depth", "returned_count", "status", "error",
    "source_url",
)
SOURCE = "apple_legacy_itunes_rss"


def feed_url(country: str, genre: str, depth: int = DEFAULT_DEPTH, chart: str = "free") -> str:
    country = country.upper()
    if country not in MARKETS:
        raise ValueError(f"Unsupported market: {country}")
    if genre not in GENRES:
        raise ValueError(f"Unsupported genre: {genre}")
    if chart not in CHARTS:
        raise ValueError(f"Unsupported chart: {chart}")
    if not 1 <= depth <= 100:
        raise ValueError("depth must be between 1 and 100")
    return (
        f"https://itunes.apple.com/{country.lower()}/rss/{CHARTS[chart]}"
        f"/limit={depth}/genre={GENRES[genre]}/json"
    )


def fetch_json(url: str, timeout: float = 15) -> dict:
    request = Request(url, headers={"User-Agent": "GameObservatory/0.1"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _label(field: object) -> str:
    return field.get("label", "") if isinstance(field, dict) else ""


def parse_entries(payload: dict, depth: int) -> list[dict]:
    """Validate first; never export partial results from a malformed feed."""
    if not isinstance(payload, dict) or not isinstance(payload.get("feed"), dict):
        raise ValueError("Missing Apple RSS feed object")
    raw = payload["feed"].get("entry", [])
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("Invalid Apple RSS entry list")
    if len(raw) > depth:
        raise ValueError("Feed contains more entries than requested")
    entries: list[dict] = []
    seen: set[str] = set()
    for rank, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValueError(f"Invalid entry at rank {rank}")
        ident = item.get("id")
        app_id = (ident.get("attributes") or {}).get("im:id") if isinstance(ident, dict) else None
        app_id = str(app_id).strip() if app_id is not None else ""
        title = _label(item.get("im:name")).strip()
        if not app_id or not title:
            raise ValueError(f"Missing app ID or name at rank {rank}")
        if app_id in seen:
            raise ValueError(f"Duplicate app ID {app_id} in a single chart")
        seen.add(app_id)
        link = item.get("link") or {}
        if isinstance(link, list):
            link = next((v for v in link if isinstance(v, dict) and isinstance(v.get("attributes"), dict) and v["attributes"].get("href")), {})
        released = item.get("im:releaseDate") or {}
        release_date = ""
        if isinstance(released, dict):
            release_date = (released.get("attributes") or {}).get("label") or _label(released)
        entries.append({
            "rank": rank, "app_id": app_id, "title": title,
            "developer": _label(item.get("im:artist")),
            "release_date": release_date,
            "store_url": (link.get("attributes") or {}).get("href", "") if isinstance(link, dict) else "",
        })
    return entries


def collect(
    countries: tuple[str, ...] = ("SG",),
    genres: tuple[str, ...] = tuple(GENRES),
    depth: int = DEFAULT_DEPTH,
    fetch: Callable[[str], dict] = fetch_json,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    pause_seconds: float = 0,
) -> tuple[list[dict], list[dict]]:
    """Return (rank_rows, chart_statuses). One failed chart does not discard others."""
    observations: list[dict] = []
    statuses: list[dict] = []
    for country in countries:
        for genre in genres:
            url = feed_url(country, genre, depth)
            stamp = clock().astimezone(timezone.utc).isoformat()
            snapshot_id = uuid4().hex
            base = {
                "snapshot_id": snapshot_id, "retrieved_at_utc": stamp,
                "country": country, "chart": "free", "genre": genre,
            }
            try:
                entries = parse_entries(fetch(url), depth)
                status = "ok" if len(entries) == depth else ("partial" if entries else "empty")
                for entry in entries:
                    observations.append({
                        **base, "store": "ios", "genre_id": GENRES[genre],
                        "chart_depth": depth, **entry, "source": SOURCE,
                    })
                error = ""
            except (ValueError, KeyError, TypeError, HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
                entries = []
                status = "error"
                error = f"{type(exc).__name__}: {exc}"
            statuses.append({
                **base, "requested_depth": depth, "returned_count": len(entries),
                "status": status, "error": error, "source_url": url,
            })
            if pause_seconds:
                time.sleep(pause_seconds)
    return observations, statuses


def write_csv(path: Path, rows: list[dict], fields: tuple[str, ...]) -> None:
    """Atomically replace one standalone CSV file, never append ambiguous duplicates."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid4().hex}.tmp")
    try:
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect live Apple RSS top-free Games charts")
    parser.add_argument("--countries", default="SG", help="Comma-separated Apple markets or ALL")
    parser.add_argument("--genres", default=",".join(GENRES), help="Comma-separated genres")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--output", default="data/apple", help="Local output directory")
    parser.add_argument("--pause-seconds", type=float, default=0.25)
    args = parser.parse_args(argv)
    countries = MARKETS if args.countries.upper() == "ALL" else tuple(x.strip().upper() for x in args.countries.split(","))
    genres = tuple(x.strip().lower() for x in args.genres.split(","))
    if not countries or not genres or len(set(countries)) != len(countries) or len(set(genres)) != len(genres):
        parser.error("Markets and genres must be nonempty and unique")
    if args.pause_seconds < 0:
        parser.error("--pause-seconds must be nonnegative")
    try:
        for country in countries:
            for genre in genres:
                feed_url(country, genre, args.depth)
    except ValueError as exc:
        parser.error(str(exc))
    rows, statuses = collect(countries, genres, args.depth, pause_seconds=args.pause_seconds)
    output = Path(args.output)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    write_csv(output / f"{run_id}_rankings.csv", rows, FIELDS)
    write_csv(output / f"{run_id}_statuses.csv", statuses, STATUS_FIELDS)
    print(json.dumps({
        "run_id": run_id, "markets": list(countries), "genres": list(genres),
        "observations": len(rows), "charts": len(statuses),
        "statuses": {state: sum(s["status"] == state for s in statuses)
                     for state in ("ok", "partial", "empty", "error")},
        "output_directory": str(output),
    }))
    return 1 if any(s["status"] == "error" for s in statuses) else 0


if __name__ == "__main__":
    raise SystemExit(main())

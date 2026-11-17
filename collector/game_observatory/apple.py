"""Diagnostic collector for Apple's legacy iTunes RSS application feeds.

Tests Top Grossing and New Applications. These are legacy endpoints, not
represented as a currently documented Apple Marketing Tools API.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
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
GENRES = {
    "games": 6014,
    "adventure": 7002,
    "role-playing": 7014,
    "action": 7001,
    "strategy": 7017,
}
CHARTS = {
    "top-grossing": "topgrossingapplications",
    "new-applications": "newapplications",
}
DEFAULT_DEPTH = 50
SNAPSHOT_BUFFER = 5
TRACKED_GAME_IDS = {"6776621908", "6745814650"}
FIELDS = (
    "snapshot_id", "retrieved_at_utc", "country", "store", "feed_type",
    "genre", "genre_id", "requested_depth", "snapshot_depth", "tracked_app_ids_found", "position", "position_semantics",
    "app_id", "title", "developer", "developer_url", "release_date",
    "store_url", "artwork_url", "description", "price_amount",
    "price_currency", "category_id", "category_label", "content_type",
    "content_rating", "copyright", "feed_updated_at", "source",
)
STATUS_FIELDS = (
    "snapshot_id", "retrieved_at_utc", "country", "feed_type", "genre",
    "genre_id", "requested_depth", "source_count", "snapshot_depth", "tracked_app_ids_found", "returned_count", "http_status",
    "status", "limit_behavior", "category_filter_id", "error",
    "feed_updated_at", "feed_fields", "entry_fields", "source_url",
)
SOURCE = "apple_legacy_itunes_rss"


def feed_url(country: str, genre: str, depth: int = DEFAULT_DEPTH, feed_type: str = "top-grossing") -> str:
    country = country.upper()
    if country not in MARKETS:
        raise ValueError(f"Unsupported market: {country}")
    if genre not in GENRES:
        raise ValueError(f"Unsupported genre: {genre}")
    if feed_type not in CHARTS:
        raise ValueError(f"Unsupported feed type: {feed_type}")
    if not 1 <= depth <= 100:
        raise ValueError("depth must be between 1 and 100")
    return (
        f"https://itunes.apple.com/{country.lower()}/rss/{CHARTS[feed_type]}"
        f"/limit={depth}/genre={GENRES[genre]}/json"
    )


def fetch_json(url: str, timeout: float = 8) -> tuple[dict, int]:
    request = Request(url, headers={"User-Agent": "GameObservatory/0.2"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Apple response exceeded 2 MB diagnostic safety limit")
        return json.loads(raw.decode("utf-8")), response.status


def _label(field: object) -> str:
    return field.get("label", "") if isinstance(field, dict) else ""


def _attributes(field: object) -> dict:
    return field.get("attributes", {}) if isinstance(field, dict) and isinstance(field.get("attributes"), dict) else {}


def _artwork(item: dict) -> str:
    images = item.get("im:image", [])
    if isinstance(images, dict):
        images = [images]
    if not isinstance(images, list):
        return ""
    # Use the largest declared artwork size where Apple supplies size metadata.
    candidates = []
    for image in images:
        if isinstance(image, dict):
            attrs = _attributes(image)
            size = str(attrs.get("height", "0"))
            try:
                score = int(size)
            except ValueError:
                score = 0
            candidates.append((score, _label(image)))
    return max(candidates, default=(0, ""))[1]


def _link(item: dict) -> dict:
    value = item.get("link") or {}
    if isinstance(value, list):
        return next((v for v in value if isinstance(v, dict) and _attributes(v).get("href")), {})
    return value if isinstance(value, dict) else {}


def parse_entries(payload: dict, depth: int, feed_type: str) -> tuple[list[dict], dict]:
    """Extract common legacy RSS metadata and preserve feed ordering semantics."""
    if feed_type not in CHARTS:
        raise ValueError(f"Unsupported feed type: {feed_type}")
    if not isinstance(payload, dict) or not isinstance(payload.get("feed"), dict):
        raise ValueError("Missing Apple RSS feed object")
    feed = payload["feed"]
    raw = feed.get("entry", [])
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("Invalid Apple RSS entry list")
    # New Applications may ignore the requested limit; retain every returned entry.
    # Top Grossing remains a strictly limited chart.
    if feed_type == "top-grossing" and len(raw) > depth:
        raise ValueError(f"Feed returned {len(raw)} entries, exceeding requested depth {depth}")

    feed_meta = {
        "feed_updated_at": _label(feed.get("updated")),
        "feed_fields": ",".join(sorted(str(k) for k in feed.keys())),
        "entry_fields": ",".join(sorted(str(k) for k in raw[0].keys())) if raw and isinstance(raw[0], dict) else "",
    }
    entries: list[dict] = []
    seen: set[str] = set()
    for position, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValueError(f"Invalid entry at position {position}")
        ident = item.get("id")
        app_id = _attributes(ident).get("im:id")
        app_id = str(app_id).strip() if app_id is not None else ""
        title = _label(item.get("im:name")).strip()
        if not app_id or not title:
            raise ValueError(f"Missing app ID or name at position {position}")
        if app_id in seen:
            raise ValueError(f"Duplicate app ID {app_id} in one feed")
        seen.add(app_id)

        artist = item.get("im:artist")
        category = item.get("category")
        if isinstance(category, list):
            category = category[0] if category else {}
        price = item.get("im:price")
        content_type = item.get("im:contentType")
        rating = item.get("im:rating")
        release = item.get("im:releaseDate")
        link = _link(item)
        artwork = _artwork(item)

        entries.append({
            "position": position,
            "position_semantics": "grossing_chart_rank" if feed_type == "top-grossing" else "feed_order_not_verified_as_rank",
            "app_id": app_id,
            "title": title,
            "developer": _label(artist),
            "developer_url": _attributes(artist).get("href", "") if isinstance(artist, dict) else "",
            "release_date": _attributes(release).get("label") or _label(release),
            "store_url": _attributes(link).get("href", ""),
            "artwork_url": artwork,
            "description": _label(item.get("summary")),
            "price_amount": _attributes(price).get("amount", "") if isinstance(price, dict) else "",
            "price_currency": _attributes(price).get("currency", "") if isinstance(price, dict) else "",
            "category_id": _attributes(category).get("im:id", "") if isinstance(category, dict) else "",
            "category_label": _attributes(category).get("label", "") if isinstance(category, dict) else "",
            "content_type": _label(content_type),
            "content_rating": _label(rating),
            "copyright": _label(item.get("rights")),
        })
    return entries, feed_meta


def collect(
    countries: tuple[str, ...] = ("SG",),
    genres: tuple[str, ...] = ("games", "adventure", "role-playing", "action", "strategy"),
    feed_types: tuple[str, ...] = ("top-grossing", "new-applications"),
    depth: int = DEFAULT_DEPTH,
    tracked_app_ids: set[str] | frozenset[str] | None = None,
    fetch: Callable[[str], object] = fetch_json,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    pause_seconds: float = 0,
) -> tuple[list[dict], list[dict]]:
    """Collect feeds and apply dynamic Top Grossing snapshot retention."""
    tracked_ids = {str(v) for v in (tracked_app_ids if tracked_app_ids is not None else TRACKED_GAME_IDS)}
    if not tracked_ids:
        raise ValueError("At least one tracked App Store ID must be configured")
    requests = [(country, feed_type, genre) for country in countries
                for feed_type in feed_types for genre in genres]

    def collect_one(request_spec):
        country, feed_type, genre = request_spec
        url = feed_url(country, genre, depth, feed_type)
        stamp = clock().astimezone(timezone.utc).isoformat()
        snapshot_id = uuid4().hex
        base = {
            "snapshot_id": snapshot_id, "retrieved_at_utc": stamp,
            "country": country, "store": "ios", "feed_type": CHARTS[feed_type],
            "genre": genre, "genre_id": GENRES[genre],
            "requested_depth": depth, "snapshot_depth": 0, "tracked_app_ids_found": "", "source": SOURCE,
        }
        http_status = None
        feed_meta = {"feed_updated_at": "", "feed_fields": "", "entry_fields": ""}
        try:
            if pause_seconds:
                time.sleep(pause_seconds)
            fetched = fetch(url)
            if isinstance(fetched, tuple) and len(fetched) == 2:
                payload, http_status = fetched
            else:
                payload = fetched
            entries, feed_meta = parse_entries(payload, depth, feed_type)
            source_count = len(entries)
            category_filter_id = GENRES["games"] if feed_type == "new-applications" and genre == "games" else ""
            if category_filter_id:
                entries = [entry for entry in entries if str(entry.get("category_id", "")) == str(category_filter_id)]
            if feed_type == "top-grossing":
                if len(entries) < depth:
                    status = "partial" if entries else "empty"
                    limit_behavior = "incomplete_chart_not_snapshotted"
                    snapshot_depth = 0
                    tracked_found_ids = []
                    retained_entries = []
                else:
                    tracked_found = [entry for entry in entries if entry["app_id"] in tracked_ids]
                    tracked_found_ids = [entry["app_id"] for entry in tracked_found]
                    if tracked_found:
                        lowest_rank = max(entry["position"] for entry in tracked_found)
                        snapshot_depth = min(depth, lowest_rank + 5 if lowest_rank % 10 == 0 else ((lowest_rank + 9) // 10) * 10)
                        retained_entries = [entry for entry in entries if entry["position"] <= snapshot_depth]
                        status = "ok"
                        limit_behavior = "tracked_rank_snapshot"
                    else:
                        snapshot_depth, retained_entries = 0, []
                        status = "no_tracked_titles"
                        limit_behavior = "no_tracked_title_in_complete_chart"
            else:
                status = "ok" if entries else "empty"
                limit_behavior = "exceeded_but_accepted" if source_count > depth else "feed_order_returned"
                snapshot_depth, retained_entries, tracked_found_ids = len(entries), entries, []
            rows = [{**base, "snapshot_depth": snapshot_depth,
                     "tracked_app_ids_found": ",".join(tracked_found_ids),
                     **entry, "feed_updated_at": feed_meta["feed_updated_at"]}
                    for entry in retained_entries]
            entries = retained_entries
            error = ""
        except HTTPError as exc:
            http_status = exc.code
            rows, entries, status = [], [], "error"
            source_count, category_filter_id, snapshot_depth = 0, "", 0
            tracked_found_ids = []
            limit_behavior = "not_verified"
            error = f"HTTPError: HTTP {exc.code}"
        except (ValueError, KeyError, TypeError, URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            rows, entries, status = [], [], "error"
            source_count, category_filter_id, snapshot_depth = 0, "", 0
            tracked_found_ids = []
            limit_behavior = "not_verified"
            error = f"{type(exc).__name__}: {exc}"
        status_row = {
            **base, "returned_count": len(entries), "source_count": source_count,
            "snapshot_depth": snapshot_depth, "tracked_app_ids_found": ",".join(tracked_found_ids),
            "category_filter_id": category_filter_id, "http_status": http_status,
            "status": status, "limit_behavior": limit_behavior,
            "error": error, **feed_meta, "source_url": url,
        }
        return rows, status_row

    observations: list[dict] = []
    statuses: list[dict] = []
    # Three concurrent connections bound total duration while avoiding a burst
    # of ten simultaneous requests to Apple's legacy feed host.
    with ThreadPoolExecutor(max_workers=3) as pool:
        for rows, status_row in pool.map(collect_one, requests):
            observations.extend(rows)
            statuses.append(status_row)
    return observations, statuses


def write_csv(path: Path, rows: list[dict], fields: tuple[str, ...]) -> None:
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
    parser = argparse.ArgumentParser(description="Collect Apple legacy Top Grossing and New Applications feeds")
    parser.add_argument("--countries", default="SG", help="Comma-separated Apple markets or ALL")
    parser.add_argument("--genres", default="games,adventure,role-playing,action,strategy")
    parser.add_argument("--feed-types", default="top-grossing,new-applications")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--output", default="data/apple")
    parser.add_argument("--pause-seconds", type=float, default=0.25)
    args = parser.parse_args(argv)
    countries = MARKETS if args.countries.upper() == "ALL" else tuple(x.strip().upper() for x in args.countries.split(","))
    genres = tuple(x.strip().lower() for x in args.genres.split(","))
    feed_types = tuple(x.strip().lower() for x in args.feed_types.split(","))
    if not countries or not genres or not feed_types or any(len(set(v)) != len(v) for v in (countries, genres, feed_types)):
        parser.error("Countries, genres and feed types must be nonempty and unique")
    if args.pause_seconds < 0:
        parser.error("--pause-seconds must be nonnegative")
    try:
        for country in countries:
            for feed_type in feed_types:
                for genre in genres:
                    feed_url(country, genre, args.depth, feed_type)
    except ValueError as exc:
        parser.error(str(exc))
    rows, statuses = collect(countries, genres, feed_types, args.depth, pause_seconds=args.pause_seconds)
    output = Path(args.output)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    write_csv(output / f"{run_id}_apple_feeds.csv", rows, FIELDS)
    write_csv(output / f"{run_id}_apple_statuses.csv", statuses, STATUS_FIELDS)
    print(json.dumps({
        "run_id": run_id, "markets": list(countries), "genres": list(genres),
        "feed_types": list(feed_types), "observations": len(rows), "feed_requests": len(statuses),
        "statuses": {state: sum(s["status"] == state for s in statuses)
                     for state in ("ok", "partial", "empty", "error")},
        "output_directory": str(output),
    }))
    return 1 if any(s["status"] == "error" for s in statuses) else 0


if __name__ == "__main__":
    raise SystemExit(main())

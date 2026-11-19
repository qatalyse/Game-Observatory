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
    "run_id", "snapshot_id", "retrieved_at_utc", "country", "store", "roster_version",
    "feed_type", "genre", "genre_id", "requested_depth", "coverage_depth",
    "chart_status", "http_status", "error", "source", "source_url",
    "feed_updated_at", "feed_fields", "entry_fields",
)
FIELDS = COMMON_FIELDS + (
    "app_id", "title", "observed_title", "rank", "status", "store_url",
    "game_id", "canonical_app_id", "mapping_status", "mapping_source_url",
    "mapping_note", "status_reason",
)
STATUS_FIELDS = COMMON_FIELDS + ("source_count", "chart_complete", "unresolved_game_ids")


def load_config(path: Path | None = None) -> dict:
    resource = path if path is not None else files(__package__).joinpath("apple_hoyoverse.json")
    config = json.loads(resource.read_text(encoding="utf-8"))
    validate_config(config)
    return config


def market_listing(game: dict, country: str) -> tuple[str | None, str]:
    """An explicit null suppresses the default ID; never guess a regional listing."""
    overrides = game.get("market_app_ids", {})
    if country in overrides:
        app_id = overrides[country]
        return app_id, "market-override" if app_id is not None else "unresolved"
    return game["app_id"], "default"


def _valid_app_id(value: object) -> bool:
    return (isinstance(value, str) and value.isascii() and value.isdigit()
            and int(value) > 0)


def validate_config(config: dict) -> None:
    if not isinstance(config, dict) or type(config.get("requested_depth")) is not int:
        raise ValueError("Config requires an integer requested_depth")
    if not 1 <= config["requested_depth"] <= 100:
        raise ValueError("requested_depth must be between 1 and 100")
    genres = config.get("genres")
    if not isinstance(genres, list) or not genres:
        raise ValueError("Config requires nonempty genres")
    seen_genres = set()
    identities = {}
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
        seen_games = set()
        market_ids = {country: set() for country in MARKETS}
        for game in games:
            if not isinstance(game, dict):
                raise ValueError("Invalid game specification")
            app_id, title = game.get("app_id"), game.get("title")
            if not _valid_app_id(app_id):
                raise ValueError("App IDs must be positive numeric strings")
            if not isinstance(title, str) or not title.strip() or app_id in seen_ids:
                raise ValueError("Game titles must be nonempty and IDs unique per genre")
            seen_ids.add(app_id)
            game_id = game.get("game_id", app_id)
            if not isinstance(game_id, str) or not game_id.strip() or game_id in seen_games:
                raise ValueError("Game IDs must be nonempty and unique per genre")
            seen_games.add(game_id)
            overrides = game.get("market_app_ids", {})
            if not isinstance(overrides, dict) or any(c not in MARKETS for c in overrides):
                raise ValueError("Market overrides require supported country keys")
            if any(value is not None and not _valid_app_id(value) for value in overrides.values()):
                raise ValueError("Market App IDs must be numeric strings or explicit null")
            for field in ("market_mapping_sources", "market_mapping_notes"):
                values = game.get(field, {})
                if (not isinstance(values, dict)
                        or any(c not in overrides for c in values)
                        or any(not isinstance(v, str) or not v.strip() for v in values.values())):
                    raise ValueError(f"{field} must describe configured market overrides")
            signature = (app_id, title, tuple(sorted(overrides.items())))
            if game_id in identities and identities[game_id] != signature:
                raise ValueError("A game must have consistent listings across genres")
            identities[game_id] = signature
            for country in MARKETS:
                resolved_id, _ = market_listing(game, country)
                if resolved_id is not None:
                    if resolved_id in market_ids[country]:
                        raise ValueError(f"Duplicate listing in {country} within one genre")
                    market_ids[country].add(resolved_id)


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
                "roster_version": config.get("roster_version", "custom"),
                "feed_type": CHARTS["top-grossing"], "genre": genre,
                "genre_id": spec["genre_id"], "requested_depth": depth,
                "coverage_depth": len(entries), "chart_status": chart_status,
                "http_status": http_status, "error": error, "source": SOURCE,
                "source_url": url, **meta,
            }
            statuses.append({
                **common, "source_count": len(entries),
                "chart_complete": chart_status == "complete",
                "unresolved_game_ids": ";".join(
                    g.get("game_id", g["app_id"]) for g in spec["games"]
                    if market_listing(g, country)[0] is None),
            })
            by_id = {entry["app_id"]: entry for entry in entries}
            for game in spec["games"]:
                app_id, mapping_status = market_listing(game, country)
                entry = by_id.get(app_id) if app_id is not None else None
                if chart_status == "error":
                    state, reason = "error", "chart_retrieval_or_validation_failed"
                elif app_id is None:
                    state, reason = "unknown", "unresolved_market_listing"
                elif entry:
                    state, reason = "ranked", "observed_app_id"
                elif chart_status == "complete":
                    state, reason = "outside-chart", "absent_from_complete_requested_chart"
                else:
                    state, reason = "unknown", "incomplete_chart"
                reference = game.get("market_mapping_sources", {}).get(country, "")
                if not reference and app_id is not None:
                    reference = f"https://apps.apple.com/{country.lower()}/app/id{app_id}"
                rows.append({
                    **common, "app_id": app_id, "title": game["title"],
                    "game_id": game.get("game_id", game["app_id"]),
                    "canonical_app_id": game["app_id"], "mapping_status": mapping_status,
                    "mapping_source_url": reference,
                    "mapping_note": game.get("market_mapping_notes", {}).get(country, ""),
                    "status_reason": reason,
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
        "unresolved_listings": [{"country": r["country"], "game_id": r["game_id"]}
                                for r in rows if r["mapping_status"] == "unresolved"],
        "game_statuses": {state: sum(r["status"] == state for r in rows)
                          for state in ("ranked", "outside-chart", "unknown", "error")},
    }))
    return int(any(s["chart_status"] == "error" for s in statuses))


if __name__ == "__main__":
    raise SystemExit(main())

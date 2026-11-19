"""Validate HoYoverse CSVs and publish one immutable daily snapshot to Sheets.

Dry-run is the default. Google dependencies and credentials are loaded only with
--publish. The existing manual collector remains storage-independent.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from .apple import MARKETS
from .apple_hoyoverse import COMMON_FIELDS, FIELDS, STATUS_FIELDS, load_config, market_listing

SCOPE = "https://www.googleapis.com/auth/spreadsheets"
MARKER_KEY = "game_observatory.apple.daily.v1"
PREFIX = ("collection_date", "publication_key", "record_key")
RANK_HEADERS = PREFIX + FIELDS
CHART_HEADERS = PREFIX + STATUS_FIELDS
NUMERIC = {"rank", "genre_id", "requested_depth", "coverage_depth", "source_count", "http_status"}
TRANSIENT = {408, 429, 500, 502, 503, 504}
DEFAULT_RANK_TAB = "HoYoRankHistory"
DEFAULT_CHART_TAB = "HoYoChartStatuses"


class SheetsError(RuntimeError):
    def __init__(self, status: int | None = None):
        self.status = status
        super().__init__(f"Google Sheets HTTP {status}" if status else "Google Sheets transport failure")


def read_csv(path: Path, fields: tuple[str, ...]) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(fields):
            raise ValueError(f"Unexpected CSV schema in {path.name}; requires PR #3 output")
        rows = list(reader)
    if any(set(row) != set(fields) or any(v is None for v in row.values()) for row in rows):
        raise ValueError(f"Malformed CSV row in {path.name}")
    return rows


def _integer(value: str, field: str, minimum: int = 0) -> int:
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError(f"Invalid integer: {field}")
    number = int(value)
    if number < minimum:
        raise ValueError(f"Invalid integer: {field}")
    return number


def _stamp(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("Retrieval timestamps must be UTC")
    return stamp


def prepare(rows: list[dict], charts: list[dict], config: dict | None = None) -> dict:
    """Validate the complete configured batch before any authentication or write."""
    config = load_config() if config is None else config
    from .apple_hoyoverse import validate_config
    validate_config(config)
    specs = {str(s["genre_id"]): s for s in config["genres"]}
    expected_charts = {(c, g) for c in MARKETS for g in specs}
    chart_map, snapshots, dates, run_ids = {}, set(), set(), set()
    for chart in charts:
        key = chart["country"], chart["genre_id"]
        if key not in expected_charts or key in chart_map:
            raise ValueError("Duplicate or unexpected chart")
        if not chart["snapshot_id"] or chart["snapshot_id"] in snapshots:
            raise ValueError("Chart snapshot IDs must be nonempty and unique")
        snapshots.add(chart["snapshot_id"])
        spec = specs[key[1]]
        depth = _integer(chart["requested_depth"], "requested_depth", 1)
        coverage = _integer(chart["coverage_depth"], "coverage_depth")
        count = _integer(chart["source_count"], "source_count")
        state = chart["chart_status"]
        if depth != config["requested_depth"] or count != coverage or coverage > depth:
            raise ValueError("Invalid chart coverage")
        if state not in {"complete", "partial", "empty", "error"}:
            raise ValueError("Invalid chart status")
        valid = {"complete": coverage == depth, "partial": 0 < coverage < depth,
                 "empty": coverage == 0, "error": coverage == 0}
        if not valid[state] or chart["chart_complete"].lower() != str(state == "complete").lower():
            raise ValueError("Inconsistent chart completeness")
        if chart["genre"] != spec["genre"] or chart["feed_type"] != "topgrossingapplications":
            raise ValueError("Unexpected chart scope")
        if chart["roster_version"] != config.get("roster_version", "custom"):
            raise ValueError("CSV roster version differs from current config")
        if state != "error" and not 200 <= _integer(chart["http_status"], "http_status") < 300:
            raise ValueError("Successful chart requires HTTP success")
        unresolved = ";".join(g.get("game_id", g["app_id"]) for g in spec["games"]
                              if market_listing(g, key[0])[0] is None)
        if chart["unresolved_game_ids"] != unresolved:
            raise ValueError("Unresolved target list differs from roster")
        dates.add(_stamp(chart["retrieved_at_utc"]).astimezone(ZoneInfo("Asia/Singapore")).date().isoformat())
        run_ids.add(chart["run_id"])
        chart_map[key] = chart
    if set(chart_map) != expected_charts or len(dates) != 1 or len(run_ids) != 1 or "" in run_ids:
        raise ValueError("Need one complete chart batch, one run and one Singapore collection date")
    day = next(iter(dates))
    publication_key = f"apple-hoyoverse:{day}"
    games = {(country, genre, g.get("game_id", g["app_id"])): g
             for country, genre in expected_charts for g in specs[genre]["games"]}
    seen = set()
    for row in rows:
        key = row["country"], row["genre_id"], row["game_id"]
        if key not in games or key in seen:
            raise ValueError("Duplicate or unexpected game observation")
        seen.add(key)
        chart, game = chart_map[key[:2]], games[key]
        if any(row[field] != chart[field] for field in COMMON_FIELDS):
            raise ValueError("Observation metadata does not match chart")
        app_id, mapping = market_listing(game, key[0])
        if (row["app_id"] != (app_id or "") or row["canonical_app_id"] != game["app_id"]
                or row["mapping_status"] != mapping):
            raise ValueError("Observation market listing differs from current config")
        if row["status"] == "ranked":
            rank = _integer(row["rank"], "rank", 1)
            if not app_id or chart["chart_status"] not in {"complete", "partial"} or rank > int(chart["coverage_depth"]):
                raise ValueError("Rank outside validated coverage")
        else:
            if row["rank"]:
                raise ValueError("Unobserved rank must be blank, never 101")
            expected = ("error" if chart["chart_status"] == "error" else "unknown"
                        if app_id is None or chart["chart_status"] != "complete" else "outside-chart")
            if row["status"] != expected:
                raise ValueError("Invalid absence status for chart/mapping coverage")
    if seen != set(games):
        raise ValueError("Missing configured game observations")
    def decorate(row, record):
        return {"collection_date": day, "publication_key": publication_key,
                "record_key": f"{publication_key}:{record}", **row}
    rankings = [decorate(r, f"{r['country']}:{r['genre_id']}:{r['game_id']}")
                for r in sorted(rows, key=lambda r: (r["country"], r["genre_id"], r["game_id"]))]
    statuses = [decorate(c, f"{c['country']}:{c['genre_id']}")
                for c in sorted(charts, key=lambda c: (c["country"], c["genre_id"]))]
    # A fixed positive, spreadsheet-unique metadata ID makes the daily commit
    # exclusive even for concurrent writers. Collisions fail closed.
    marker_id = 1_000_000_000 + int(day.replace("-", ""))
    return {"collection_date": day, "publication_key": publication_key,
            "marker_id": marker_id, "run_id": next(iter(run_ids)),
            "rankings": rankings, "charts": statuses,
            "chart_errors": sum(c["chart_status"] == "error" for c in charts)}


def _cell(value, field=""):
    if value is None or value == "":
        return {}
    if field in NUMERIC:
        return {"userEnteredValue": {"numberValue": int(value)}}
    if field == "chart_complete":
        return {"userEnteredValue": {"boolValue": str(value).lower() == "true"}}
    # Explicit stringValue prevents formulas and preserves IDs as text.
    return {"userEnteredValue": {"stringValue": str(value)}}


def _row(values, fields):
    return {"values": [_cell(values.get(field, ""), field) for field in fields]}



class GoogleSheets:
    """Small REST adapter; no hidden POST retries (publisher reconciles writes)."""
    def __init__(self, spreadsheet_id, session, auth_errors=()):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", spreadsheet_id):
            raise ValueError("Invalid spreadsheet ID")
        self.base = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        self.session = session
        self.auth_errors = auth_errors

    @classmethod
    def authenticated(cls, spreadsheet_id):
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        from google.auth.exceptions import GoogleAuthError
        try:
            credentials, _ = google.auth.default(scopes=[SCOPE])
        except GoogleAuthError as exc:
            raise SheetsError(401) from exc
        return cls(spreadsheet_id, AuthorizedSession(credentials), (GoogleAuthError,))

    def request(self, method, suffix="", body=None):
        try:
            response = self.session.request(method, self.base + suffix, json=body, timeout=30)
        except self.auth_errors as exc:
            raise SheetsError(401) from exc
        except (OSError, TimeoutError) as exc:
            raise SheetsError() from exc
        if not 200 <= response.status_code < 300:
            # Never log tokens, request payloads or credential-provider responses.
            raise SheetsError(response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise SheetsError() from exc

    def metadata(self):
        fields = "sheets(properties(sheetId,title)),developerMetadata"
        return self.request("GET", "?" + urlencode({"fields": fields}))

    def header(self, title):
        quoted = "'" + title.replace("'", "''") + "'"
        target = quote(f"{quoted}!1:1", safe="")
        return self.request("GET", "/values/" + target).get("values", [])

    def batch(self, requests):
        return self.request("POST", ":batchUpdate", {"requests": requests})


def publish(client, batch, rank_tab=DEFAULT_RANK_TAB, chart_tab=DEFAULT_CHART_TAB,
            *, sleep=time.sleep, attempts=4):
    """Atomically append both tables and an exclusive daily commit marker.

    First published snapshot wins. Later collections on that Singapore date
    are no-ops; successful rows are never replaced with failed or newer data.
    """
    if batch["chart_errors"]:
        raise ValueError("Source chart errors: keep CSVs and retry collection; no Sheets writes")
    if attempts < 1:
        raise ValueError("attempts must be positive")
    if (not rank_tab.strip() or not chart_tab.strip() or rank_tab == chart_tab
            or any(len(t) > 100 or re.search(r"[:\\/?*\[\]]", t) for t in (rank_tab, chart_tab))):
        raise ValueError("Choose two distinct, valid sheet tab names")
    marker_value = json.dumps({"publication_key": batch["publication_key"],
                               "rank_tab": rank_tab, "chart_tab": chart_tab}, sort_keys=True)
    last_error = None
    for attempt in range(attempts):
        try:
            meta = client.metadata()
            sheets = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}
            markers = meta.get("developerMetadata", [])
            existing = next((m for m in markers if m["metadataId"] == batch["marker_id"]), None)
            if existing:
                if existing.get("metadataKey") != MARKER_KEY or existing.get("metadataValue") != marker_value:
                    raise ValueError("Daily receipt ID collision or different destination tabs")
                if rank_tab not in sheets or chart_tab not in sheets:
                    raise ValueError("Published receipt exists but a destination tab is missing")
                return {"status": "already_published", "publication_key": batch["publication_key"]}
            if any(m.get("metadataKey") == MARKER_KEY and m.get("metadataValue") == marker_value for m in markers):
                raise ValueError("Daily receipt uses an unexpected ID")
            requests, used_ids = [], set(sheets.values())
            for title, fields, records in (
                (rank_tab, RANK_HEADERS, batch["rankings"]),
                (chart_tab, CHART_HEADERS, batch["charts"]),
            ):
                if title in sheets:
                    if client.header(title) != [list(fields)]:
                        raise ValueError(f"Unexpected headers in {title}; no writes performed")
                    sheet_id = sheets[title]
                else:
                    sheet_id = max(used_ids, default=0) + 1
                    used_ids.add(sheet_id)
                    requests.append({"addSheet": {"properties": {
                        "sheetId": sheet_id, "title": title,
                        "gridProperties": {"columnCount": len(fields), "frozenRowCount": 1},
                    }}})
                    requests.append({"updateCells": {
                        "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
                        "rows": [{"values": [_cell(field) for field in fields]}],
                        "fields": "userEnteredValue",
                    }})
                requests.append({"appendCells": {"sheetId": sheet_id,
                                                  "rows": [_row(row, fields) for row in records],
                                                  "fields": "userEnteredValue"}})
            requests.append({"createDeveloperMetadata": {"developerMetadata": {
                "metadataId": batch["marker_id"], "metadataKey": MARKER_KEY,
                "metadataValue": marker_value, "location": {"spreadsheet": True},
                "visibility": "DOCUMENT",
            }}})
            if len(json.dumps(requests, ensure_ascii=False).encode("utf-8")) > 1_800_000:
                raise ValueError("Upload exceeds the 1.8 MB request safety limit")
            try:
                client.batch(requests)
            except SheetsError as exc:
                # A timeout or even a duplicate-ID 400 may follow a completed
                # concurrent commit. Always reconcile before deciding to retry.
                try:
                    after = client.metadata()
                    committed = next((m for m in after.get("developerMetadata", [])
                                      if m["metadataId"] == batch["marker_id"]), None)
                    if committed and committed.get("metadataKey") == MARKER_KEY and committed.get("metadataValue") == marker_value:
                        return {"status": "already_published", "publication_key": batch["publication_key"]}
                except SheetsError:
                    pass
                raise exc
            return {"status": "published", "publication_key": batch["publication_key"],
                    "ranking_rows": len(batch["rankings"]), "chart_rows": len(batch["charts"])}
        except SheetsError as exc:
            last_error = exc
            if exc.status is not None and exc.status not in TRANSIENT:
                raise
            if attempt + 1 < attempts:
                sleep(2 ** (attempt + 1))
    raise last_error or SheetsError()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/apple-hoyoverse"))
    parser.add_argument("--spreadsheet-id", default=os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", ""))
    parser.add_argument("--rankings-tab", default=os.environ.get("GOOGLE_SHEETS_RANKINGS_TAB", DEFAULT_RANK_TAB))
    parser.add_argument("--statuses-tab", default=os.environ.get("GOOGLE_SHEETS_STATUSES_TAB", DEFAULT_CHART_TAB))
    parser.add_argument("--publish", action="store_true", help="Explicitly enable remote Sheets writes")
    args = parser.parse_args(argv)
    try:
        rows = read_csv(args.input / "apple_hoyoverse_rankings.csv", FIELDS)
        charts = read_csv(args.input / "apple_hoyoverse_chart_statuses.csv", STATUS_FIELDS)
        batch = prepare(rows, charts)
        report = {"status": "dry_run", "publication_key": batch["publication_key"],
                  "ranking_rows": len(rows), "chart_rows": len(charts),
                  "ready_for_publish": not batch["chart_errors"]}
        if args.publish:
            if batch["chart_errors"]:
                raise ValueError("Source chart errors: publication disabled")
            if not args.spreadsheet_id:
                raise ValueError("Set GOOGLE_SHEETS_SPREADSHEET_ID before publishing")
            client = GoogleSheets.authenticated(args.spreadsheet_id)
            try:
                report = publish(client, batch, args.rankings_tab, args.statuses_tab)
            finally:
                client.session.close()
        print(json.dumps(report))
        return 0
    except (ValueError, OSError, SheetsError, ImportError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

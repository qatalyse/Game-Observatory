"""Validate Steam CSVs and publish one immutable daily snapshot to Sheets.

Dry-run is the default. Authentication is loaded only for explicit --publish.
The existing collector and manual CSV exporter remain storage-independent.
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
from zoneinfo import ZoneInfo

from .apple_sheets import GoogleSheets, SheetsError
from .steam import GAMES, SOURCE, player_url
from .steam_test_dataset import PLAYER_FIELDS, STATUS_FIELDS

MARKER_KEY = "game_observatory.steam.daily.v1"
PREFIX = ("collection_date", "publication_key", "record_key")
PLAYER_HEADERS = PREFIX + PLAYER_FIELDS
STATUS_HEADERS = PREFIX + STATUS_FIELDS
NUMERIC = {"player_count", "http_status", "steam_result"}
TRANSIENT = {408, 429, 500, 502, 503, 504}
DEFAULT_PLAYERS_TAB = "SteamPlayerHistory"
DEFAULT_STATUSES_TAB = "SteamPlayerStatuses"


def read_csv(path, fields):
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(fields):
            raise ValueError(f"Unexpected Steam CSV schema in {path.name}")
        rows = list(reader)
    if any(set(row) != set(fields) or any(v is None for v in row.values()) for row in rows):
        raise ValueError(f"Malformed Steam CSV row in {path.name}")
    return rows


def _integer(value, field, *, signed=False):
    if not isinstance(value, str) or not re.fullmatch(r"-?[0-9]+" if signed else r"[0-9]+", value):
        raise ValueError(f"Invalid integer: {field}")
    return int(value)


def _stamp(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("Retrieval timestamps must be UTC")
    return stamp


def prepare(players, statuses):
    """Require one complete current-roster batch and matching successful rows."""
    seen, snapshots, runs, dates = set(), set(), set(), set()
    for row in statuses:
        if set(row) != set(STATUS_FIELDS) or any(not isinstance(v, str) for v in row.values()):
            raise ValueError("Unexpected Steam status schema")
        app_id = row["app_id"]
        if app_id not in GAMES or app_id in seen:
            raise ValueError("Duplicate or unexpected Steam App ID")
        seen.add(app_id)
        if not row["snapshot_id"] or row["snapshot_id"] in snapshots or not row["run_id"]:
            raise ValueError("Need unique snapshot IDs and a nonempty run ID")
        snapshots.add(row["snapshot_id"])
        runs.add(row["run_id"])
        if row["title"] != GAMES[app_id] or row["source"] != SOURCE or row["source_url"] != player_url(app_id):
            raise ValueError("Steam observation identity or source differs from current roster")
        started, retrieved = _stamp(row["started_at_utc"]), _stamp(row["retrieved_at_utc"])
        if retrieved < started:
            raise ValueError("Retrieval precedes request start")
        dates.add(retrieved.astimezone(ZoneInfo("Asia/Singapore")).date().isoformat())
        http = _integer(row["http_status"], "http_status") if row["http_status"] else None
        result = _integer(row["steam_result"], "steam_result", signed=True) if row["steam_result"] else None
        if http is not None and not 100 <= http <= 599:
            raise ValueError("Invalid HTTP status")
        state = row["status"]
        if state == "ok":
            _integer(row["player_count"], "player_count")
            if http != 200 or result != 1 or row["error_code"] or row["error"]:
                raise ValueError("Invalid successful Steam observation")
        elif state == "unavailable":
            if (row["player_count"] or http != 200 or result is None or result == 1
                    or row["error_code"] != "steam_unavailable" or not row["error"]):
                raise ValueError("Invalid unavailable Steam observation")
        elif state == "error":
            if (row["player_count"] or row["error_code"] not in {
                    "http_error", "timeout", "network_error", "invalid_response", "unexpected_error"}
                    or not row["error"] or result is not None):
                raise ValueError("Invalid failed Steam observation")
            if row["error_code"] == "http_error" and (http is None or http == 200):
                raise ValueError("HTTP failure requires a failing HTTP status")
        else:
            raise ValueError("Invalid Steam observation status")
    if seen != set(GAMES) or len(runs) != 1 or len(dates) != 1:
        raise ValueError("Need the full Steam roster, one run and one Singapore collection date")
    if any(set(row) != set(PLAYER_FIELDS) for row in players):
        raise ValueError("Unexpected Steam player schema")
    expected = {r["app_id"]: {f: r[f] for f in PLAYER_FIELDS}
                for r in statuses if r["status"] == "ok"}
    actual = {r["app_id"]: r for r in players}
    if len(actual) != len(players) or actual != expected:
        raise ValueError("Player rows must exactly match successful status records")
    day = next(iter(dates))
    key = f"steam-players:{day}"
    def decorate(row):
        return {"collection_date": day, "publication_key": key,
                "record_key": f"{key}:{row['app_id']}", **row}
    return {"collection_date": day, "publication_key": key,
            "marker_id": 1_100_000_000 + int(day.replace("-", "")),
            "run_id": next(iter(runs)),
            "players": [decorate(r) for r in sorted(players, key=lambda r: r["app_id"])],
            "statuses": [decorate(r) for r in sorted(statuses, key=lambda r: r["app_id"])],
            "source_errors": sum(r["status"] == "error" for r in statuses)}


def _cell(value, field=""):
    if value is None or value == "":
        return {}
    if field in NUMERIC:
        return {"userEnteredValue": {"numberValue": int(value)}}
    # Literal text preserves App IDs and prevents spreadsheet formula execution.
    return {"userEnteredValue": {"stringValue": str(value)}}


def _row(values, fields):
    return {"values": [_cell(values.get(field, ""), field) for field in fields]}


def publish(client, batch, players_tab=DEFAULT_PLAYERS_TAB, statuses_tab=DEFAULT_STATUSES_TAB,
            *, sleep=time.sleep, attempts=4):
    """Atomically append both tables and an exclusive daily commit marker.

    First published snapshot wins. Later collections on that Singapore date
    are no-ops; successful rows are never replaced with failed or newer data.
    """
    if batch["source_errors"]:
        raise ValueError("Steam request/parse errors: keep CSVs and retry collection; no Sheets writes")
    if attempts < 1:
        raise ValueError("attempts must be positive")
    if (not players_tab.strip() or not statuses_tab.strip() or players_tab == statuses_tab
            or any(len(t) > 100 or re.search(r"[:\\/?*\[\]]", t) for t in (players_tab, statuses_tab))):
        raise ValueError("Choose two distinct, valid sheet tab names")
    marker_value = json.dumps({"publication_key": batch["publication_key"],
                               "players_tab": players_tab, "statuses_tab": statuses_tab}, sort_keys=True)
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
                if players_tab not in sheets or statuses_tab not in sheets:
                    raise ValueError("Published receipt exists but a destination tab is missing")
                return {"status": "already_published", "publication_key": batch["publication_key"]}
            if any(m.get("metadataKey") == MARKER_KEY and m.get("metadataValue") == marker_value for m in markers):
                raise ValueError("Daily receipt uses an unexpected ID")
            requests, used_ids = [], set(sheets.values())
            for title, fields, records in (
                (players_tab, PLAYER_HEADERS, batch["players"]),
                (statuses_tab, STATUS_HEADERS, batch["statuses"]),
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
                if records:
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
                    "player_rows": len(batch["players"]), "status_rows": len(batch["statuses"])}
        except SheetsError as exc:
            last_error = exc
            if exc.status is not None and exc.status not in TRANSIENT:
                raise
            if attempt + 1 < attempts:
                sleep(2 ** (attempt + 1))
    raise last_error or SheetsError()



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/steam-daily"))
    parser.add_argument("--spreadsheet-id", default=os.environ.get("STEAM_SHEETS_SPREADSHEET_ID", ""))
    parser.add_argument("--players-tab", default=os.environ.get("STEAM_SHEETS_PLAYERS_TAB", DEFAULT_PLAYERS_TAB))
    parser.add_argument("--statuses-tab", default=os.environ.get("STEAM_SHEETS_STATUSES_TAB", DEFAULT_STATUSES_TAB))
    parser.add_argument("--publish", action="store_true", help="Explicitly enable remote Sheets writes")
    args = parser.parse_args(argv)
    try:
        players = read_csv(args.input / "steam_players.csv", PLAYER_FIELDS)
        statuses = read_csv(args.input / "steam_statuses.csv", STATUS_FIELDS)
        batch = prepare(players, statuses)
        report = {"status": "dry_run", "publication_key": batch["publication_key"],
                  "player_rows": len(players), "status_rows": len(statuses),
                  "source_errors": batch["source_errors"],
                  "ready_for_publish": not batch["source_errors"]}
        if args.publish:
            if batch["source_errors"]:
                raise ValueError("Steam request/parse errors: publication disabled")
            if not args.spreadsheet_id:
                raise ValueError("Set STEAM_SHEETS_SPREADSHEET_ID before publishing")
            client = GoogleSheets.authenticated(args.spreadsheet_id)
            try:
                report = publish(client, batch, args.players_tab, args.statuses_tab)
            finally:
                client.session.close()
        print(json.dumps(report))
        return 1 if batch["source_errors"] else 0
    except (ValueError, OSError, SheetsError, ImportError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

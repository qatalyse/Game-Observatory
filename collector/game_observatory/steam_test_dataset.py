"""Manual CSV export of the configured Steam concurrent-player catalogue.

The existing diagnostic collector remains storage-independent. This separate
entry point writes files only when explicitly invoked, including in Actions.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .steam import collect

PLAYER_FIELDS = (
    "snapshot_id", "run_id", "app_id", "title", "player_count",
    "started_at_utc", "retrieved_at_utc", "source", "source_url",
)
STATUS_FIELDS = PLAYER_FIELDS + (
    "http_status", "steam_result", "status", "error_code", "error",
)


def write_csv(path: Path, rows: list[dict], fields: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/steam-test"))
    args = parser.parse_args(argv)
    result = collect()
    statuses = result["results"]
    players = [row for row in statuses if row["status"] == "ok"]
    # Write both files before reporting per-app failures. None becomes a blank
    # CSV cell, while an observed player_count of zero remains the integer 0.
    write_csv(args.output / "steam_players.csv", players, PLAYER_FIELDS)
    write_csv(args.output / "steam_statuses.csv", statuses, STATUS_FIELDS)
    counts = {state: sum(row["status"] == state for row in statuses)
              for state in ("ok", "unavailable", "error")}
    print(json.dumps({
        "run_id": result["run_id"],
        "started_at_utc": result["started_at_utc"],
        "completed_at_utc": result["completed_at_utc"],
        "status": result["status"],
        "app_ids_selected": result["app_ids_selected"],
        "request_count": result["request_count"],
        "observations": len(players),
        "statuses": counts,
        "output_directory": str(args.output),
    }, ensure_ascii=False))
    # Unavailable data is a source outcome, not an export failure. Actual
    # request/parse failures fail the job after leaving both CSVs available.
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

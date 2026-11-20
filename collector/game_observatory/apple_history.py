"""Validate saved manual HoYoverse exports for an explicit historical import."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from . import apple_sheets as sheets
from .apple_hoyoverse import FIELDS, STATUS_FIELDS

MANUAL_WORKFLOW = ".github/workflows/apple-hoyoverse-targeted.yml"


def positive_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value):
        raise ValueError(f"{label} must be a positive numeric ID")
    return value


def source_details(payload: dict, repository: str, run_id: str) -> dict:
    """Accept only a completed successful manual export from this repository."""
    run_id = positive_id(run_id, "Source run ID")
    if not isinstance(payload, dict):
        raise ValueError("Invalid source run metadata")
    if type(payload.get("id")) is not int or str(payload["id"]) != run_id:
        raise ValueError("Source run ID does not match metadata")
    for field in ("repository", "head_repository"):
        repo = payload.get(field)
        if not isinstance(repo, dict) or repo.get("full_name") != repository:
            raise ValueError("Source run must belong to this repository")
    if (payload.get("path") != MANUAL_WORKFLOW
            or payload.get("event") != "workflow_dispatch"
            or payload.get("status") != "completed"
            or payload.get("conclusion") != "success"):
        raise ValueError("Source must be a successful completed manual HoYoverse export")
    attempt = payload.get("run_attempt")
    if type(attempt) is not int or attempt < 1:
        raise ValueError("Invalid source attempt")
    sha = payload.get("head_sha")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid source commit")
    return {
        "source_run_id": run_id,
        "source_attempt": positive_id(str(attempt), "Source attempt"),
        "source_sha": sha,
        "rankings_artifact": f"apple-hoyoverse-rankings-{run_id}-{attempt}",
        "statuses_artifact": f"apple-hoyoverse-chart-statuses-{run_id}-{attempt}",
    }


def historical_batch(directory: Path, run_id: str, attempt: str, expected_date: str, *, clock=None) -> dict:
    """Keep original observation times; reject wrong, current or future dates."""
    run_id = positive_id(run_id, "Source run ID")
    attempt = positive_id(attempt, "Source attempt")
    day = date.fromisoformat(expected_date)
    if day.isoformat() != expected_date:
        raise ValueError("Collection date must use YYYY-MM-DD")
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Current time must be timezone-aware")
    if day >= now.astimezone(ZoneInfo("Asia/Singapore")).date():
        raise ValueError("Historical imports require a date before today in Singapore")
    rows = sheets.read_csv(directory / "apple_hoyoverse_rankings.csv", FIELDS)
    charts = sheets.read_csv(directory / "apple_hoyoverse_chart_statuses.csv", STATUS_FIELDS)
    batch = sheets.prepare(rows, charts)
    if batch["collection_date"] != expected_date:
        raise ValueError("Saved observations do not match the requested collection date")
    if batch["run_id"] != f"github-{run_id}-{attempt}":
        raise ValueError("CSV run identifier does not match the selected source run/attempt")
    if batch["chart_errors"]:
        raise ValueError("Source chart errors block historical publication")
    return batch


def main(argv=None, *, clock=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-attempt", required=True)
    parser.add_argument("--collection-date", required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    try:
        historical_batch(args.input, args.source_run_id, args.source_attempt,
                         args.collection_date, clock=clock)
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1
    # Reuse the same schema, three tracking columns and atomic daily receipt.
    # The publisher defaults to dry-run and obtains Google credentials only
    # when explicitly requested. It never overwrites an accepted daily snapshot.
    return sheets.main(["--input", str(args.input)] + (["--publish"] if args.publish else []))


if __name__ == "__main__":
    raise SystemExit(main())

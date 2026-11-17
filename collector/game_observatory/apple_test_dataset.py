"""Manual, storage-independent Adventure Top 50 test extraction.

This entry point deliberately fixes the collection scope and never invokes
the diagnostic CLI, tracked-game retention, or any database integration.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .apple import FIELDS, MARKETS, STATUS_FIELDS, collect, write_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/apple-test"))
    args = parser.parse_args(argv)
    rows, statuses = collect(
        countries=MARKETS,
        genres=("adventure",),
        feed_types=("top-grossing",),
        depth=50,
        full_chart=True,
        pause_seconds=0.25,
    )
    # Always publish both CSVs, even when every market is empty or failed.
    write_csv(args.output / "apple_rankings.csv", rows, FIELDS)
    write_csv(args.output / "apple_statuses.csv", statuses, STATUS_FIELDS)
    print(json.dumps({
        "collection_mode": "full_chart",
        "markets": list(MARKETS),
        "genre_id": 7002,
        "requested_depth": 50,
        "observations": len(rows),
        "feed_requests": len(statuses),
        "statuses": {state: sum(s["status"] == state for s in statuses)
                     for state in ("ok", "partial", "empty", "error")},
        "output_directory": str(args.output),
    }))
    # Partial/empty charts are reported as source outcomes, not job failures.
    # Request/parse errors fail the job after the CSVs have been written.
    return 1 if any(s["status"] == "error" for s in statuses) else 0


if __name__ == "__main__":
    raise SystemExit(main())

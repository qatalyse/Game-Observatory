import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from game_observatory.apple import (
    FIELDS, STATUS_FIELDS, MARKETS, collect, feed_url, parse_entries, write_csv,
)


def payload(ids=("123", "456")):
    return {"feed": {"entry": [
        {
            "id": {"attributes": {"im:id": game_id}},
            "im:name": {"label": f"Game {game_id}"},
            "im:artist": {"label": "Studio"},
            "link": {"attributes": {"href": f"https://apps.apple.com/app/id{game_id}"}},
        } for game_id in ids
    ]}}


class AppleCollectorTests(unittest.TestCase):
    def test_all_ten_markets_and_genre_endpoint(self):
        self.assertEqual(len(MARKETS), 10)
        self.assertEqual(
            feed_url("SG", "role-playing", 20),
            "https://itunes.apple.com/sg/rss/topfreeapplications/limit=20/genre=7014/json",
        )

    def test_normalized_entries_keep_order(self):
        entries = parse_entries(payload(), 20)
        self.assertEqual([(e["app_id"], e["rank"]) for e in entries], [("123", 1), ("456", 2)])

    def test_invalid_entries_do_not_become_partial_export(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            parse_entries(payload(("123", "123")), 20)
        with self.assertRaisesRegex(ValueError, "Missing"):
            parse_entries({"feed": {"entry": [{"im:name": {"label": "Bad"}}]}}, 20)
        with self.assertRaises(ValueError):
            parse_entries(payload(), 1)

    def test_partial_and_error_are_explicit(self):
        def fake_fetch(url):
            if "genre=7001" in url:
                raise OSError("offline")
            return payload()
        fixed = lambda: datetime(2026, 11, 17, tzinfo=timezone.utc)
        rows, statuses = collect(
            countries=("SG",), genres=("adventure", "action"),
            fetch=fake_fetch, clock=fixed,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual([s["status"] for s in statuses], ["partial", "error"])
        self.assertTrue(all(r["retrieved_at_utc"] == "2026-11-17T00:00:00+00:00" for r in rows))
        self.assertEqual({r["rank"] for r in rows}, {1, 2})
        self.assertEqual(len({r["snapshot_id"] for r in rows}), 1)
        self.assertNotEqual(statuses[0]["snapshot_id"], statuses[1]["snapshot_id"])

    def test_csv_files_have_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "sample.csv"
            write_csv(file, [], FIELDS)
            with file.open(newline="", encoding="utf-8") as handle:
                self.assertEqual(next(csv.reader(handle)), list(FIELDS))
            write_csv(file, [], STATUS_FIELDS)
            self.assertTrue(file.exists())


if __name__ == "__main__":
    unittest.main()

import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from game_observatory.apple import (
    CHARTS, FIELDS, GENRES, MARKETS, STATUS_FIELDS, collect, feed_url,
    parse_entries, write_csv,
)


def payload(ids=("123", "456")):
    entries = []
    for app_id in ids:
        entries.append({
            "id": {"attributes": {"im:id": app_id}},
            "im:name": {"label": f"Game {app_id}"},
            "im:artist": {"label": "Studio", "attributes": {"href": "https://example.com"}},
            "im:releaseDate": {"label": "2026-11-01T00:00:00-07:00"},
            "im:image": [
                {"label": "small.png", "attributes": {"height": "53"}},
                {"label": "large.png", "attributes": {"height": "512"}},
            ],
            "im:price": {"label": "Free", "attributes": {"amount": "0.00", "currency": "SGD"}},
            "summary": {"label": "Sample game description"},
            "category": {"attributes": {"im:id": "7014", "label": "Role Playing"}},
            "im:contentType": {"label": "Application"},
            "im:rating": {"label": "12+"},
            "rights": {"label": "Copyright Studio"},
            "link": {"attributes": {"href": f"https://apps.apple.com/app/id{app_id}"}},
        })
    return {"feed": {"title": {"label": "Test feed"}, "updated": {"label": "2026-11-17T00:00:00Z"}, "entry": entries}}


class AppleCollectorTests(unittest.TestCase):
    def test_all_markets_and_both_feed_types(self):
        self.assertEqual(len(MARKETS), 10)
        self.assertEqual(set(CHARTS), {"top-grossing", "new-applications"})
        self.assertEqual(
            feed_url("SG", "games", 20, "top-grossing"),
            "https://itunes.apple.com/sg/rss/topgrossingapplications/limit=20/genre=6014/json",
        )
        self.assertEqual(
            feed_url("SG", "role-playing", 20, "new-applications"),
            "https://itunes.apple.com/sg/rss/newapplications/limit=20/genre=7014/json",
        )

    def test_extracts_legacy_metadata_fields(self):
        grossing, meta = parse_entries(payload(), 20, "top-grossing")
        new_apps, _ = parse_entries(payload(), 20, "new-applications")
        self.assertEqual(grossing[0]["position_semantics"], "grossing_chart_rank")
        self.assertEqual(new_apps[0]["position_semantics"], "feed_order_not_verified_as_rank")
        self.assertEqual(grossing[0]["artwork_url"], "large.png")
        self.assertEqual(grossing[0]["price_currency"], "SGD")
        self.assertEqual(grossing[0]["category_id"], "7014")
        self.assertIn("updated", meta["feed_fields"])
        self.assertIn("im:releaseDate", meta["entry_fields"])

    def test_invalid_entries_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            parse_entries(payload(("123", "123")), 20, "top-grossing")
        with self.assertRaisesRegex(ValueError, "Missing"):
            parse_entries({"feed": {"entry": [{"im:name": {"label": "Bad"}}]}}, 20, "new-applications")
        with self.assertRaises(ValueError):
            parse_entries(payload(), 1, "top-grossing")
        accepted, _ = parse_entries(payload(), 1, "new-applications")
        self.assertEqual(len(accepted), 2)

    def test_collects_two_feeds_and_multiple_genres(self):
        calls = []
        fixed = lambda: datetime(2026, 11, 17, tzinfo=timezone.utc)
        rows, statuses = collect(
            countries=("SG",), genres=("games", "role-playing"),
            feed_types=("top-grossing", "new-applications"),
            fetch=lambda url: (calls.append(url) or (payload(), 200)), clock=fixed,
        )
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(statuses), 4)
        self.assertEqual(len(rows), 8)
        self.assertEqual({s["status"] for s in statuses}, {"partial", "ok"})
        self.assertEqual({s["http_status"] for s in statuses}, {200})
        self.assertEqual({r["feed_type"] for r in rows}, set(CHARTS.values()))
        self.assertEqual(
            {r["position_semantics"] for r in rows},
            {"grossing_chart_rank", "feed_order_not_verified_as_rank"},
        )

    def test_partial_and_error_statuses_are_explicit(self):
        def fake_fetch(url):
            if "genre=7001" in url:
                raise OSError("offline")
            return payload()
        fixed = lambda: datetime(2026, 11, 17, tzinfo=timezone.utc)
        rows, statuses = collect(
            countries=("SG",), genres=("adventure", "action"),
            feed_types=("top-grossing",), fetch=fake_fetch, clock=fixed,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual([s["status"] for s in statuses], ["partial", "error"])
        self.assertTrue(all(r["retrieved_at_utc"] == "2026-11-17T00:00:00+00:00" for r in rows))


    def test_new_applications_accepts_all_entries_above_requested_limit(self):
        ids = tuple(str(1000 + i) for i in range(104))
        fixed = lambda: datetime(2026, 11, 18, tzinfo=timezone.utc)
        rows, statuses = collect(
            countries=("SG",), genres=("games",),
            feed_types=("new-applications",), depth=20,
            fetch=lambda url: (payload(ids), 200), clock=fixed,
        )
        self.assertEqual(len(rows), 104)
        self.assertEqual(statuses[0]["returned_count"], 104)
        self.assertEqual(statuses[0]["status"], "ok")
        self.assertEqual(statuses[0]["limit_behavior"], "exceeded_but_accepted")
        self.assertEqual(rows[-1]["position"], 104)
        self.assertEqual(rows[0]["position_semantics"], "feed_order_not_verified_as_rank")

    def test_top_grossing_remains_strict_at_requested_depth(self):
        ids = tuple(str(2000 + i) for i in range(21))
        rows, statuses = collect(
            countries=("SG",), genres=("games",),
            feed_types=("top-grossing",), depth=20,
            fetch=lambda url: (payload(ids), 200),
        )
        self.assertEqual(rows, [])
        self.assertEqual(statuses[0]["status"], "error")
        self.assertIn("exceeding requested depth", statuses[0]["error"])

    def test_csv_files_have_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "sample.csv"
            write_csv(file, [], FIELDS)
            with file.open(newline="", encoding="utf-8") as handle:
                self.assertEqual(next(csv.reader(handle)), list(FIELDS))
            write_csv(file, [], STATUS_FIELDS)
            self.assertTrue(file.exists())


def _entry_fields(sample):
    return set(sample["feed"]["entry"][0])


if __name__ == "__main__":
    unittest.main()

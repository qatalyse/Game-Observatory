import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from game_observatory import apple_test_dataset
from game_observatory.apple import FIELDS, MARKETS, STATUS_FIELDS, collect, main
from test_apple import payload


class FullChartTests(unittest.TestCase):
    def collect_chart(self, response, **kwargs):
        return collect(
            countries=("SG",), genres=("adventure",),
            feed_types=("top-grossing",), depth=50, full_chart=True,
            fetch=lambda url: (response, 200), **kwargs,
        )

    def test_retains_500_rows_regardless_of_tracked_title_presence(self):
        for tracked in (set(), {"1000"}, {"999999"}):
            with self.subTest(tracked=tracked):
                calls = []

                def fetch(url):
                    calls.append(url)
                    return payload(tuple(str(1000 + n) for n in range(50))), 200

                rows, statuses = collect(
                    countries=MARKETS, genres=("adventure",),
                    feed_types=("top-grossing",), depth=50,
                    full_chart=True, tracked_app_ids=tracked, fetch=fetch,
                )
                self.assertEqual(len(calls), 10)
                self.assertEqual(set(calls), {
                    f"https://itunes.apple.com/{m.lower()}/rss/topgrossingapplications/limit=50/genre=7002/json"
                    for m in MARKETS
                })
                self.assertEqual(len(rows), 500)
                self.assertEqual([s["country"] for s in statuses], list(MARKETS))
                self.assertEqual(len({s["snapshot_id"] for s in statuses}), 10)
                for status in statuses:
                    market_rows = [r for r in rows if r["country"] == status["country"]]
                    self.assertEqual([r["position"] for r in market_rows], list(range(1, 51)))
                    self.assertEqual({r["snapshot_id"] for r in market_rows}, {status["snapshot_id"]})
                    self.assertEqual(status["status"], "ok")
                    self.assertEqual(status["limit_behavior"], "full_chart_returned")
                    self.assertEqual(status["source_count"], 50)
                    self.assertEqual(status["returned_count"], 50)
                    self.assertEqual(status["snapshot_depth"], 50)
                    self.assertEqual(status["tracked_app_ids_found"], "")

    def test_partial_chart_retains_all_fetched_rows_and_original_ranks(self):
        rows, statuses = self.collect_chart(payload(tuple(str(1000 + n) for n in range(23))))
        self.assertEqual([r["position"] for r in rows], list(range(1, 24)))
        self.assertEqual(statuses[0]["status"], "partial")
        self.assertEqual(statuses[0]["returned_count"], 23)
        self.assertEqual(statuses[0]["source_count"], 23)
        self.assertEqual(statuses[0]["snapshot_depth"], 23)

    def test_all_ten_outcomes_survive_mixed_source_failures(self):
        def fetch(url):
            market = url.split("/")[3].upper()
            if market == "US":
                raise HTTPError(url, 503, "Unavailable", None, None)
            if market == "JP":
                raise URLError("offline")
            if market == "KR":
                raise TimeoutError("timed out")
            if market == "CN":
                return {"unexpected": []}, 200
            if market == "MY":
                return payload(()), 200
            if market == "TH":
                return payload(("123",)), 200
            return payload(tuple(str(1000 + n) for n in range(50))), 200

        rows, statuses = collect(
            countries=MARKETS, genres=("adventure",),
            feed_types=("top-grossing",), full_chart=True, fetch=fetch,
        )
        self.assertEqual(len(rows), 201)
        self.assertEqual([s["status"] for s in statuses],
                         ["ok", "error", "error", "error", "error", "empty", "partial", "ok", "ok", "ok"])
        self.assertEqual(statuses[1]["http_status"], 503)
        self.assertIn("HTTP 503", statuses[1]["error"])
        self.assertIn("offline", statuses[2]["error"])
        self.assertEqual(statuses[4]["http_status"], 200)
        for status in statuses:
            self.assertEqual(status["returned_count"],
                             sum(r["country"] == status["country"] for r in rows))

    def test_invalid_or_oversized_charts_still_rejected(self):
        for response in (payload(("123", "123")),
                         payload(tuple(str(n) for n in range(51))),
                         {"feed": {"entry": [{"im:name": {"label": "Bad"}}]}}):
            with self.subTest(response=response):
                rows, statuses = self.collect_chart(response)
                self.assertEqual(rows, [])
                self.assertEqual(statuses[0]["status"], "error")
                self.assertTrue(statuses[0]["error"])

    def test_full_chart_mode_cannot_change_discovery_feed_semantics(self):
        with self.assertRaisesRegex(ValueError, "only supports Top Grossing"):
            collect(full_chart=True)

    def test_diagnostic_cli_does_not_opt_into_full_chart_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("game_observatory.apple.collect", return_value=([], [])) as collector:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["--output", directory]), 0)
            self.assertNotIn("full_chart", collector.call_args.kwargs)


class TestDatasetCliTests(unittest.TestCase):
    def run_cli(self, fetch):
        # Exercise the real collector and CSV writer without network calls.
        def fixture_collect(**kwargs):
            return collect(**{**kwargs, "pause_seconds": 0}, fetch=fetch)

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(apple_test_dataset, "collect", side_effect=fixture_collect) as collector:
                with contextlib.redirect_stdout(io.StringIO()) as stdout:
                    result = apple_test_dataset.main(["--output", directory])
            self.assertEqual(collector.call_args.kwargs["countries"], MARKETS)
            self.assertTrue(collector.call_args.kwargs["full_chart"])
            self.assertEqual(collector.call_args.kwargs["genres"], ("adventure",))
            self.assertEqual(collector.call_args.kwargs["feed_types"], ("top-grossing",))
            self.assertEqual(collector.call_args.kwargs["depth"], 50)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()),
                             ["apple_rankings.csv", "apple_statuses.csv"])
            data = []
            for name, fields in (("apple_rankings.csv", FIELDS), ("apple_statuses.csv", STATUS_FIELDS)):
                with (Path(directory) / name).open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(reader.fieldnames, list(fields))
                    data.append(list(reader))
            return result, data[0], data[1], json.loads(stdout.getvalue())

    def test_csv_roundtrip_preserves_unicode_commas_quotes_and_newlines(self):
        def fetch(url):
            response = payload(("123",))
            response["feed"]["entry"][0]["im:name"]["label"] = '冒険, "Game"\nNext line'
            return response, 200

        result, rows, statuses, report = self.run_cli(fetch)
        self.assertEqual(result, 0)
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0]["title"], '冒険, "Game"\nNext line')
        self.assertEqual(len(statuses), 10)
        self.assertEqual({s["status"] for s in statuses}, {"partial"})
        self.assertEqual(report["statuses"]["partial"], 10)

    def test_all_errors_write_header_only_rankings_and_ten_error_records_then_fail(self):
        def fetch(url):
            raise OSError('offline, "try later"\nnetwork unavailable')

        result, rows, statuses, report = self.run_cli(fetch)
        self.assertEqual(result, 1)
        self.assertEqual(rows, [])
        self.assertEqual([s["country"] for s in statuses], list(MARKETS))
        self.assertTrue(all(s["error"] == 'OSError: offline, "try later"\nnetwork unavailable' for s in statuses))
        self.assertEqual(report["statuses"]["error"], 10)

    def test_empty_feeds_still_write_ten_statuses_and_succeed(self):
        result, rows, statuses, report = self.run_cli(lambda url: (payload(()), 200))
        self.assertEqual(result, 0)
        self.assertEqual(rows, [])
        self.assertEqual(len(statuses), 10)
        self.assertEqual(report["statuses"]["empty"], 10)


if __name__ == "__main__":
    unittest.main()

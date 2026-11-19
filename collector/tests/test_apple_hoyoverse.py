import contextlib
from copy import deepcopy
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from game_observatory import apple_hoyoverse as tracker
from game_observatory.apple import GENRES, MARKETS, TRACKED_GAME_IDS
from test_apple import payload

FIXED = datetime(2026, 11, 19, tzinfo=timezone.utc)
GENSHIN = "1517783697"
STAR_RAIL = "1599719154"


class TargetedTests(unittest.TestCase):
    def collect(self, response=None, fetch=None):
        # Generic response/error tests retain coverage of the legacy default-ID schema.
        config = tracker.load_config()
        for genre in config["genres"]:
            for game in genre["games"]:
                for field in ("market_app_ids", "market_mapping_sources", "market_mapping_notes"):
                    game.pop(field, None)
        return tracker.collect(
            config, fetch=fetch or (lambda url: (response, 200)),
            clock=lambda: FIXED, run_id="fixture-run",
        )

    def test_config_matches_existing_markets_genres_and_known_ids(self):
        config = tracker.load_config()
        self.assertEqual(config["requested_depth"], 100)
        self.assertEqual(MARKETS, ("SG", "US", "JP", "KR", "CN", "MY", "TH", "ID", "PH", "VN"))
        self.assertEqual([(g["genre"], g["genre_id"]) for g in config["genres"]],
                         [("adventure", 7002), ("role-playing", 7014), ("action", 7001)])
        adventure, rpg, action = config["genres"]
        self.assertEqual([g["app_id"] for g in adventure["games"]], [GENSHIN, STAR_RAIL])
        self.assertEqual([g["app_id"] for g in rpg["games"]],
                         [GENSHIN, STAR_RAIL, "1606356401", "1336342304", "1517957388"])
        self.assertEqual([g["app_id"] for g in action["games"]], ["1606356401", "1336342304"])
        self.assertTrue(TRACKED_GAME_IDS <= {g["app_id"] for g in rpg["games"]})
        self.assertTrue(all(GENRES[g["genre"]] == g["genre_id"] for g in config["genres"]))

    def test_invalid_config_fails_before_any_request(self):
        original = tracker.load_config()
        for change in (
            lambda c: c.update(requested_depth=101),
            lambda c: c.update(requested_depth=True),
            lambda c: c["genres"][0].update(genre_id=7014),
            lambda c: c["genres"].append(deepcopy(c["genres"][0])),
            lambda c: c["genres"][0]["games"].append(deepcopy(c["genres"][0]["games"][0])),
            lambda c: c["genres"][0]["games"][0].update(app_id="bad"),
            lambda c: c["genres"][0]["games"][0].update(title=""),
        ):
            with self.subTest(change=change):
                config = deepcopy(original)
                change(config)
                with self.assertRaises(ValueError):
                    tracker.collect(config, fetch=lambda u: self.fail("must not fetch"))

    def test_30_requests_90_rows_exact_id_matching_original_ranks_and_join(self):
        ids = [str(10000 + n) for n in range(100)]
        ids[39], ids[99] = GENSHIN, STAR_RAIL
        response = payload(ids)
        # Localized titles cannot affect ID matching; identical names cannot match an ID.
        response["feed"]["entry"][0]["im:name"]["label"] = "Genshin Impact"
        response["feed"]["entry"][39]["im:name"]["label"] = '原神, "世界"\n冒険'
        calls = []

        def fetch(url):
            calls.append(url)
            return response, 200

        rows, statuses = self.collect(fetch=fetch)
        self.assertEqual(len(calls), 30)
        self.assertEqual(set(calls), {
            f"https://itunes.apple.com/{m.lower()}/rss/topgrossingapplications/limit=100/genre={g}/json"
            for m in MARKETS for g in (7002, 7014, 7001)
        })
        self.assertEqual(len(rows), 90)
        self.assertEqual(len(statuses), 30)
        required = {"run_id", "snapshot_id", "retrieved_at_utc", "country", "genre_id",
                    "app_id", "rank", "status", "chart_status", "coverage_depth",
                    "requested_depth", "source", "source_url", "http_status", "error"}
        self.assertTrue(required <= set(rows[0]))
        self.assertEqual(set(rows[0]), set(tracker.FIELDS))
        self.assertEqual(set(statuses[0]), set(tracker.STATUS_FIELDS))
        self.assertEqual(len({s["snapshot_id"] for s in statuses}), 30)
        self.assertEqual(len({(r["run_id"], r["country"], r["genre_id"], r["app_id"]) for r in rows}), 90)
        for s in statuses:
            self.assertEqual(s["chart_status"], "complete")
            self.assertTrue(s["chart_complete"])
            self.assertEqual(s["coverage_depth"], 100)
            matches = [r for r in rows if r["snapshot_id"] == s["snapshot_id"]]
            self.assertEqual(len(matches), {7002: 2, 7014: 5, 7001: 2}[s["genre_id"]])
            for r in matches:
                self.assertEqual({k: r[k] for k in tracker.COMMON_FIELDS},
                                 {k: s[k] for k in tracker.COMMON_FIELDS})
                self.assertEqual(r["retrieved_at_utc"], "2026-11-19T00:00:00+00:00")
                self.assertEqual(r["run_id"], "fixture-run")
                if r["app_id"] in (GENSHIN, STAR_RAIL):
                    self.assertEqual(r["status"], "ranked")
                    self.assertEqual(r["rank"], 40 if r["app_id"] == GENSHIN else 100)
                else:
                    self.assertEqual(r["status"], "outside-chart")
                    self.assertIsNone(r["rank"])
        self.assertEqual(rows[0]["observed_title"], '原神, "世界"\n冒険')
        self.assertFalse(any(r["rank"] == 101 for r in rows))

    def test_partial_keeps_observed_ranks_and_absence_unknown(self):
        rows, statuses = self.collect(payload(("123", GENSHIN)))
        self.assertEqual({s["chart_status"] for s in statuses}, {"partial"})
        self.assertEqual({s["coverage_depth"] for s in statuses}, {2})
        for row in rows:
            self.assertEqual(row["status"], "ranked" if row["app_id"] == GENSHIN else "unknown")
            self.assertEqual(row["rank"], 2 if row["app_id"] == GENSHIN else None)
            self.assertEqual(row["chart_status"], "partial")
        self.assertFalse(any(s["chart_complete"] for s in statuses))

    def test_empty_and_missing_entries_are_unknown_never_outside(self):
        for response in (payload(()), {"feed": {}}):
            with self.subTest(response=response):
                rows, statuses = self.collect(response)
                self.assertEqual(len(rows), 90)
                self.assertEqual({r["status"] for r in rows}, {"unknown"})
                self.assertEqual({s["chart_status"] for s in statuses}, {"empty"})
                self.assertTrue(all(r["rank"] is None for r in rows))

    def test_single_object_entry_is_partial(self):
        response = payload((GENSHIN,))
        response["feed"]["entry"] = response["feed"]["entry"][0]
        rows, statuses = self.collect(response)
        self.assertEqual({s["coverage_depth"] for s in statuses}, {1})
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[1]["status"], "unknown")

    def test_malformed_duplicate_oversize_and_non_numeric_are_errors(self):
        cases = [
            {}, {"feed": {"entry": None}}, payload(("123", "123")),
            payload(tuple(str(n) for n in range(101))),
            payload(("not-an-id",)),
            {"feed": {"entry": [{"im:name": {"label": "Missing ID"}}]}},
            {"feed": {"entry": [{"id": {"attributes": {"im:id": "123"}},
                                 "im:name": {"label": None}}]}},
        ]
        for response in cases:
            with self.subTest(response=response):
                rows, statuses = self.collect(response)
                self.assertEqual(len(rows), 90)
                self.assertEqual({r["status"] for r in rows}, {"error"})
                self.assertTrue(all(r["rank"] is None for r in rows))
                self.assertTrue(all(s["error"] and not s["chart_complete"] for s in statuses))

    def test_http_network_timeout_and_json_errors_do_not_stop_other_charts(self):
        def fetch(url):
            if "/us/" in url:
                raise HTTPError(url, 503, "unavailable", None, None)
            if "/jp/" in url:
                raise URLError("offline")
            if "/kr/" in url:
                raise TimeoutError("timeout")
            if "/cn/" in url:
                raise json.JSONDecodeError("bad JSON", "", 0)
            if "/my/" in url:
                return payload((GENSHIN,)), 500
            return payload((GENSHIN,)), 200

        rows, statuses = self.collect(fetch=fetch)
        self.assertEqual(len(rows), 90)
        self.assertEqual(len(statuses), 30)
        self.assertEqual(sum(s["chart_status"] == "error" for s in statuses), 15)
        self.assertEqual(next(s for s in statuses if s["country"] == "US")["http_status"], 503)
        self.assertEqual({r["status"] for r in rows if r["country"] == "US"}, {"error"})
        self.assertEqual({r["status"] for r in rows if r["country"] == "VN"}, {"ranked", "unknown"})

    def test_collect_has_no_file_writes_and_only_30_injected_requests(self):
        config = tracker.load_config()
        calls = []
        def fetch(url):
            calls.append(url)
            return payload(()), 200
        with patch("builtins.open", side_effect=AssertionError("unexpected file access")), \
             patch.object(Path, "open", side_effect=AssertionError("unexpected file access")), \
             patch("game_observatory.apple.urlopen", side_effect=AssertionError("unexpected network")):
            rows, statuses = tracker.collect(config, fetch=fetch)
        self.assertEqual(len(calls), 30)
        self.assertEqual((len(rows), len(statuses)), (90, 30))

    def test_csv_contract_errors_nulls_unicode_and_artifact_only_cli(self):
        def fetch(url):
            if "/us/" in url:
                raise OSError('offline, "retry"\nlater')
            response = payload((GENSHIN,))
            response["feed"]["entry"][0]["im:name"]["label"] = '原神, "世界"\n冒険'
            return response, 200

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(tracker, "fetch_json", side_effect=fetch), \
                 patch.dict("os.environ", {"GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "2",
                                           "DATABASE_URL": "must-not-be-used"}), \
                 contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(tracker.main(["--output", directory]), 1)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()),
                             ["apple_hoyoverse_chart_statuses.csv", "apple_hoyoverse_rankings.csv"])
            tables = []
            for filename, fields in (("apple_hoyoverse_rankings.csv", tracker.FIELDS),
                                     ("apple_hoyoverse_chart_statuses.csv", tracker.STATUS_FIELDS)):
                with (Path(directory) / filename).open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(reader.fieldnames, list(fields))
                    tables.append(list(reader))
            rows, statuses = tables
            self.assertEqual((len(rows), len(statuses)), (90, 30))
            self.assertEqual(rows[0]["observed_title"], '原神, "世界"\n冒険')
            self.assertEqual(rows[1]["rank"], "")
            self.assertEqual(rows[1]["status"], "unknown")
            self.assertEqual({r["run_id"] for r in rows}, {"github-12345-2"})
            self.assertEqual(next(s for s in statuses if s["country"] == "US")["error"],
                             'OSError: offline, "retry"\nlater')
            self.assertEqual(json.loads(stdout.getvalue())["chart_requests"], 30)

    def test_cli_all_empty_still_exports_and_returns_success(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(tracker, "fetch_json", return_value=(payload(()), 200)), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tracker.main(["--output", directory]), 0)
            with (Path(directory) / "apple_hoyoverse_rankings.csv").open(newline="", encoding="utf-8") as f:
                self.assertEqual({r["status"] for r in csv.DictReader(f)}, {"unknown"})

    def test_alternative_roster_config(self):
        config = tracker.load_config()
        config["genres"][0]["games"].append({"app_id": "9999", "title": "Future title"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roster.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            loaded = tracker.load_config(path)
        rows, statuses = tracker.collect(loaded, fetch=lambda u: (payload(()), 200))
        self.assertEqual((len(rows), len(statuses)), (100, 30))

    def test_workflow_is_manual_and_artifacts_survive_errors(self):
        workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/apple-hoyoverse-targeted.yml").read_text()
        triggers = workflow.split("on:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(triggers.strip(), "workflow_dispatch:")
        self.assertEqual(workflow.count("if: always()"), 2)
        self.assertEqual(workflow.count("actions/upload-artifact@v4"), 2)
        self.assertIn("contents: read", workflow)
        for forbidden in ("schedule:", "secrets.", "supabase", "tableau", "git push"):
            self.assertNotIn(forbidden, workflow.lower())


class RegionalListingTests(unittest.TestCase):
    def test_audited_regional_ids(self):
        games = {g["game_id"]: g for s in tracker.load_config()["genres"] for g in s["games"]}
        expected = {
            "genshin-impact": {"CN": "1467190251", "VN": "6451477469"},
            "honkai-star-rail": {"CN": "1523037824", "VN": "6451473600"},
            "zenless-zone-zero": {"CN": "1606359076", "VN": "6476137851"},
            "honkai-impact-3rd": {
                "SG": "1299582178", "US": "1336342304", "JP": "1172809651",
                "KR": "1286705196", "CN": "1143402987", "MY": "1299582178",
                "TH": "1299582178", "ID": "1299582178", "PH": "1299582178",
                "VN": "6448864292",
            },
            "tears-of-themis": {"CN": "1507310279", "VN": None},

        }
        for game_id, markets in expected.items():
            for country, app_id in markets.items():
                with self.subTest(game_id=game_id, country=country):
                    self.assertEqual(tracker.market_listing(games[game_id], country)[0], app_id)
        self.assertEqual(set(games), {"genshin-impact", "honkai-star-rail", "zenless-zone-zero", "honkai-impact-3rd", "tears-of-themis"})
        self.assertEqual(tracker.market_listing(games["genshin-impact"], "US"),
                         (GENSHIN, "default"))

    def test_reported_cn_and_vn_ranks_are_offline_regression_fixtures(self):
        # These reproduce the reported positions, not a claim about live rankings.
        fixture_ranks = {
            ("CN", "7002"): {"1523037824": 1, "1467190251": 2},
            ("CN", "7014"): {"1523037824": 3, "1467190251": 5,
                             "1143402987": 45, "1507310279": 60, "1606359076": 12},
            ("VN", "7002"): {"6451473600": 9, "6451477469": 14},
            ("VN", "7014"): {"6451473600": 7, "6451477469": 11,
                             "6448864292": 40, "6476137851": 19},
            ("CN", "7001"): {"1606359076": 12, "1143402987": 20},
            ("VN", "7001"): {"6476137851": 19, "6448864292": 40},
        }
        calls = []
        def fetch(url):
            calls.append(url)
            country = url.split("/")[3].upper()
            genre_id = url.split("/genre=")[1].split("/")[0]
            ids = [str(900000 + n) for n in range(100)]
            for app_id, rank in fixture_ranks.get((country, genre_id), {}).items():
                ids[rank - 1] = app_id
            return payload(ids), 200

        rows, statuses = tracker.collect(fetch=fetch, run_id="regional-regression")
        self.assertEqual((len(calls), len(statuses), len(rows)), (30, 30, 90))
        self.assertEqual(len(set(calls)), 30)
        self.assertEqual(len({(r["country"], r["genre_id"], r["game_id"]) for r in rows}), 90)
        for row in rows:
            ranks = fixture_ranks.get((row["country"], str(row["genre_id"])), {})
            if row["app_id"] in ranks:
                self.assertEqual(row["status"], "ranked")
                self.assertEqual(row["rank"], ranks[row["app_id"]])
                self.assertEqual(row["mapping_status"], "market-override")
        self.assertEqual({r["game_id"] for r in rows},
                         {"genshin-impact", "honkai-star-rail", "zenless-zone-zero",
                          "honkai-impact-3rd", "tears-of-themis"})
        self.assertEqual({r["game_id"] for r in rows if r["genre_id"] == 7001},
                         {"zenless-zone-zero", "honkai-impact-3rd"})
        self.assertEqual({r["game_id"] for r in rows if r["genre_id"] == 7014},
                         {"genshin-impact", "honkai-star-rail", "zenless-zone-zero",
                          "honkai-impact-3rd", "tears-of-themis"})
        star_rows = [r for r in rows if r["game_id"] == "honkai-star-rail"]
        self.assertEqual({r["canonical_app_id"] for r in star_rows}, {STAR_RAIL})
        self.assertEqual({r["app_id"] for r in star_rows},
                         {STAR_RAIL, "1523037824", "6451473600"})

    def test_unresolved_listing_never_falls_back_or_claims_outside_chart(self):
        ids = [str(800000 + n) for n in range(100)]
        ids[0] = "1606356401"  # Even a default-ID hit must not override an explicit null.
        config = tracker.load_config()
        for spec in config["genres"]:
            for game in spec["games"]:
                if game["game_id"] == "zenless-zone-zero":
                    game["market_app_ids"]["VN"] = None
                    game["market_mapping_sources"].pop("VN")
                    game["market_mapping_notes"] = {"VN": "Unresolved custom-roster fixture"}
        rows, statuses = tracker.collect(config, fetch=lambda u: (payload(ids), 200))
        row = next(r for r in rows if r["country"] == "VN" and r["game_id"] == "zenless-zone-zero")
        self.assertEqual(row["chart_status"], "complete")
        self.assertEqual(row["status"], "unknown")
        self.assertEqual(row["status_reason"], "unresolved_market_listing")
        self.assertEqual(row["mapping_status"], "unresolved")
        self.assertIsNone(row["app_id"])
        self.assertIsNone(row["rank"])
        self.assertIn("fixture", row["mapping_note"])
        status = next(s for s in statuses if s["snapshot_id"] == row["snapshot_id"])
        self.assertIn("zenless-zone-zero", status["unresolved_game_ids"].split(";"))


    def test_cn_themis_at_rank_99_and_100_is_found_in_roleplaying_games_payload(self):
        # Synthetic positions test both chart boundaries. The user's isolated
        # payload identifies the app/category but does not establish an exact rank.
        for rank in (99, 100):
            with self.subTest(rank=rank):
                calls = []
                def fetch(url):
                    calls.append(url)
                    ids = [str(600000 + n) for n in range(100)]
                    if "/cn/" in url and "/genre=7014/" in url:
                        ids[rank - 1] = "1507310279"
                    response = payload(ids, category_id="6014")
                    if "1507310279" in ids:
                        entry = response["feed"]["entry"][rank - 1]
                        entry["im:name"]["label"] = "未定事件簿"
                        entry["id"]["attributes"]["im:bundleId"] = "com.miHoYo.wd"
                    return response, 200
                rows, statuses = tracker.collect(fetch=fetch)
                row = next(r for r in rows if r["country"] == "CN"
                           and r["genre_id"] == 7014 and r["game_id"] == "tears-of-themis")
                self.assertEqual((row["app_id"], row["rank"], row["status"]),
                                 ("1507310279", rank, "ranked"))
                self.assertEqual(row["observed_title"], "未定事件簿")
                self.assertEqual(row["coverage_depth"], 100)
                self.assertEqual({r["genre_id"] for r in rows if r["game_id"] == "tears-of-themis"}, {7014})
                self.assertEqual(len(calls), 30)
                self.assertEqual({url.split("/genre=")[1].split("/")[0] for url in calls},
                                 {"7001", "7002", "7014"})
                self.assertEqual((len(rows), len(statuses)), (90, 30))

    def test_override_is_market_specific_and_never_matches_global_id_in_cn(self):
        ids = [str(700000 + n) for n in range(100)]
        ids[0], ids[4] = GENSHIN, "1467190251"
        rows, _ = tracker.collect(fetch=lambda u: (payload(ids), 200))
        cn = next(r for r in rows if r["country"] == "CN" and r["game_id"] == "genshin-impact")
        us = next(r for r in rows if r["country"] == "US" and r["game_id"] == "genshin-impact")
        self.assertEqual((cn["app_id"], cn["rank"]), ("1467190251", 5))
        self.assertEqual((us["app_id"], us["rank"]), (GENSHIN, 1))
        self.assertEqual(cn["game_id"], us["game_id"])
        self.assertEqual(cn["canonical_app_id"], us["canonical_app_id"])

    def test_partial_and_error_semantics_survive_regional_matching(self):
        def fetch(url):
            if "/cn/" in url:
                return payload(("1523037824",)), 200
            if "/vn/" in url:
                raise OSError("offline")
            return payload(()), 200
        rows, statuses = tracker.collect(fetch=fetch)
        cn_star = next(r for r in rows if r["country"] == "CN" and r["game_id"] == "honkai-star-rail")
        cn_genshin = next(r for r in rows if r["country"] == "CN" and r["game_id"] == "genshin-impact")
        self.assertEqual((cn_star["rank"], cn_star["status"], cn_star["chart_status"]), (1, "ranked", "partial"))
        self.assertEqual((cn_genshin["rank"], cn_genshin["status"]), (None, "unknown"))
        self.assertEqual({r["status"] for r in rows if r["country"] == "VN"}, {"error"})
        self.assertEqual(len(statuses), 30)

    def test_invalid_market_config_rejected_before_fetch(self):
        original = tracker.load_config()
        for change in (
            lambda c: c["genres"][0]["games"][0]["market_app_ids"].update(ZZ="123"),
            lambda c: c["genres"][0]["games"][0]["market_app_ids"].update(CN=123),
            lambda c: c["genres"][0]["games"][0].update(game_id=""),
            lambda c: c["genres"][0]["games"][0]["market_app_ids"].update(CN="1523037824"),
            lambda c: c["genres"][0]["games"][0]["market_app_ids"].update(CN="111"),
            lambda c: c["genres"][0]["games"][0].update(market_mapping_sources={"US": "unexpected"}),
        ):
            with self.subTest(change=change):
                config = deepcopy(original)
                change(config)
                with self.assertRaises(ValueError):
                    tracker.collect(config, fetch=lambda u: self.fail("invalid config fetched"))

    def test_regional_csv_fields_keep_stable_identity_and_blank_unknown_rank(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(tracker, "fetch_json", return_value=(payload(()), 200)), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tracker.main(["--output", directory]), 0)
            with (Path(directory) / "apple_hoyoverse_rankings.csv").open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                self.assertTrue({"game_id", "canonical_app_id", "mapping_status",
                                 "mapping_source_url", "mapping_note", "status_reason"} <= set(reader.fieldnames))
                rows = list(reader)
        cn = next(r for r in rows if r["country"] == "CN" and r["game_id"] == "genshin-impact")
        vn_zzz = next(r for r in rows if r["country"] == "VN" and r["game_id"] == "zenless-zone-zero")
        self.assertEqual((cn["app_id"], cn["canonical_app_id"]), ("1467190251", GENSHIN))
        self.assertEqual((vn_zzz["app_id"], vn_zzz["rank"], vn_zzz["status"]), ("6476137851", "", "unknown"))
        self.assertEqual(len(rows), 90)


if __name__ == "__main__":
    unittest.main()

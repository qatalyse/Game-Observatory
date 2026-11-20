"""Offline Steam CSV validation and atomic Sheets publication tests."""
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

from game_observatory import steam, steam_test_dataset as exporter, steam_sheets as sheets
from game_observatory import apple_sheets
from test_apple_sheets import FakeSheets


def fixture(day=20, mode="ok", calls=None):
    ids = list(steam.GAMES)
    def fetch(url):
        if calls is not None:
            calls.append(url)
        app = url.split("appid=")[1]
        if mode == "error" and app == ids[1]:
            raise TimeoutError()
        if mode == "unavailable" or (mode == "mixed" and app == ids[1]):
            return {"response": {"result": 42}}, 200
        return {"response": {"result": 1, "player_count": 0 if app == ids[0] else 1234}}, 200
    result = steam.collect(fetch=fetch, clock=lambda: datetime(2026, 11, day, 1, 17, tzinfo=timezone.utc))
    def strings(rows, fields):
        out = io.StringIO(newline="")
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return list(csv.DictReader(io.StringIO(out.getvalue())))
    statuses = result["results"]
    return (strings([r for r in statuses if r["status"] == "ok"], exporter.PLAYER_FIELDS),
            strings(statuses, exporter.STATUS_FIELDS))


def save(directory, players, statuses):
    exporter.write_csv(directory / "steam_players.csv", players, exporter.PLAYER_FIELDS)
    exporter.write_csv(directory / "steam_statuses.csv", statuses, exporter.STATUS_FIELDS)


class ValidationTests(unittest.TestCase):
    def test_full_current_roster_source_requests_and_csv_schema(self):
        calls = []
        players, statuses = fixture(calls=calls)
        self.assertEqual(len(calls), len(steam.GAMES))
        self.assertEqual(set(calls), {steam.player_url(app) for app in steam.GAMES})
        self.assertIn(steam.player_url("4019220"), calls)
        self.assertIn(steam.player_url("1401590"), calls)
        batch = sheets.prepare(players, statuses)
        self.assertEqual(len(batch["players"]), len(steam.GAMES))
        self.assertEqual(len(batch["statuses"]), len(steam.GAMES))
        self.assertEqual(batch["publication_key"], "steam-players:2026-11-20")
        self.assertEqual(len({r["record_key"] for r in batch["statuses"]}), len(steam.GAMES))
        self.assertEqual(sheets.PLAYER_HEADERS, sheets.PREFIX + exporter.PLAYER_FIELDS)
        self.assertEqual(sheets.STATUS_HEADERS, sheets.PREFIX + exporter.STATUS_FIELDS)
        self.assertEqual((len(sheets.PLAYER_HEADERS), len(sheets.STATUS_HEADERS)), (12, 17))

    def test_collection_date_uses_actual_retrieval_in_singapore(self):
        players, statuses = fixture()
        for row in players + statuses:
            row["started_at_utc"] = "2026-11-19T16:59:59Z"
            row["retrieved_at_utc"] = "2026-11-19T17:00:00Z"
        self.assertEqual(sheets.prepare(players, statuses)["collection_date"], "2026-11-20")

    def test_missing_duplicate_mixed_or_spoofed_batches_rejected(self):
        original = fixture()
        changes = [
            lambda p, s: s.pop(),
            lambda p, s: s.append(deepcopy(s[0])),
            lambda p, s: s[0].update(app_id="99999"),
            lambda p, s: s[0].update(title="wrong"),
            lambda p, s: s[0].update(source="wrong"),
            lambda p, s: s[0].update(source_url="https://example.com"),
            lambda p, s: s[0].update(snapshot_id=""),
            lambda p, s: s[0].update(snapshot_id=s[1]["snapshot_id"]),
            lambda p, s: s[0].update(run_id="different"),
            lambda p, s: s[0].update(run_id=""),
            lambda p, s: s[0].update(retrieved_at_utc="2026-11-21T01:17:00Z"),
            lambda p, s: s[0].update(retrieved_at_utc="2026-11-20T09:17:00+08:00"),
            lambda p, s: s[0].update(retrieved_at_utc="2026-11-20T01:17:00"),
            lambda p, s: s[0].update(retrieved_at_utc="2026-11-19T01:17:00Z"),
            lambda p, s: s[0].update(extra="field"),
            lambda p, s: s[0].pop("status"),
            lambda p, s: s[0].update(player_count=None),
        ]
        for change in changes:
            with self.subTest(change=change):
                players, statuses = deepcopy(original)
                change(players, statuses)
                with self.assertRaises(ValueError):
                    sheets.prepare(players, statuses)

    def test_invalid_counts_codes_states_and_success_metadata_rejected(self):
        for field, values in {
            "player_count": ("", "-1", "1.5", "True", "null"),
            "http_status": ("", "201", "503", "999"),
            "steam_result": ("", "42", "1.0"),
            "status": ("unknown", ""),
            "error_code": ("timeout",),
            "error": ("failed",),
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    players, statuses = fixture()
                    statuses[0][field] = value
                    with self.assertRaises(ValueError):
                        sheets.prepare(players, statuses)

    def test_player_projection_must_exactly_match_successful_statuses(self):
        for change in (
            lambda p: p.pop(),
            lambda p: p.append(deepcopy(p[0])),
            lambda p: p[0].update(player_count="777"),
            lambda p: p[0].update(snapshot_id="mismatch"),
            lambda p: p[0].update(extra="field"),
        ):
            players, statuses = fixture()
            change(players)
            with self.assertRaises(ValueError):
                sheets.prepare(players, statuses)

    def test_unavailable_and_zero_are_distinct_and_errors_block_before_access(self):
        players, statuses = fixture(mode="mixed")
        batch = sheets.prepare(players, statuses)
        self.assertEqual(players[0]["player_count"], "0")
        self.assertEqual((statuses[1]["status"], statuses[1]["player_count"]), ("unavailable", ""))
        self.assertEqual(batch["source_errors"], 0)
        for update in ({"player_count": "0"}, {"steam_result": "1"}, {"http_status": "500"},
                       {"error_code": ""}, {"error": ""}):
            changed = deepcopy(statuses)
            changed[1].update(update)
            with self.assertRaises(ValueError):
                sheets.prepare(players, changed)
        client = FakeSheets()
        batch = sheets.prepare(*fixture(mode="error"))
        with self.assertRaisesRegex(ValueError, "request/parse"):
            sheets.publish(client, batch)
        self.assertEqual((client.reads, client.writes), (0, []))

    def test_csv_headers_and_ragged_rows_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            for text in ("wrong\nvalue\n", "a,b\none\n", "a,b\none,two,three\n"):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    sheets.read_csv(path, ("a", "b"))

    def test_dry_run_reads_only_csvs_without_authentication_or_new_files(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            save(directory, *fixture(mode="mixed"))
            before = {p.name: p.read_bytes() for p in directory.iterdir()}
            with patch.object(sheets.GoogleSheets, "authenticated") as auth:
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(sheets.main(["--input", str(directory)]), 0)
                auth.assert_not_called()
            report = json.loads(output.getvalue())
            self.assertTrue(report["ready_for_publish"])
            self.assertEqual(report["status_rows"], len(steam.GAMES))
            self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()}, before)

    def test_errors_fail_dry_run_and_publish_before_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            save(Path(directory), *fixture(mode="error"))
            for flags in ([], ["--publish", "--spreadsheet-id", "steam-id"]):
                with patch.object(sheets.GoogleSheets, "authenticated") as auth:
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(sheets.main(["--input", directory, *flags]), 1)
                    auth.assert_not_called()

    def test_explicit_publish_uses_only_steam_destination_and_closes_session(self):
        with tempfile.TemporaryDirectory() as directory:
            save(Path(directory), *fixture())
            with patch.dict("os.environ", {"GOOGLE_SHEETS_SPREADSHEET_ID": "hoyo-id"}, clear=True):
                with patch.object(sheets.GoogleSheets, "authenticated") as auth:
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(sheets.main(["--input", directory, "--publish"]), 1)
                    auth.assert_not_called()
            client = FakeSheets()
            with patch.dict("os.environ", {"STEAM_SHEETS_SPREADSHEET_ID": "steam-id"}, clear=True):
                with patch.object(sheets.GoogleSheets, "authenticated", return_value=client) as auth:
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(sheets.main(["--input", directory, "--publish"]), 0)
                    auth.assert_called_once_with("steam-id")
                    client.session.close.assert_called_once_with()


class PublishingTests(unittest.TestCase):
    def batch(self, day=20, mode="ok"):
        return sheets.prepare(*fixture(day=day, mode=mode))

    def test_atomic_initialization_preserves_other_tabs_and_receipts(self):
        client = FakeSheets()
        client.state["sheets"] = [{"properties": {"title": "Sheet1", "sheetId": 0}}]
        client.tables["Sheet1"] = [["untouched"]]
        client.state["developerMetadata"] = [
            {"metadataId": 1020261120, "metadataKey": apple_sheets.MARKER_KEY, "metadataValue": "hoyo"}]
        self.assertEqual(sheets.publish(client, self.batch())["status"], "published")
        self.assertEqual(len(client.writes), 1)
        self.assertEqual(client.tables["Sheet1"], [["untouched"]])
        self.assertEqual(client.tables[sheets.DEFAULT_PLAYERS_TAB][0], list(sheets.PLAYER_HEADERS))
        self.assertEqual(client.tables[sheets.DEFAULT_STATUSES_TAB][0], list(sheets.STATUS_HEADERS))
        self.assertEqual(len(client.tables[sheets.DEFAULT_PLAYERS_TAB]), len(steam.GAMES) + 1)
        self.assertEqual(len(client.state["developerMetadata"]), 2)
        self.assertEqual(client.state["developerMetadata"][1]["metadataKey"], sheets.MARKER_KEY)

    def test_first_snapshot_wins_and_next_date_appends(self):
        client = FakeSheets()
        sheets.publish(client, self.batch())
        before = deepcopy(client.tables)
        batch = self.batch(mode="unavailable")
        self.assertEqual(sheets.publish(client, batch)["status"], "already_published")
        self.assertEqual(client.tables, before)
        self.assertEqual(len(client.writes), 1)
        sheets.publish(client, self.batch(21))
        n = len(steam.GAMES) + 1
        self.assertEqual(client.tables[sheets.DEFAULT_PLAYERS_TAB][:n],
                         before[sheets.DEFAULT_PLAYERS_TAB])
        self.assertEqual(len(client.tables[sheets.DEFAULT_STATUSES_TAB]), 2 * len(steam.GAMES) + 1)

    def test_all_unavailable_creates_header_only_history_and_complete_statuses(self):
        client = FakeSheets()
        sheets.publish(client, self.batch(mode="unavailable"))
        self.assertEqual(len(client.tables[sheets.DEFAULT_PLAYERS_TAB]), 1)
        self.assertEqual(len(client.tables[sheets.DEFAULT_STATUSES_TAB]), len(steam.GAMES) + 1)
        self.assertTrue(all(r["appendCells"]["rows"] for r in client.writes[0] if "appendCells" in r))
        index = sheets.STATUS_HEADERS.index("player_count")
        self.assertTrue(all(r[index] == "" for r in client.tables[sheets.DEFAULT_STATUSES_TAB][1:]))

    def test_ambiguous_commit_and_concurrent_writer_do_not_duplicate(self):
        for mode in ("timeout_after_commit", "concurrent_commit"):
            client = FakeSheets()
            client.failures = [mode]
            self.assertEqual(sheets.publish(client, self.batch())["status"], "already_published")
            self.assertEqual(len(client.writes), 1)
            self.assertEqual(len(client.tables[sheets.DEFAULT_PLAYERS_TAB]), len(steam.GAMES) + 1)

    def test_transient_write_read_retries_and_exhaustion(self):
        client, pauses = FakeSheets(), []
        client.read_failures = [sheets.SheetsError()]
        client.failures = [sheets.SheetsError(429), sheets.SheetsError(503)]
        self.assertEqual(sheets.publish(client, self.batch(), sleep=pauses.append)["status"], "published")
        self.assertEqual(pauses, [2, 4, 8])
        self.assertEqual(len(client.tables[sheets.DEFAULT_PLAYERS_TAB]), len(steam.GAMES) + 1)
        client = FakeSheets()
        client.failures = [sheets.SheetsError(503)] * 4
        with self.assertRaises(sheets.SheetsError):
            sheets.publish(client, self.batch(), sleep=lambda _: None)
        self.assertEqual(client.tables, {})

    def test_permanent_failure_schema_and_receipt_collision_fail_closed(self):
        client = FakeSheets()
        client.failures = [sheets.SheetsError(403)]
        with self.assertRaises(sheets.SheetsError):
            sheets.publish(client, self.batch(), sleep=lambda _: self.fail("no retry"))
        self.assertEqual(client.tables, {})
        client = FakeSheets()
        sheets.publish(client, self.batch())
        client.tables[sheets.DEFAULT_PLAYERS_TAB][0][0] = "edited"
        with self.assertRaisesRegex(ValueError, "headers"):
            sheets.publish(client, self.batch(21))
        self.assertEqual(len(client.writes), 1)
        batch = self.batch()
        client = FakeSheets()
        client.state["developerMetadata"] = [
            {"metadataId": batch["marker_id"], "metadataKey": "other", "metadataValue": "collision"}]
        with self.assertRaisesRegex(ValueError, "collision"):
            sheets.publish(client, batch)
        self.assertEqual(client.writes, [])

    def test_missing_tab_invalid_names_and_atomic_rejection(self):
        client, batch = FakeSheets(), self.batch()
        sheets.publish(client, batch)
        client.state["sheets"] = []
        with self.assertRaisesRegex(ValueError, "missing"):
            sheets.publish(client, batch)
        for names in (("", "b"), ("same", "same"), ("bad/name", "b")):
            with self.assertRaises(ValueError):
                sheets.publish(FakeSheets(), batch, *names)
        client = FakeSheets()
        client.failures = ["reject"]
        with self.assertRaises(sheets.SheetsError):
            sheets.publish(client, batch)
        self.assertEqual(client.tables, {})
        self.assertEqual(client.state["developerMetadata"], [])

    def test_text_ids_literal_titles_numeric_counts_and_blank_unavailable_cells(self):
        app = next(iter(steam.GAMES))
        with patch.dict(steam.GAMES, {app: '=SUM(1,2) "冒険"\nline'}):
            batch = self.batch(mode="mixed")
        client = FakeSheets()
        sheets.publish(client, batch)
        appends = [r["appendCells"] for r in client.writes[0] if "appendCells" in r]
        cells = [c for a in appends for row in a["rows"] for c in row["values"]]
        self.assertFalse(any("formulaValue" in c.get("userEnteredValue", {}) for c in cells))
        self.assertTrue(any(c.get("userEnteredValue", {}).get("stringValue", "").startswith("=SUM") for c in cells))
        statuses = {row["values"][sheets.STATUS_HEADERS.index("app_id")]["userEnteredValue"]["stringValue"]: row["values"]
                    for row in appends[1]["rows"]}
        self.assertEqual(statuses[app][sheets.STATUS_HEADERS.index("player_count")],
                         {"userEnteredValue": {"numberValue": 0}})
        unavailable = list(steam.GAMES)[1]
        self.assertEqual(statuses[unavailable][sheets.STATUS_HEADERS.index("player_count")], {})
        self.assertEqual(statuses[unavailable][sheets.STATUS_HEADERS.index("steam_result")],
                         {"userEnteredValue": {"numberValue": 42}})


if __name__ == "__main__":
    unittest.main()

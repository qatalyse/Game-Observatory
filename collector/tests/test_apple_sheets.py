import contextlib
from copy import deepcopy
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from game_observatory import apple_hoyoverse as tracker
from game_observatory import apple_sheets as sheets
from game_observatory.apple import write_csv
from test_apple import payload


def strings(rows, fields):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return list(csv.DictReader(io.StringIO(output.getvalue())))


def fixture(day=19, error=False, config=None):
    config = tracker.load_config() if config is None else config
    specs = {str(g["genre_id"]): g for g in config["genres"]}
    def fetch(url):
        if error and "/us/" in url:
            raise OSError("offline")
        country = url.split("/")[3].upper()
        genre = url.split("/genre=")[1].split("/")[0]
        ids = [str(800000 + n) for n in range(100)]
        for index, game in enumerate(specs[genre]["games"]):
            app_id, _ = tracker.market_listing(game, country)
            if app_id:
                ids[index] = app_id
        result = payload(ids)
        result["feed"]["entry"][0]["im:name"]["label"] = '=SUM(1,2) 原神, "世界"'
        return result, 200
    rows, charts = tracker.collect(config, fetch=fetch,
        clock=lambda: datetime(2026, 11, day, 1, 17, tzinfo=timezone.utc), run_id=f"fixture-{day}")
    return strings(rows, tracker.FIELDS), strings(charts, tracker.STATUS_FIELDS)


class FakeSheets:
    """Atomic in-memory Sheets service, with uncertain-commit fault injection."""
    def __init__(self):
        self.state = {"sheets": [], "developerMetadata": []}
        self.tables = {}
        self.writes = []
        self.reads = 0
        self.failures = []
        self.read_failures = []
        self.session = SimpleNamespace(close=Mock())

    def metadata(self):
        self.reads += 1
        if self.read_failures:
            raise self.read_failures.pop(0)
        return deepcopy(self.state)

    def header(self, title):
        return [deepcopy(self.tables[title][0])]

    def batch(self, requests):
        self.writes.append(deepcopy(requests))
        mode = self.failures.pop(0) if self.failures else None
        if isinstance(mode, sheets.SheetsError):
            raise mode
        state, tables = deepcopy(self.state), deepcopy(self.tables)
        by_id = {s["properties"]["sheetId"]: s["properties"]["title"] for s in state["sheets"]}
        def values(row):
            return [cell.get("userEnteredValue", {}).get("stringValue",
                    cell.get("userEnteredValue", {}).get("numberValue",
                    cell.get("userEnteredValue", {}).get("boolValue", "")))
                    for cell in row["values"]]
        for request in requests:
            if "addSheet" in request:
                props = request["addSheet"]["properties"]
                if props["sheetId"] in by_id or props["title"] in tables:
                    raise sheets.SheetsError(400)
                state["sheets"].append({"properties": deepcopy(props)})
                by_id[props["sheetId"]] = props["title"]
                tables[props["title"]] = []
            elif "updateCells" in request:
                update = request["updateCells"]
                tables[by_id[update["start"]["sheetId"]]] = [values(r) for r in update["rows"]]
            elif "appendCells" in request:
                update = request["appendCells"]
                tables[by_id[update["sheetId"]]].extend(values(r) for r in update["rows"])
            elif "createDeveloperMetadata" in request:
                marker = request["createDeveloperMetadata"]["developerMetadata"]
                if any(m["metadataId"] == marker["metadataId"] for m in state["developerMetadata"]):
                    raise sheets.SheetsError(400)
                state["developerMetadata"].append(deepcopy(marker))
        if mode == "reject":
            raise sheets.SheetsError(400)
        self.state, self.tables = state, tables
        if mode == "timeout_after_commit":
            raise sheets.SheetsError()
        if mode == "concurrent_commit":
            raise sheets.SheetsError(400)


class ValidationTests(unittest.TestCase):
    def test_50_rows_20_charts_and_singapore_day_preserve_regional_identity(self):
        rows, charts = fixture()
        batch = sheets.prepare(rows, charts)
        self.assertEqual((len(batch["rankings"]), len(batch["charts"])), (50, 20))
        self.assertEqual(batch["collection_date"], "2026-11-19")
        self.assertEqual(len({r["record_key"] for r in batch["rankings"]}), 50)
        cn = next(r for r in batch["rankings"] if r["country"] == "CN" and r["game_id"] == "honkai-star-rail" and r["genre_id"] == "7002")
        self.assertEqual(cn["app_id"], "1523037824")
        self.assertEqual(cn["canonical_app_id"], "1599719154")
        self.assertEqual(cn["rank"], "2")

    def test_utc_previous_day_is_bucketed_by_singapore_date(self):
        rows, charts = fixture()
        for r in rows + charts:
            r["retrieved_at_utc"] = "2026-11-18T17:00:00+00:00"
        self.assertEqual(sheets.prepare(rows, charts)["collection_date"], "2026-11-19")

    def test_invalid_or_mixed_batch_rejected(self):
        original_rows, original_charts = fixture()
        changes = (
            lambda r, c: r.pop(),
            lambda r, c: r.append(deepcopy(r[0])),
            lambda r, c: c.pop(),
            lambda r, c: c.append(deepcopy(c[0])),
            lambda r, c: r[0].update(rank="101"),
            lambda r, c: r[0].update(app_id="99999"),
            lambda r, c: r[0].update(snapshot_id="wrong"),
            lambda r, c: c[0].update(chart_complete="False"),
            lambda r, c: c[0].update(roster_version="old"),
            lambda r, c: c[0].update(retrieved_at_utc="2026-11-20T01:17:00+00:00"),
            lambda r, c: c[0].update(retrieved_at_utc="2026-11-19T09:17:00+08:00"),
            lambda r, c: c[0].update(run_id="different"),
        )
        for change in changes:
            with self.subTest(change=change):
                rows, charts = deepcopy(original_rows), deepcopy(original_charts)
                change(rows, charts)
                with self.assertRaises(ValueError):
                    sheets.prepare(rows, charts)

    def test_unresolved_and_partial_are_valid_but_errors_block_publication(self):
        config = tracker.load_config()
        game = config["genres"][1]["games"][2]
        game["market_app_ids"]["VN"] = None
        game["market_mapping_sources"].pop("VN")
        rows, charts = fixture(config=config)
        vn = next(r for r in rows if r["country"] == "VN" and r["game_id"] == "zenless-zone-zero")
        self.assertEqual((vn["rank"], vn["status"]), ("", "unknown"))
        # All retained observations are within first five entries in this fixture.
        for r in rows + charts:
            r["chart_status"], r["coverage_depth"] = "partial", "5"
        for c in charts:
            c["source_count"], c["chart_complete"] = "5", "False"
        self.assertEqual(sheets.prepare(rows, charts, config=config)["chart_errors"], 0)
        bad_rows, bad_charts = fixture(error=True)
        batch = sheets.prepare(bad_rows, bad_charts)
        self.assertEqual(batch["chart_errors"], 2)
        client = FakeSheets()
        with self.assertRaisesRegex(ValueError, "Source chart errors"):
            sheets.publish(client, batch)
        self.assertEqual((client.reads, len(client.writes)), (0, 0))

    def test_outside_chart_requires_blank_rank_and_complete_chart(self):
        rows, charts = fixture()
        row = next(r for r in rows if r["country"] == "SG")
        row["rank"], row["status"] = "", "outside-chart"
        sheets.prepare(rows, charts)
        row["rank"] = "101"
        with self.assertRaisesRegex(ValueError, "Unobserved rank"):
            sheets.prepare(rows, charts)


class PublishingTests(unittest.TestCase):
    def batch(self, day=19):
        return sheets.prepare(*fixture(day=day))

    def test_atomic_initialization_two_tables_and_daily_marker(self):
        client, batch = FakeSheets(), self.batch()
        report = sheets.publish(client, batch)
        self.assertEqual(report["status"], "published")
        self.assertEqual(len(client.writes), 1)
        self.assertEqual(len(client.tables[sheets.DEFAULT_RANK_TAB]), 51)
        self.assertEqual(len(client.tables[sheets.DEFAULT_CHART_TAB]), 21)
        self.assertEqual(client.tables[sheets.DEFAULT_RANK_TAB][0], list(sheets.RANK_HEADERS))
        self.assertEqual(len(client.state["developerMetadata"]), 1)
        self.assertTrue(any("createDeveloperMetadata" in r for r in client.writes[0]))

    def test_rerun_is_noop_and_never_replaces_first_publication(self):
        client, batch = FakeSheets(), self.batch()
        sheets.publish(client, batch)
        before = deepcopy(client.tables)
        batch["rankings"][0]["rank"] = "99"
        batch["run_id"] = "a-different-run"
        self.assertEqual(sheets.publish(client, batch)["status"], "already_published")
        self.assertEqual(len(client.writes), 1)
        self.assertEqual(client.tables, before)

    def test_new_date_appends_history_without_overwriting_previous_rows(self):
        client = FakeSheets()
        sheets.publish(client, self.batch(19))
        before = deepcopy(client.tables)
        sheets.publish(client, self.batch(20))
        self.assertEqual(len(client.tables[sheets.DEFAULT_RANK_TAB]), 101)
        self.assertEqual(client.tables[sheets.DEFAULT_RANK_TAB][:51], before[sheets.DEFAULT_RANK_TAB])
        self.assertEqual(len(client.state["developerMetadata"]), 2)

    def test_timeout_after_commit_and_concurrent_writer_do_not_duplicate(self):
        for mode in ("timeout_after_commit", "concurrent_commit"):
            with self.subTest(mode=mode):
                client = FakeSheets()
                client.failures = [mode]
                report = sheets.publish(client, self.batch(), sleep=lambda _: None)
                self.assertEqual(report["status"], "already_published")
                self.assertEqual(len(client.writes), 1)
                self.assertEqual(len(client.tables[sheets.DEFAULT_RANK_TAB]), 51)

    def test_transient_errors_retry_with_backoff_then_succeed(self):
        client, pauses = FakeSheets(), []
        client.failures = [sheets.SheetsError(429), sheets.SheetsError(503)]
        self.assertEqual(sheets.publish(client, self.batch(), sleep=pauses.append)["status"], "published")
        self.assertEqual(pauses, [2, 4])
        self.assertEqual(len(client.tables[sheets.DEFAULT_RANK_TAB]), 51)

    def test_read_failures_and_exhaustion_do_not_blindly_append(self):
        client, pauses = FakeSheets(), []
        client.read_failures = [sheets.SheetsError()]
        sheets.publish(client, self.batch(), sleep=pauses.append)
        self.assertEqual(pauses, [2])
        self.assertEqual(len(client.writes), 1)
        client = FakeSheets()
        client.failures = [sheets.SheetsError(503)] * 4
        with self.assertRaises(sheets.SheetsError):
            sheets.publish(client, self.batch(), sleep=lambda _: None)
        self.assertEqual(client.tables, {})

    def test_permanent_rejection_is_atomic_and_not_retried(self):
        for error in (sheets.SheetsError(403), "reject"):
            client = FakeSheets()
            client.failures = [error]
            with self.assertRaises(sheets.SheetsError):
                sheets.publish(client, self.batch(), sleep=lambda _: self.fail("must not retry"))
            self.assertEqual(len(client.writes), 1)
            self.assertEqual(client.tables, {})
            self.assertEqual(client.state["developerMetadata"], [])

    def test_header_changes_receipt_collisions_and_missing_tabs_fail_closed(self):
        batch = self.batch()
        client = FakeSheets()
        sheets.publish(client, batch)
        client.tables[sheets.DEFAULT_RANK_TAB][0][0] = "edited-header"
        with self.assertRaisesRegex(ValueError, "headers"):
            sheets.publish(client, self.batch(20))
        client = FakeSheets()
        client.state["developerMetadata"] = [{"metadataId": batch["marker_id"], "metadataKey": "other", "metadataValue": "x"}]
        with self.assertRaisesRegex(ValueError, "collision"):
            sheets.publish(client, batch)
        client = FakeSheets()
        sheets.publish(client, batch)
        client.state["sheets"] = []
        with self.assertRaisesRegex(ValueError, "missing"):
            sheets.publish(client, batch)

    def test_strings_are_literal_ids_text_numbers_numeric_and_null_ranks_blank(self):
        client = FakeSheets()
        batch = self.batch()
        absent = next(r for r in batch["rankings"] if r["country"] == "VN" and r["game_id"] == "zenless-zone-zero")
        absent.update(rank="", status="outside-chart", observed_title="", store_url="")
        sheets.publish(client, batch)
        requests = client.writes[0]
        append = next(r["appendCells"] for r in requests if "appendCells" in r)
        values = append["rows"][0]["values"]
        data = dict(zip(sheets.RANK_HEADERS, values))
        self.assertIn("stringValue", data["app_id"]["userEnteredValue"])
        self.assertIn("numberValue", data["rank"]["userEnteredValue"])
        all_cells = [v for r in append["rows"] for v in r["values"]]
        self.assertTrue(any(v.get("userEnteredValue", {}).get("stringValue", "").startswith("=SUM") for v in all_cells))
        self.assertFalse(any("formulaValue" in v.get("userEnteredValue", {}) for v in all_cells))
        vn = next(r for r in append["rows"] if r["values"][sheets.RANK_HEADERS.index("game_id")].get("userEnteredValue", {}).get("stringValue") == "zenless-zone-zero" and r["values"][sheets.RANK_HEADERS.index("country")]["userEnteredValue"]["stringValue"] == "VN")
        self.assertEqual(vn["values"][sheets.RANK_HEADERS.index("rank")], {})

    def test_sheet_names_are_distinct_and_support_quotes(self):
        client = FakeSheets()
        with self.assertRaises(ValueError):
            sheets.publish(client, self.batch(), "same", "same")
        with self.assertRaises(ValueError):
            sheets.publish(client, self.batch(), "bad/name", "status")
        self.assertEqual(client.writes, [])
        sheets.publish(client, self.batch(), "Game's history", "Chart status")
        self.assertIn("Game's history", client.tables)


class AdapterAndCliTests(unittest.TestCase):
    def test_adapter_uses_google_endpoint_and_sanitizes_errors(self):
        response = SimpleNamespace(status_code=200, json=lambda: {"values": [["header"]]})
        session = SimpleNamespace(request=Mock(return_value=response))
        client = sheets.GoogleSheets("sheet_123", session)
        self.assertEqual(client.header("Game's history"), [["header"]])
        args, kwargs = session.request.call_args
        self.assertIn("sheets.googleapis.com/v4/spreadsheets/sheet_123/values/", args[1])
        self.assertIn("Game%27%27s", args[1])
        self.assertEqual(kwargs["timeout"], 30)
        session.request.side_effect = OSError("private credential response")
        with self.assertRaises(sheets.SheetsError) as caught:
            client.metadata()
        self.assertNotIn("private", str(caught.exception))
        session.request.side_effect = None
        session.request.return_value = SimpleNamespace(status_code=403)
        with self.assertRaises(sheets.SheetsError) as caught:
            client.batch([])
        self.assertEqual(caught.exception.status, 403)

    def test_dry_run_has_no_google_access_or_new_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            rows, charts = fixture()
            write_csv(target / "apple_hoyoverse_rankings.csv", rows, tracker.FIELDS)
            write_csv(target / "apple_hoyoverse_chart_statuses.csv", charts, tracker.STATUS_FIELDS)
            with patch.object(sheets.GoogleSheets, "authenticated", side_effect=AssertionError("no Google access")), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(sheets.main(["--input", directory]), 0)
            self.assertEqual(json.loads(out.getvalue())["status"], "dry_run")
            self.assertEqual(len(list(target.iterdir())), 2)

    def test_publish_requires_explicit_flag_and_destination_and_closes_session(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            rows, charts = fixture()
            write_csv(target / "apple_hoyoverse_rankings.csv", rows, tracker.FIELDS)
            write_csv(target / "apple_hoyoverse_chart_statuses.csv", charts, tracker.STATUS_FIELDS)
            client = FakeSheets()
            with patch.dict("os.environ", {"GOOGLE_SHEETS_SPREADSHEET_ID": ""}), patch.object(sheets.GoogleSheets, "authenticated", return_value=client) as auth, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sheets.main(["--input", directory, "--publish"]), 1)
                auth.assert_not_called()
                self.assertEqual(sheets.main(["--input", directory, "--publish", "--spreadsheet-id", "sheet_123"]), 0)
                auth.assert_called_once_with("sheet_123")
            client.session.close.assert_called_once()

    def test_legacy_or_truncated_csv_rejected_before_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "apple_hoyoverse_rankings.csv").write_text("old,header\nx,y\n", encoding="utf-8")
            with patch.object(sheets.GoogleSheets, "authenticated") as auth, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sheets.main(["--input", directory, "--publish"]), 1)
                auth.assert_not_called()

    def test_workflow_defaults_are_gated_and_manual_collector_is_unchanged(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / ".github/workflows/apple-hoyoverse-daily-sheets.yml").read_text()
        manual = (root / ".github/workflows/apple-hoyoverse-targeted.yml").read_text()
        self.assertIn("schedule:", workflow)
        self.assertIn("vars.APPLE_SHEETS_DAILY_ENABLED == 'true'", workflow)
        self.assertIn("default: false", workflow)
        self.assertIn("APPLE_REGIONAL_VALIDATED", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("if: always()", workflow)
        self.assertIn("continue-on-error: true", workflow)
        self.assertNotIn("schedule:", manual)
        self.assertNotIn("apple_sheets", manual)


if __name__ == "__main__":
    unittest.main()

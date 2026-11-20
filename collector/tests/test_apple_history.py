import contextlib
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from game_observatory import apple_history as history, apple_sheets as sheets
from game_observatory.apple import write_csv
from game_observatory.apple_hoyoverse import FIELDS, STATUS_FIELDS
from test_apple_sheets import FakeSheets, fixture

RUN_ID = "44489555279"
FIXED = datetime(2026, 11, 20, 2, tzinfo=timezone.utc)
REPO = "qatalyse/Game-Observatory"


def source():
    return {"id": int(RUN_ID), "repository": {"full_name": REPO},
            "head_repository": {"full_name": REPO}, "event": "workflow_dispatch",
            "path": history.MANUAL_WORKFLOW, "status": "completed",
            "conclusion": "success", "run_attempt": 1, "head_sha": "a" * 40}


def saved(directory, *, day=19, error=False):
    rows, charts = fixture(day=day, error=error)
    for row in rows + charts:
        row["run_id"] = f"github-{RUN_ID}-1"
    write_csv(directory / "apple_hoyoverse_rankings.csv", rows, FIELDS)
    write_csv(directory / "apple_hoyoverse_chart_statuses.csv", charts, STATUS_FIELDS)
    return rows, charts


def args(directory):
    return ["--input", str(directory), "--source-run-id", RUN_ID,
            "--source-attempt", "1", "--collection-date", "2026-11-19"]


class HistoryTests(unittest.TestCase):
    def test_source_selects_exact_successful_manual_artifacts(self):
        details = history.source_details(source(), REPO, RUN_ID)
        self.assertEqual(details["source_run_id"], RUN_ID)
        self.assertEqual(details["source_attempt"], "1")
        self.assertEqual(details["rankings_artifact"], f"apple-hoyoverse-rankings-{RUN_ID}-1")
        self.assertEqual(details["statuses_artifact"], f"apple-hoyoverse-chart-statuses-{RUN_ID}-1")

    def test_invalid_ids_and_untrusted_or_unsuccessful_sources_are_rejected(self):
        for value in ("", "0", "../1", "1\n", "１２３", "1;echo", 123, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                history.source_details(source(), REPO, value)
        mutations = [
            lambda p: p.update(id=123),
            lambda p: p.update(repository={"full_name": "other/repo"}),
            lambda p: p.update(head_repository={"full_name": "fork/repo"}),
            lambda p: p.update(path=".github/workflows/apple-test-dataset.yml"),
            lambda p: p.update(event="pull_request"),
            lambda p: p.update(status="in_progress"),
            lambda p: p.update(conclusion="failure"),
            lambda p: p.update(run_attempt=True),
            lambda p: p.update(head_sha="invalid"),
        ]
        for change in mutations:
            data = source()
            change(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                history.source_details(data, REPO, RUN_ID)

    def test_original_observations_and_tracking_fields_keep_the_historical_date(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            rows, _ = saved(directory)
            original = {row["snapshot_id"]: deepcopy(row) for row in rows}
            batch = history.historical_batch(directory, RUN_ID, "1", "2026-11-19", clock=lambda: FIXED)
        self.assertEqual((len(batch["rankings"]), len(batch["charts"])), (90, 30))
        self.assertEqual(batch["collection_date"], "2026-11-19")
        self.assertEqual(batch["publication_key"], "apple-hoyoverse:2026-11-19")
        for row in batch["rankings"]:
            self.assertEqual({key: row[key] for key in FIELDS}, original[row["snapshot_id"]])
            self.assertEqual(row["record_key"],
                f"apple-hoyoverse:2026-11-19:{row['country']}:{row['genre_id']}:{row['game_id']}")

    def test_wrong_date_source_attempt_and_source_errors_block_before_google_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            saved(directory)
            for run_id, attempt, day in (
                (RUN_ID, "1", "2026-11-18"), ("123", "1", "2026-11-19"),
                (RUN_ID, "2", "2026-11-19"), (RUN_ID, "1", "2026-11-20"),
                (RUN_ID, "1", "2026-11-21"), (RUN_ID, "1", "20261119"),
            ):
                with self.subTest(run_id=run_id, attempt=attempt, day=day), self.assertRaises(ValueError):
                    history.historical_batch(directory, run_id, attempt, day, clock=lambda: FIXED)
            saved(directory, error=True)
            with self.assertRaisesRegex(ValueError, "Source chart errors"):
                history.historical_batch(directory, RUN_ID, "1", "2026-11-19", clock=lambda: FIXED)
            with patch.object(sheets.GoogleSheets, "authenticated") as auth, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(history.main(args(directory) + ["--publish"], clock=lambda: FIXED), 1)
                auth.assert_not_called()

    def test_truncated_old_schema_and_wrong_roster_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for mode in ("missing", "schema", "roster"):
                rows, charts = saved(directory)
                if mode == "missing":
                    write_csv(directory / "apple_hoyoverse_rankings.csv", rows[:-1], FIELDS)
                elif mode == "schema":
                    (directory / "apple_hoyoverse_rankings.csv").write_text("old,header\nx,y\n")
                else:
                    for row in rows + charts:
                        row["roster_version"] = "old"
                    write_csv(directory / "apple_hoyoverse_rankings.csv", rows, FIELDS)
                    write_csv(directory / "apple_hoyoverse_chart_statuses.csv", charts, STATUS_FIELDS)
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    history.historical_batch(directory, RUN_ID, "1", "2026-11-19", clock=lambda: FIXED)

    def test_dry_run_has_no_google_access_no_apple_requests_and_no_file_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            saved(directory)
            before = {path.name: path.read_bytes() for path in directory.iterdir()}
            with patch.object(sheets.GoogleSheets, "authenticated") as auth, \
                 patch("game_observatory.apple.urlopen", side_effect=AssertionError("No live charts")), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(history.main(args(directory), clock=lambda: FIXED), 0)
                auth.assert_not_called()
            self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()}, before)
        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "dry_run")
        self.assertEqual(report["publication_key"], "apple-hoyoverse:2026-11-19")
        self.assertTrue(report["ready_for_publish"])

    def test_import_preserves_today_and_records_yesterday_once(self):
        client = FakeSheets()
        today = sheets.prepare(*fixture(day=20))
        sheets.publish(client, today)
        original = deepcopy(client.tables)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            saved(directory)
            with patch.dict("os.environ", {"GOOGLE_SHEETS_SPREADSHEET_ID": "test_sheet"}), \
                 patch.object(sheets.GoogleSheets, "authenticated", return_value=client), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(history.main(args(directory) + ["--publish"], clock=lambda: FIXED), 0)
                self.assertEqual(history.main(args(directory) + ["--publish"], clock=lambda: FIXED), 0)
        reports = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r["status"] for r in reports], ["published", "already_published"])
        for title, count in ((sheets.DEFAULT_RANK_TAB, 90), (sheets.DEFAULT_CHART_TAB, 30)):
            self.assertEqual(client.tables[title][:count + 1], original[title])
            self.assertEqual(len(client.tables[title]), 2 * count + 1)
            self.assertEqual({r[0] for r in client.tables[title][count + 1:]}, {"2026-11-19"})
        self.assertEqual(len(client.state["developerMetadata"]), 2)
        self.assertEqual(len(client.writes), 2)

    def test_workflow_is_manual_dry_run_default_and_separates_google_auth(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / ".github/workflows/apple-hoyoverse-history-import.yml").read_text()
        triggers = workflow.split("on:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("workflow_dispatch:", triggers)
        self.assertNotIn("schedule:", triggers)
        self.assertNotIn("push:", triggers)
        self.assertIn("default: false", triggers)
        preparation, publication = workflow.split("\n  publish:", 1)
        self.assertNotIn("google-github-actions/auth", preparation)
        self.assertNotIn("--publish", preparation)
        self.assertIn("inputs.publish_to_sheets", publication)
        self.assertIn("github.ref == 'refs/heads/main'", publication)
        self.assertIn("group: apple-hoyoverse-daily-sheets", workflow)
        self.assertNotIn("github.run_attempt", workflow)
        self.assertIn("overwrite: true", workflow)


if __name__ == "__main__":
    unittest.main()

"""Export integration tests: real Steam collector, mocked upstream responses."""
import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from game_observatory import steam, steam_test_dataset


def payload(count):
    return {"response": {"result": 1, "player_count": count}}, 200


class SteamDatasetTests(unittest.TestCase):
    def run_export(self, fetch):
        # Use the real fixed catalogue, collector and CSV writer without network.
        def fixture_collect():
            return steam.collect(fetch=fetch)

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(steam_test_dataset, "collect", side_effect=fixture_collect) as collector:
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    code = steam_test_dataset.main(["--output", directory])
            collector.assert_called_once_with()
            self.assertEqual(sorted(path.name for path in Path(directory).iterdir()),
                             ["steam_players.csv", "steam_statuses.csv"])
            data = []
            for name, fields in (("steam_players.csv", steam_test_dataset.PLAYER_FIELDS),
                                 ("steam_statuses.csv", steam_test_dataset.STATUS_FIELDS)):
                with (Path(directory) / name).open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(reader.fieldnames, list(fields))
                    data.append(list(reader))
            return code, data[0], data[1], json.loads(output.getvalue())

    def test_all_games_export_observations_and_joinable_statuses(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return payload(4321)

        code, players, statuses, report = self.run_export(fetch)
        self.assertEqual(code, 0)
        self.assertEqual(set(calls), {steam.player_url(app_id) for app_id in steam.GAMES})
        self.assertEqual(len(calls), len(steam.GAMES))
        self.assertEqual([row["app_id"] for row in players], list(steam.GAMES))
        self.assertEqual([row["app_id"] for row in statuses], list(steam.GAMES))
        self.assertEqual(report["request_count"], len(steam.GAMES))
        self.assertEqual(report["observations"], len(steam.GAMES))
        self.assertEqual(report["statuses"], {"ok": len(steam.GAMES), "unavailable": 0, "error": 0})
        self.assertEqual(len({row["snapshot_id"] for row in statuses}), len(steam.GAMES))
        self.assertEqual({row["run_id"] for row in players + statuses}, {report["run_id"]})
        for player, status in zip(players, statuses):
            self.assertEqual(player, {field: status[field] for field in steam_test_dataset.PLAYER_FIELDS})
            self.assertEqual(player["title"], steam.GAMES[player["app_id"]])
            self.assertEqual(player["player_count"], "4321")
            self.assertEqual(status["http_status"], "200")
            self.assertEqual(status["steam_result"], "1")

    def test_mixed_failures_keep_successes_zero_and_every_status(self):
        ids = list(steam.GAMES)

        def fetch(url):
            app_id = url.split("appid=")[1]
            if app_id == ids[0]:
                return payload(0)
            if app_id == ids[1]:
                return {"response": {"result": 42, "player_count": 999}}, 200
            if app_id == ids[2]:
                raise HTTPError(url, 429, "rate limited", {}, None)
            if app_id == ids[3]:
                raise TimeoutError()
            return payload(100)

        code, players, statuses, report = self.run_export(fetch)
        self.assertEqual(code, 1)
        self.assertEqual(len(statuses), len(ids))
        self.assertEqual(len(players), len(ids) - 3)
        self.assertEqual(players[0]["player_count"], "0")
        self.assertEqual([row["app_id"] for row in players], [ids[0], *ids[4:]])
        self.assertEqual([row["status"] for row in statuses[:4]], ["ok", "unavailable", "error", "error"])
        for row in statuses[1:4]:
            self.assertEqual(row["player_count"], "")
            self.assertTrue(row["error_code"])
            self.assertTrue(row["retrieved_at_utc"])
        self.assertEqual(statuses[1]["steam_result"], "42")
        self.assertEqual(statuses[2]["http_status"], "429")
        self.assertEqual(statuses[3]["http_status"], "")
        self.assertEqual(statuses[3]["error_code"], "timeout")
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["statuses"], {"ok": len(ids) - 3, "unavailable": 1, "error": 2})

    def test_all_errors_still_write_header_only_players_and_complete_statuses(self):
        def fetch(url):
            raise TimeoutError()

        code, players, statuses, report = self.run_export(fetch)
        self.assertEqual(code, 1)
        self.assertEqual(players, [])
        self.assertEqual(len(statuses), len(steam.GAMES))
        self.assertEqual({row["status"] for row in statuses}, {"error"})
        self.assertTrue(all(row["player_count"] == "" for row in statuses))
        self.assertEqual(report["status"], "no_data")
        self.assertEqual(report["observations"], 0)
        self.assertEqual(report["statuses"]["error"], len(steam.GAMES))

    def test_all_unavailable_is_explicit_and_does_not_fail_export(self):
        code, players, statuses, report = self.run_export(
            lambda url: ({"response": {"result": 42}}, 200))
        self.assertEqual(code, 0)
        self.assertEqual(players, [])
        self.assertEqual([row["app_id"] for row in statuses], list(steam.GAMES))
        self.assertTrue(all(row["player_count"] == "" for row in statuses))
        self.assertEqual(report["status"], "no_data")
        self.assertEqual(report["statuses"]["unavailable"], len(steam.GAMES))

    def test_malformed_success_is_not_exported_as_zero(self):
        code, players, statuses, _ = self.run_export(
            lambda url: ({"response": {"result": 1}}, 200))
        self.assertEqual(code, 1)
        self.assertEqual(players, [])
        self.assertTrue(all(row["error_code"] == "invalid_response" for row in statuses))
        self.assertTrue(all(row["player_count"] == "" for row in statuses))

    def test_csv_roundtrip_preserves_unicode_commas_quotes_and_newlines(self):
        app_id = next(iter(steam.GAMES))
        title = '冒険, "Game"\nNext line'
        with patch.dict(steam.GAMES, {app_id: title}):
            code, players, statuses, _ = self.run_export(lambda url: payload(7))
        self.assertEqual(code, 0)
        self.assertEqual(players[0]["title"], title)
        self.assertEqual(statuses[0]["title"], title)

    def test_writer_replaces_previous_export_without_duplicate_headers_or_rows(self):
        fields = ("app_id", "player_count")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested/players.csv"
            steam_test_dataset.write_csv(path, [{"app_id": "413150", "player_count": 12}], fields)
            steam_test_dataset.write_csv(path, [{"app_id": "2456740", "player_count": 0}], fields)
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(rows, [{"app_id": "2456740", "player_count": "0"}])


if __name__ == "__main__":
    unittest.main()

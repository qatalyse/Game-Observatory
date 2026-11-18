import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from game_observatory import steam


def success(count=123):
    return {"response": {"result": 1, "player_count": count}}


class SteamTests(unittest.TestCase):
    def test_exact_catalogue_and_frontend_mapping(self):
        expected = {
            "1671200": "Honkai Impact 3rd", "4162040": "Zenless Zone Zero",
            "3513350": "Wuthering Waves", "4125930": "Punishing Gray Raven",
            "2064650": "Tower of Fantasy", "4508340": "Neverness to Everness",
            "2456740": "inZOI", "2320980": "Loftia", "413150": "Stardew Valley",
        }
        self.assertEqual(steam.GAMES, expected)
        frontend = (Path(__file__).resolve().parents[2] / "frontend/src/SteamDevCollection.tsx").read_text(encoding="utf-8")
        for app_id, name in expected.items():
            self.assertIn(f'{{ id: "{app_id}", name: "{name}" }}', frontend)

    def test_all_nine_one_request_each_order_and_provenance(self):
        calls = []
        lock = threading.Lock()
        clock = lambda: datetime(2026, 11, 18, tzinfo=timezone.utc)

        def fetch(url):
            with lock:
                calls.append(url)
            return success(), 200

        result = steam.collect(fetch=fetch, clock=clock)
        rows = result["results"]
        self.assertEqual(len(calls), 9)
        self.assertEqual(set(calls), {steam.player_url(app_id) for app_id in steam.GAMES})
        self.assertEqual([row["app_id"] for row in rows], list(steam.GAMES))
        self.assertEqual(result["request_count"], 9)
        self.assertEqual(result["success_count"], 9)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len({row["snapshot_id"] for row in rows}), 9)
        for row in rows:
            self.assertEqual(row["run_id"], result["run_id"])
            self.assertEqual(row["retrieved_at_utc"], "2026-11-18T00:00:00+00:00")
            self.assertEqual(row["started_at_utc"], row["retrieved_at_utc"])
            self.assertEqual(row["source"], steam.SOURCE)
            self.assertEqual(row["player_count"], 123)
            self.assertEqual(row["http_status"], 200)
        self.assertEqual(result["started_at_utc"], result["completed_at_utc"])

    def test_validation_happens_before_requests(self):
        for selected in ([], (), "413150", {}, ["unknown"], [413150], [True], [None], ["413150"] * 2, list(steam.GAMES) * 2):
            with self.subTest(selected=selected):
                fetch = MagicMock()
                with self.assertRaises(ValueError):
                    steam.collect(selected, fetch=fetch)
                fetch.assert_not_called()

    def test_zero_is_observed_but_unavailable_is_null(self):
        result = steam.collect(["413150", "2320980"], fetch=lambda url:
            (success(0) if "413150" in url else {"response": {"result": 42, "player_count": 99}}, 200))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["success_count"], 1)
        zero, unavailable = result["results"]
        self.assertEqual(zero["status"], "ok")
        self.assertEqual(zero["player_count"], 0)
        self.assertEqual(unavailable["status"], "unavailable")
        self.assertEqual(unavailable["steam_result"], 42)
        self.assertIsNone(unavailable["player_count"])

    def test_invalid_schemas_never_become_observations(self):
        invalid = [None, [], {}, {"response": []}, {"response": {}},
                   {"response": {"result": True}}, {"response": {"result": "1"}},
                   {"response": {"result": 1}}]
        invalid += [success(value) for value in (None, -1, True, 1.5, "0", [], {})]
        for payload in invalid:
            with self.subTest(payload=payload):
                result = steam.collect(["413150"], fetch=lambda url: (payload, 200))
                row = result["results"][0]
                self.assertEqual(row["error_code"], "invalid_response")
                self.assertEqual(row["http_status"], 200)
                self.assertIsNone(row["player_count"])
                self.assertEqual(result["status"], "no_data")

    def test_errors_are_isolated_sanitized_and_timestamped(self):
        cases = [
            (HTTPError("url", 429, "rate limited", {}, None), "http_error", 429),
            (TimeoutError(), "timeout", None),
            (URLError(TimeoutError()), "timeout", None),
            (URLError("private network detail"), "network_error", None),
            (ConnectionResetError(), "network_error", None),
            (RuntimeError("secret detail"), "unexpected_error", None),
        ]
        for exc, code, http_status in cases:
            with self.subTest(code=code):
                def fetch(url):
                    if "2320980" in url:
                        raise exc
                    return success(), 200
                result = steam.collect(["2320980", "413150"], fetch=fetch)
                failed, ok = result["results"]
                self.assertEqual(result["status"], "partial")
                self.assertEqual(failed["error_code"], code)
                self.assertEqual(failed["http_status"], http_status)
                self.assertIsNone(failed["player_count"])
                self.assertIsNotNone(datetime.fromisoformat(failed["retrieved_at_utc"]).tzinfo)
                self.assertNotIn("detail", failed["error"])
                self.assertEqual(ok["status"], "ok")

    def test_non_200_fetch_result_is_an_http_error(self):
        row = steam.collect(["413150"], fetch=lambda url: (success(), 503))["results"][0]
        self.assertEqual(row["error_code"], "http_error")
        self.assertEqual(row["http_status"], 503)
        self.assertIsNone(row["player_count"])

    def test_fetch_timeout_size_and_json_limits(self):
        for raw in (b"not json", b"\xff", b"x" * (steam.MAX_RESPONSE_BYTES + 1)):
            with self.subTest(raw_length=len(raw)), patch.object(steam, "urlopen") as opened:
                response = opened.return_value.__enter__.return_value
                response.status = 200
                response.read.return_value = raw
                result = steam.collect(["413150"])
                row = result["results"][0]
                self.assertEqual(row["error_code"], "invalid_response")
                self.assertEqual(row["http_status"], 200)
                response.read.assert_called_once_with(steam.MAX_RESPONSE_BYTES + 1)
                self.assertEqual(opened.call_args.kwargs["timeout"], 8)
                self.assertEqual(opened.call_args.args[0].full_url, steam.player_url("413150"))

    def test_cli_selected_ids_output_and_exit_codes(self):
        for status, expected_code in (("ok", 0), ("partial", 1), ("no_data", 1)):
            with patch.object(steam, "collect", return_value={"status": status}) as collect:
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(steam.main(["--app-ids", "413150,2456740"]), expected_code)
                self.assertEqual(json.loads(output.getvalue())["status"], status)
                collect.assert_called_once_with(("413150", "2456740"))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            steam.main(["--app-ids", ""])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

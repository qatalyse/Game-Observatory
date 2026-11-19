"""Exercise the Apple HTTP handler on the cloud runner with fixture-only upstream."""
from http.client import HTTPConnection
from http.server import HTTPServer
import importlib.util
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from game_observatory.apple import GENRES, MARKETS, collect
from test_apple import payload

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("apple_endpoint", ROOT / "api/index.py")
endpoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(endpoint)


class AppleEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), endpoint.handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        env = patch.dict(os.environ, {"DEV_COLLECT_TOKEN": "test-token"})
        env.start()
        self.addCleanup(env.stop)
        mocked = patch.object(endpoint, "collect", return_value=([], []))
        self.collect = mocked.start()
        self.addCleanup(mocked.stop)
        logs = patch.object(endpoint.handler, "log_message")
        logs.start()
        self.addCleanup(logs.stop)

    def request(self, options=None, *, body=None, token="test-token", method="POST",
                path="/api/dev/apple-collect", headers=None):
        if body is None:
            body = json.dumps(options or {}).encode()
        connection = HTTPConnection(*self.server.server_address, timeout=3)
        try:
            connection.request(method, path, body=body,
                               headers={"X-Dev-Token": token, **(headers or {})})
            response = connection.getresponse()
            raw = response.read()
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
            self.assertEqual(int(response.getheader("Content-Length")), len(raw))
            return response.status, json.loads(raw)
        finally:
            connection.close()

    def use_fixture(self, response):
        calls = []
        def run(**kwargs):
            def fetch(url):
                calls.append(url)
                return response, 200
            return collect(**kwargs, fetch=fetch)
        self.collect.side_effect = run
        return calls

    def test_every_market_and_genre_requests_full_top_100(self):
        for market in MARKETS:
            for genre in GENRES:
                with self.subTest(market=market, genre=genre):
                    code, data = self.request({"market": market, "genre": genre})
                    self.assertEqual(code, 200)
                    self.collect.assert_called_with(
                        countries=(market,), genres=(genre,), feed_types=("top-grossing",),
                        depth=100, full_chart=True)
                    self.assertEqual(data["requested_depth"], 100)
                    self.assertEqual(data["collection_mode"], "full_chart")
                    self.assertEqual(data["request_count"], 1)
                    self.assertNotIn("tracked_app_ids_selected", data)
                    self.assertNotIn("snapshot_policy", data)

    def test_complete_simulation_chart_returns_all_100_untracked_titles(self):
        ids = tuple(str(880000 + n) for n in range(100))
        response = payload(ids, category_id="7015")
        response["feed"]["entry"][-1]["im:name"]["label"] = 'シミュレーション, "Last"'
        calls = self.use_fixture(response)
        code, data = self.request({"market": "SG", "genre": "simulation"})
        self.assertEqual(code, 200)
        self.assertEqual(calls, ["https://itunes.apple.com/sg/rss/topgrossingapplications/limit=100/genre=7015/json"])
        self.assertEqual([r["position"] for r in data["rankings"]], list(range(1, 101)))
        self.assertEqual([r["app_id"] for r in data["rankings"]], list(ids))
        self.assertEqual(data["rankings"][-1]["title"], 'シミュレーション, "Last"')
        self.assertEqual(set(data["rankings"][0]), set(endpoint.COMPACT_FIELDS))
        self.assertEqual(data["statuses"][0]["status"], "ok")
        self.assertEqual(data["statuses"][0]["snapshot_depth"], 100)

    def test_legacy_id_and_depth_fields_cannot_reenable_dynamic_retention(self):
        response = payload(tuple(str(880000 + n) for n in range(100)))
        response["feed"]["entry"][9]["id"]["attributes"]["im:id"] = "1517783697"
        self.use_fixture(response)
        for ids in ([], ["1517783697"], ["1599719154", "1606356401"]):
            code, data = self.request({"genre": "adventure", "tracked_app_ids": ids, "depth": 5})
            self.assertEqual(code, 200)
            self.assertEqual(len(data["rankings"]), 100)
            self.assertEqual(data["rankings"][-1]["position"], 100)
            self.assertNotIn("tracked_app_ids", self.collect.call_args.kwargs)

    def test_partial_empty_and_invalid_charts_keep_honest_source_outcomes(self):
        cases = (
            (payload(tuple(str(800000 + n) for n in range(23))), "partial", 23),
            (payload(()), "empty", 0),
            (payload(("123", "123")), "error", 0),
        )
        for response, state, count in cases:
            with self.subTest(state=state):
                self.use_fixture(response)
                code, data = self.request({"genre": "simulation"})
                self.assertEqual(code, 200)
                self.assertEqual(len(data["rankings"]), count)
                self.assertEqual(data["statuses"][0]["status"], state)
                self.assertEqual(data["statuses"][0]["requested_depth"], 100)
                self.assertEqual(data["statuses"][0]["returned_count"], count)
                self.assertEqual([r["position"] for r in data["rankings"]], list(range(1, count + 1)))

    def test_new_applications_keeps_20_requested_and_104_returned(self):
        self.use_fixture(payload(tuple(str(770000 + n) for n in range(104)), category_id="6014"))
        code, data = self.request({"feed_type": "new-applications", "genre": "games"})
        self.assertEqual(code, 200)
        self.collect.assert_called_with(
            countries=("SG",), genres=("games",), feed_types=("new-applications",),
            depth=20, full_chart=False)
        self.assertEqual(data["requested_depth"], 20)
        self.assertEqual(len(data["rankings"]), 104)
        self.assertEqual(data["rankings"][-1]["position_semantics"], "feed_order_not_verified_as_rank")

    def test_disabled_or_invalid_tokens_never_collect(self):
        with patch.dict(os.environ, {"DEV_COLLECT_TOKEN": ""}):
            self.assertEqual(self.request()[0], 503)
        for token in ("", "wrong", "é"):
            self.assertEqual(self.request(token=token)[0], 401)
        self.collect.assert_not_called()

    def test_invalid_scope_and_request_shapes_never_collect(self):
        for options in ({"genre": "unsupported"}, {"feed_type": []}, {"genre": {}},
                        {"market": "ZZ"}, {"market": None}):
            self.assertEqual(self.request(options)[0], 400)
        for body in (b"{", b"null", b"[]", b'"text"', b"\xff"):
            self.assertEqual(self.request(body=body)[0], 400)
        self.assertEqual(self.request(body=b"x" * 1025)[0], 413)
        for length in ("-1", "invalid"):
            self.assertEqual(self.request(body=b"", headers={"Content-Length": length})[0], 400)
        self.assertEqual(self.request(body=b"", headers={"Transfer-Encoding": "chunked"})[0], 400)
        self.collect.assert_not_called()

    def test_readiness_and_unexpected_failures(self):
        code, data = self.request(method="GET")
        self.assertEqual(code, 200)
        self.assertIn("simulation", data["genres"])
        self.assertIn("action", data["genres"])
        self.collect.assert_not_called()
        self.assertEqual(self.request(path="/api/other")[0], 404)
        self.collect.side_effect = RuntimeError("private details")
        with patch.object(endpoint.traceback, "print_exc"):
            code, data = self.request()
        self.assertEqual(code, 502)
        self.assertNotIn("private details", str(data))


if __name__ == "__main__":
    unittest.main()

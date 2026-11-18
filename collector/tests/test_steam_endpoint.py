"""Exercise the actual HTTP handler locally; all upstream collection is mocked."""
from http.client import HTTPConnection
from http.server import HTTPServer
import importlib.util
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("steam_endpoint", ROOT / "api/steam_collect.py")
endpoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(endpoint)


class EndpointTests(unittest.TestCase):
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
        collector = patch.object(endpoint, "collect", return_value={"status": "no_data", "results": []})
        self.collect = collector.start()
        self.addCleanup(collector.stop)
        logs = patch.object(endpoint.handler, "log_message")
        logs.start()
        self.addCleanup(logs.stop)

    def request(self, body=b'{"app_ids":["413150"]}', token="test-token", method="POST", path="/api/dev/steam-collect", headers=None):
        connection = HTTPConnection(*self.server.server_address, timeout=3)
        try:
            connection.request(method, path, body=body, headers={"X-Dev-Token": token, **(headers or {})})
            response = connection.getresponse()
            data = response.read()
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
            self.assertEqual(int(response.getheader("Content-Length")), len(data))
            return response.status, json.loads(data), response
        finally:
            connection.close()

    def test_authenticated_selection_and_no_data_results_return_200(self):
        for path in endpoint.PATHS:
            status, data, _ = self.request(path=path)
            self.assertEqual(status, 200)
            self.assertEqual(data["status"], "no_data")
        self.assertEqual(self.collect.call_count, len(endpoint.PATHS))
        self.collect.assert_called_with(("413150",))

    def test_disabled_and_bad_tokens_never_collect(self):
        with patch.dict(os.environ, {"DEV_COLLECT_TOKEN": ""}):
            self.assertEqual(self.request()[0], 503)
        for token in ("", "incorrect", "é"):
            self.assertEqual(self.request(token=token)[0], 401)
        self.collect.assert_not_called()

    def test_invalid_json_and_selections_never_collect(self):
        bodies = [b"", b"{", b"\xff"] + [json.dumps(value).encode() for value in (
            None, [], "text", {}, {"app_ids": None}, {"app_ids": []},
            {"app_ids": [413150]}, {"app_ids": ["413150", "413150"]},
            {"app_ids": ["1"]}, {"app_ids": ["413150"], "url": "https://example.com"},
        )]
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual(self.request(body=body)[0], 400)
        self.collect.assert_not_called()

    def test_request_size_length_and_transfer_encoding(self):
        self.assertEqual(self.request(body=b"x" * 2049)[0], 413)
        for length in ("-1", "invalid"):
            self.assertEqual(self.request(body=b"", headers={"Content-Length": length})[0], 400)
        self.assertEqual(self.request(body=b"", headers={"Transfer-Encoding": "chunked"})[0], 400)
        self.collect.assert_not_called()

    def test_get_and_unknown_path_never_collect(self):
        status, _, response = self.request(method="GET")
        self.assertEqual(status, 405)
        self.assertEqual(response.getheader("Allow"), "POST")
        self.assertEqual(self.request(path="/api/other")[0], 404)
        self.collect.assert_not_called()

    def test_unexpected_collection_failure_is_sanitized(self):
        self.collect.side_effect = RuntimeError("private detail")
        with patch.object(endpoint.traceback, "print_exc"):
            status, data, _ = self.request()
        self.assertEqual(status, 502)
        self.assertNotIn("private", str(data))

    def test_vercel_routing_packaging_and_duration(self):
        config = json.loads((ROOT / "vercel.json").read_text())
        self.assertIn({"source": "/api/dev/steam-collect", "destination": "/api/steam_collect.py"}, config["rewrites"])
        settings = config["functions"]["api/steam_collect.py"]
        self.assertEqual(settings["maxDuration"], 60)
        self.assertEqual(settings["includeFiles"], "collector/game_observatory/**")
        self.assertNotIn("crons", config)


if __name__ == "__main__":
    unittest.main()

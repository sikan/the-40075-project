import gzip
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rowing_tracker.client import APIError, Concept2


class Response:
    def __init__(self, status=200, data=None, compressed=False, broken=False):
        self.status = status
        self.data = {"data": []} if data is None else data
        self.compressed = compressed
        self.broken = broken

    def getheader(self, name, default=""):
        return "gzip" if name == "Content-Encoding" and self.compressed else default

    def read(self):
        if self.broken:
            raise ConnectionResetError("Simulated disconnect")
        payload = json.dumps(self.data).encode()
        return gzip.compress(payload) if self.compressed else payload

    def close(self):
        pass


class Connection:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.closed = False

    def request(self, method, target, headers):
        self.requests.append((method, target, headers))

    def getresponse(self):
        return next(self.responses)

    def close(self):
        self.closed = True


class ClientTests(unittest.TestCase):
    def test_reuses_verified_connection_and_decodes_gzip(self):
        connection = Connection([Response(data={"data": {"id": 1}}), Response(compressed=True)])
        with patch("rowing_tracker.client.http.client.HTTPSConnection", return_value=connection) as create:
            client = Concept2("TEST-TOKEN")
            self.assertEqual(client.get("")["data"]["id"], 1)
            self.assertEqual(client.get("/results", {"page": 1}), {"data": []})
            self.assertEqual(create.call_count, 1)
            self.assertEqual(create.call_args.args[0], "log.concept2.com")
            self.assertTrue(create.call_args.kwargs["context"].check_hostname)
            for method, target, headers in connection.requests:
                self.assertEqual(method, "GET")
                self.assertTrue(target.startswith("/api/users/me"))
                self.assertNotIn("TEST-TOKEN", target)

    def test_redirect_is_not_followed(self):
        connection = Connection([Response(status=302)])
        with patch("rowing_tracker.client.http.client.HTTPSConnection", return_value=connection):
            with self.assertRaises(APIError) as result:
                Concept2("TEST-TOKEN").get("")
            self.assertEqual(result.exception.status, 302)
            self.assertEqual(len(connection.requests), 1)

    def test_disconnect_retries_with_fresh_connection(self):
        first, second = Connection([Response(broken=True)]), Connection([Response()])
        with patch("rowing_tracker.client.http.client.HTTPSConnection", side_effect=[first, second]), patch("rowing_tracker.client.time.sleep"):
            self.assertEqual(Concept2("TEST-TOKEN").get("/results"), {"data": []})
            self.assertTrue(first.closed)

    def test_retryable_status_uses_a_fresh_connection(self):
        first, second = Connection([Response(status=429)]), Connection([Response()])
        with patch("rowing_tracker.client.http.client.HTTPSConnection", side_effect=[first, second]), \
                patch("rowing_tracker.client.time.sleep") as sleep:
            self.assertEqual(Concept2("TEST-TOKEN").get("/results"), {"data": []})
            self.assertTrue(first.closed)
            sleep.assert_called_once()

    def test_only_known_read_paths_are_allowed(self):
        client = Concept2("TEST-TOKEN")
        for path in ("/results-invalid", "/users", "/results/1/delete", "/results/../users", "/results?all=1"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                client.get(path)


if __name__ == "__main__":
    unittest.main()

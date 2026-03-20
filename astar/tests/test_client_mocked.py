from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from astar_client import AstarAPIError, AstarClient


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class MockedClientTests(unittest.TestCase):
    def test_simulate_request_is_validated(self) -> None:
        client = AstarClient(token="token")
        with self.assertRaises(Exception):
            client.simulate({"round_id": "r", "seed_index": 9, "viewport_x": 0, "viewport_y": 0, "viewport_w": 15, "viewport_h": 15})

    def test_authenticated_request_requires_token(self) -> None:
        client = AstarClient()
        with self.assertRaises(AstarAPIError):
            client.get_budget()

    def test_http_error_is_formatted(self) -> None:
        client = AstarClient(token="token")
        with patch.object(client.session, "request", return_value=FakeResponse(429, {"detail": "rate limit"})):
            with self.assertRaises(AstarAPIError) as ctx:
                client.get_budget()
        self.assertIn("Rate limit exceeded", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

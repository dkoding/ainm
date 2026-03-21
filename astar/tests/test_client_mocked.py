from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from astar_client import AstarAPIError, AstarClient
except ImportError as exc:  # pragma: no cover - environment guard
    raise unittest.SkipTest(f"missing runtime dependency: {exc}") from exc


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

    def test_simulate_requests_are_paced(self) -> None:
        client = AstarClient(token="token")
        payload = {
            "round_id": "round-1",
            "seed_index": 0,
            "viewport_x": 0,
            "viewport_y": 0,
            "viewport_w": 15,
            "viewport_h": 15,
        }
        response = {
            "round_id": "round-1",
            "grid": [[11 for _ in range(15)] for _ in range(15)],
            "settlements": [],
            "viewport": {"x": 0, "y": 0, "w": 15, "h": 15},
            "width": 40,
            "height": 40,
            "queries_used": 1,
            "queries_max": 50,
        }
        monotonic_values = iter([100.0, 100.0, 100.0, 100.1, 100.1, 100.32, 100.32, 100.32])
        with patch.object(client.session, "request", return_value=FakeResponse(200, response)):
            with patch("astar_client.time.monotonic", side_effect=lambda: next(monotonic_values)):
                with patch("astar_client.time.sleep") as sleep_mock:
                    client.simulate(payload)
                    client.simulate(payload)
        sleep_mock.assert_called_once()
        self.assertGreaterEqual(float(sleep_mock.call_args.args[0]), 0.11)
        metrics = client.get_request_metrics_summary()
        self.assertEqual(metrics["paced_request_count"], 1)
        self.assertEqual(metrics["per_endpoint"][0]["path"], "/astar-island/simulate")

    def test_last_request_meta_is_recorded_for_submit(self) -> None:
        client = AstarClient(token="token")
        payload = {
            "round_id": "round-1",
            "seed_index": 0,
            "prediction": [[[1 / 6 for _ in range(6)]]],
        }
        with patch.object(client.session, "request", return_value=FakeResponse(200, {"ok": True})):
            client.submit_prediction(payload)
        meta = client.get_last_request_meta()
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta["method"], "POST")
        self.assertEqual(meta["path"], "/astar-island/submit")
        self.assertEqual(meta["status_code"], 200)


if __name__ == "__main__":
    unittest.main()

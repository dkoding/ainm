from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from astar_client import AstarClient
except ImportError as exc:  # pragma: no cover - environment guard
    raise unittest.SkipTest(f"missing runtime dependency: {exc}") from exc


class PublicIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(os.getenv("ASTAR_RUN_LIVE_TESTS") == "1", "set ASTAR_RUN_LIVE_TESTS=1 to run live integration tests")
    def test_public_round_endpoints(self) -> None:
        client = AstarClient()
        rounds = client.get_rounds()
        self.assertTrue(rounds)
        historical = next((item for item in rounds if item.get("status") == "completed"), None)
        self.assertIsNotNone(historical)
        detail = client.get_round_detail(str(historical["id"]))
        self.assertEqual(int(detail["seeds_count"]), 5)
        self.assertGreater(int(detail["map_width"]), 0)
        self.assertGreater(int(detail["map_height"]), 0)


if __name__ == "__main__":
    unittest.main()

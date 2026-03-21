from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from supervise_round_loop import heartbeat_is_stale


class SuperviseRoundLoopTests(unittest.TestCase):
    def test_heartbeat_is_stale_detects_old_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "heartbeat.json"
            path.write_text(
                json.dumps(
                    {
                        "generated_at": (datetime.now(timezone.utc) - timedelta(seconds=900)).isoformat(),
                    }
                )
            )
            self.assertTrue(heartbeat_is_stale(path, timeout_seconds=600))

    def test_heartbeat_is_stale_ignores_recent_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "heartbeat.json"
            path.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat()}))
            self.assertFalse(heartbeat_is_stale(path, timeout_seconds=600))


if __name__ == "__main__":
    unittest.main()

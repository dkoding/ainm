from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from round_loop import (
        build_missed_rounds_report,
        choose_active_round,
        acquire_loop_lock,
        has_pending_final_overwrite,
        log_loop_event,
        release_loop_lock,
        write_heartbeat,
        write_round_score_feedback,
        LoopState,
    )
except ImportError as exc:  # pragma: no cover - environment guard
    raise unittest.SkipTest(f"missing runtime dependency: {exc}") from exc


class RoundLoopTests(unittest.TestCase):
    def test_choose_active_round_prefers_latest_active_candidate(self) -> None:
        rounds = [
            {"id": "round-1", "status": "completed", "round_number": 1},
            {"id": "round-2", "status": "active", "round_number": 2, "started_at": "2026-03-21T10:00:00+00:00"},
        ]
        my_rounds = [
            {"round_id": "round-3", "status": "active", "round_number": 3, "started_at": "2026-03-21T11:00:00+00:00"}
        ]
        active = choose_active_round(rounds=rounds, my_rounds=my_rounds)
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(str(active.get("id") or active.get("round_id")), "round-3")

    def test_build_missed_rounds_report_only_lists_unsubmitted_completed_rounds(self) -> None:
        report = build_missed_rounds_report(
            [
                {"round_id": "r1", "status": "completed", "seeds_submitted": 0},
                {"round_id": "r2", "status": "completed", "seeds_submitted": 5},
                {"round_id": "r3", "status": "active", "seeds_submitted": 0},
            ]
        )
        self.assertEqual(len(report["missed_rounds"]), 1)
        self.assertEqual(report["missed_rounds"][0]["round_id"], "r1")

    def test_write_score_feedback_flags_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report_root = root / "round-2"
            report_root.mkdir(parents=True)
            (report_root / "report.json").write_text(
                json.dumps({"prediction_model": "sklearn", "strategy_evaluation": {"summary": {"best_variant_mean_round_score": 80.0}}})
            )
            output = write_round_score_feedback(
                root=root,
                round_id="round-2",
                my_rounds=[
                    {"round_id": "round-1", "status": "completed", "round_score": 78.0},
                    {"round_id": "round-2", "status": "completed", "round_score": 60.0},
                ],
            )
            payload = json.loads(output.read_text())
            self.assertIn("below_offline_expectation", payload["regression_flags"])

    def test_loop_lock_and_heartbeat_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            lock_path = root / "loop.lock"
            acquire_loop_lock(lock_path=lock_path, force=True)
            self.assertTrue(lock_path.exists())
            state = LoopState(last_active_round_id="round-9", last_tick_at="2026-03-21T10:00:00+00:00")
            write_heartbeat(root=root, state=state)
            self.assertTrue((root / "loop" / "heartbeat.json").exists())
            log_loop_event(root=root, event_type="tick", message="hello")
            self.assertTrue((root / "loop" / "events.jsonl").exists())
            release_loop_lock(lock_path=lock_path, owner_pid=int(json.loads(lock_path.read_text())["pid"]))
            self.assertFalse(lock_path.exists())

    def test_pending_final_overwrite_detects_initial_only_submissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            team_root = root / "round-1" / "team"
            initial_dir = team_root / "submissions_initial"
            final_dir = team_root / "submissions"
            initial_dir.mkdir(parents=True)
            final_dir.mkdir(parents=True)
            for seed_index in range(5):
                (initial_dir / f"seed_{seed_index}.json").write_text("{}")
            self.assertTrue(has_pending_final_overwrite(root=root, round_id="round-1", seeds_count=5))
            for seed_index in range(5):
                (final_dir / f"seed_{seed_index}.json").write_text("{}")
            self.assertFalse(has_pending_final_overwrite(root=root, round_id="round-1", seeds_count=5))


if __name__ == "__main__":
    unittest.main()

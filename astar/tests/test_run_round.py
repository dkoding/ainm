from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import json
    import tempfile
    from run_round import initial_stage_skip_reason, load_cached_tuning_report, should_stage_initial_submit
except ImportError as exc:  # pragma: no cover - environment guard
    raise unittest.SkipTest(f"missing runtime dependency: {exc}") from exc


class RunRoundLogicTests(unittest.TestCase):
    def test_should_stage_initial_submit_only_for_clean_submit_runs(self) -> None:
        self.assertTrue(
            should_stage_initial_submit(
                submit_enabled=True,
                simulate_enabled=True,
                staged_submit_enabled=True,
                existing_predictions_count=0,
            )
        )
        self.assertFalse(
            should_stage_initial_submit(
                submit_enabled=False,
                simulate_enabled=True,
                staged_submit_enabled=True,
                existing_predictions_count=0,
            )
        )
        self.assertFalse(
            should_stage_initial_submit(
                submit_enabled=True,
                simulate_enabled=False,
                staged_submit_enabled=True,
                existing_predictions_count=0,
            )
        )
        self.assertFalse(
            should_stage_initial_submit(
                submit_enabled=True,
                simulate_enabled=True,
                staged_submit_enabled=False,
                existing_predictions_count=0,
            )
        )
        self.assertFalse(
            should_stage_initial_submit(
                submit_enabled=True,
                simulate_enabled=True,
                staged_submit_enabled=True,
                existing_predictions_count=3,
            )
        )

    def test_initial_stage_skip_reason(self) -> None:
        self.assertEqual(
            initial_stage_skip_reason(
                submit_enabled=False,
                simulate_enabled=True,
                staged_submit_enabled=True,
                existing_predictions_count=0,
            ),
            "submit_disabled",
        )
        self.assertEqual(
            initial_stage_skip_reason(
                submit_enabled=True,
                simulate_enabled=False,
                staged_submit_enabled=True,
                existing_predictions_count=0,
            ),
            "simulate_disabled",
        )
        self.assertEqual(
            initial_stage_skip_reason(
                submit_enabled=True,
                simulate_enabled=True,
                staged_submit_enabled=False,
                existing_predictions_count=0,
            ),
            "staged_submit_disabled",
        )
        self.assertEqual(
            initial_stage_skip_reason(
                submit_enabled=True,
                simulate_enabled=True,
                staged_submit_enabled=True,
                existing_predictions_count=2,
            ),
            "preexisting_server_predictions",
        )

    def test_cached_tuning_report_ignores_unlabeled_completed_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "tuning.json"
            output.write_text(
                json.dumps(
                    {
                        "history_round_ids": ["round-1"],
                        "best": {"floor": 0.02, "history_prior_strength": 4.0},
                    }
                )
            )
            cached = load_cached_tuning_report(
                tuning_output=output,
                history_summary={
                    "rounds": [
                        {"round_id": "round-1", "analysis_cached_seeds": [0]},
                        {"round_id": "round-2", "analysis_cached_seeds": []},
                    ]
                },
            )
            self.assertIsNotNone(cached)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import numpy as np
    from prediction_variants import apply_observation_conditioning_to_prediction_set, strategy_signature
    from run_round import load_cached_strategy_evaluation, load_strategy_feedback_summary, select_prediction_variant
except ImportError as exc:  # pragma: no cover - environment guard
    raise unittest.SkipTest(f"missing runtime dependency: {exc}") from exc


class PredictionVariantTests(unittest.TestCase):
    def test_observation_conditioning_updates_unsampled_cells(self) -> None:
        round_detail = {
            "initial_states": [
                {
                    "grid": [
                        [11, 11, 11],
                        [11, 11, 11],
                        [10, 10, 10],
                    ],
                    "settlements": [],
                }
            ]
        }
        base = [np.full((3, 3, 6), 1.0 / 6.0, dtype=float)]
        observations = {
            0: [
                {
                    "grid": [[1, 1], [1, 1]],
                    "settlements": [],
                    "viewport": {"x": 0, "y": 0, "w": 2, "h": 2},
                    "width": 3,
                    "height": 3,
                }
            ]
        }
        adjusted = apply_observation_conditioning_to_prediction_set(
            round_detail=round_detail,
            predictions=base,
            observations_by_seed=observations,
            floor=0.0,
            floor_distribution=np.full(6, 1.0 / 6.0, dtype=float),
        )
        self.assertEqual(adjusted[0].shape, (3, 3, 6))
        self.assertFalse(np.allclose(adjusted[0][2, 2], base[0][2, 2]))

    def test_strategy_signature_changes_with_settings(self) -> None:
        base = strategy_signature(
            history_round_ids=["a", "b"],
            floor=0.01,
            prior_strength=2.0,
            history_prior_strength=2.0,
            neighborhood_radius=1,
            n_estimators=100,
            min_samples_leaf=2,
            random_state=0,
            simulate_queries=50,
            viewport_size=15,
        )
        changed = strategy_signature(
            history_round_ids=["a", "b"],
            floor=0.02,
            prior_strength=2.0,
            history_prior_strength=2.0,
            neighborhood_radius=1,
            n_estimators=100,
            min_samples_leaf=2,
            random_state=0,
            simulate_queries=50,
            viewport_size=15,
        )
        self.assertNotEqual(base, changed)

    def test_cached_strategy_evaluation_invalidates_on_signature_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "variant_selection.json"
            output.write_text(
                json.dumps(
                    {
                        "summary": {
                            "history_round_ids": ["round-1"],
                            "strategy_signature": strategy_signature(
                                history_round_ids=["round-1"],
                                floor=0.01,
                                prior_strength=2.0,
                                history_prior_strength=2.0,
                                neighborhood_radius=1,
                                n_estimators=100,
                                min_samples_leaf=2,
                                random_state=0,
                                simulate_queries=50,
                                viewport_size=15,
                            ),
                        }
                    }
                )
            )
            cached = load_cached_strategy_evaluation(
                strategy_evaluation_output=output,
                history_summary={"rounds": [{"round_id": "round-1"}]},
                floor=0.02,
                prior_strength=2.0,
                history_prior_strength=2.0,
                neighborhood_radius=1,
                n_estimators=100,
                min_samples_leaf=2,
                random_state=0,
                simulate_queries=50,
                viewport_size=15,
            )
            self.assertIsNone(cached)

    def test_strategy_feedback_blocks_regressing_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for round_id in ["round-1", "round-2"]:
                path = root / round_id / "team"
                path.mkdir(parents=True)
                (path / "score_feedback.json").write_text(
                    json.dumps(
                        {
                            "round_id": round_id,
                            "selected_variant": "sklearn",
                            "regression_flags": ["below_offline_expectation"],
                        }
                    )
                )
            feedback = load_strategy_feedback_summary(root=root)
            self.assertIn("sklearn", feedback["blocked_variants"])
            selected = select_prediction_variant(
                requested_model="auto",
                strategy_evaluation_summary={
                    "summary": {
                        "variants": [
                            {"variant": "sklearn", "mean_round_score": 80.0},
                            {"variant": "ensemble_sklearn_75", "mean_round_score": 79.0},
                        ]
                    }
                },
                strategy_feedback_summary=feedback,
                prediction_variants={"sklearn": [], "ensemble_sklearn_75": []},
            )
            self.assertEqual(selected, "ensemble_sklearn_75")


if __name__ == "__main__":
    unittest.main()

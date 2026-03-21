from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import numpy as np
    from history_priors import HistoryPriorModel, RoundPrior, infer_regime_history_prior_model, summarize_observed_round_behavior
except ImportError as exc:  # pragma: no cover - environment guard
    raise unittest.SkipTest(f"missing runtime dependency: {exc}") from exc


class HistoryPriorTests(unittest.TestCase):
    def _model(self) -> HistoryPriorModel:
        round_a = RoundPrior(
            round_id="round-a",
            round_number=1,
            terrain_probs={11: np.array([0.3, 0.35, 0.2, 0.05, 0.08, 0.02], dtype=float)},
            terrain_counts={11: 10},
            settlement_probs={False: np.array([0.1, 0.5, 0.1, 0.15, 0.1, 0.05], dtype=float)},
            settlement_counts={False: 5},
            global_class_probs=np.array([0.35, 0.30, 0.15, 0.10, 0.08, 0.02], dtype=float),
            summary_features={
                "development_mass": 0.45,
                "conflict_mass": 0.10,
                "port_mass": 0.15,
                "forest_mass": 0.08,
                "mountain_mass": 0.02,
                "port_ratio": 0.2,
            },
            seeds_used=1,
            cells_used=10,
        )
        round_b = RoundPrior(
            round_id="round-b",
            round_number=2,
            terrain_probs={11: np.array([0.7, 0.08, 0.02, 0.05, 0.1, 0.05], dtype=float)},
            terrain_counts={11: 10},
            settlement_probs={False: np.array([0.3, 0.2, 0.05, 0.25, 0.15, 0.05], dtype=float)},
            settlement_counts={False: 5},
            global_class_probs=np.array([0.72, 0.08, 0.02, 0.06, 0.08, 0.04], dtype=float),
            summary_features={
                "development_mass": 0.10,
                "conflict_mass": 0.06,
                "port_mass": 0.02,
                "forest_mass": 0.08,
                "mountain_mass": 0.04,
                "port_ratio": 0.05,
            },
            seeds_used=1,
            cells_used=10,
        )
        return HistoryPriorModel(
            round_priors=(round_a, round_b),
            round_weights={"round-a": 0.5, "round-b": 0.5},
            rounds_used=2,
            seeds_used=2,
            cells_used=20,
        )

    def test_summarize_observed_round_behavior_uses_settlement_stats(self) -> None:
        summary = summarize_observed_round_behavior(
            {
                0: [
                    {
                        "grid": [[1, 2], [3, 4]],
                        "settlements": [
                            {"population": 120, "food": 80, "wealth": 90, "defense": 30, "has_port": True, "alive": True, "owner_id": "a"},
                            {"population": 60, "food": 40, "wealth": 50, "defense": 20, "has_port": False, "alive": True, "owner_id": "b"},
                        ],
                        "viewport": {"x": 0, "y": 0, "w": 2, "h": 2},
                    }
                ]
            }
        )
        self.assertGreater(summary["development_signal"], 0.0)
        self.assertGreater(summary["owner_diversity"], 0.0)
        self.assertGreater(summary["mean_population"], 0.0)
        self.assertIn("trade_signal", summary)
        self.assertIn("harshness_signal", summary)

    def test_regime_inference_reweights_toward_better_matching_round(self) -> None:
        round_detail = {
            "initial_states": [
                {
                    "grid": [[11, 11], [11, 11]],
                    "settlements": [{"x": 0, "y": 0, "has_port": False}],
                }
            ]
        }
        observations = {
            0: [
                {
                    "grid": [[1, 2], [1, 1]],
                    "settlements": [
                        {"population": 100, "food": 80, "wealth": 60, "defense": 10, "has_port": True, "alive": True, "owner_id": "a"}
                    ],
                    "viewport": {"x": 0, "y": 0, "w": 2, "h": 2},
                }
            ]
        }
        adjusted, summary = infer_regime_history_prior_model(self._model(), round_detail=round_detail, observations_by_seed=observations)
        self.assertIsNotNone(adjusted)
        self.assertIsNotNone(summary)
        assert adjusted is not None
        self.assertGreater(adjusted.round_weights["round-a"], adjusted.round_weights["round-b"])


if __name__ == "__main__":
    unittest.main()

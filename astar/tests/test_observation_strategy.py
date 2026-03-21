from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import numpy as np
    from history_priors import HistoryPriorModel, RoundPrior
    from observation_strategy import build_round_viewport_plan, select_next_viewport_request
except ImportError as exc:  # pragma: no cover - environment guard
    raise unittest.SkipTest(f"missing runtime dependency: {exc}") from exc


class ObservationStrategyTests(unittest.TestCase):
    def _round_detail(self) -> dict:
        grid = [[11 for _ in range(40)] for _ in range(40)]
        return {
            "map_width": 40,
            "map_height": 40,
            "seeds_count": 5,
            "initial_states": [
                {
                    "grid": grid,
                    "settlements": [{"x": 10 + seed_index, "y": 10 + seed_index, "has_port": seed_index % 2 == 0}],
                }
                for seed_index in range(5)
            ],
        }

    def test_round_plan_respects_total_budget(self) -> None:
        round_detail = self._round_detail()
        plan = build_round_viewport_plan(round_detail=round_detail, total_queries=7, viewport_size=15)
        total = sum(len(items) for items in plan.values())
        self.assertLessEqual(total, 7)
        self.assertGreater(total, 0)

    def test_small_budget_spreads_one_query_per_seed_first(self) -> None:
        plan = build_round_viewport_plan(round_detail=self._round_detail(), total_queries=5, viewport_size=15)
        self.assertEqual(sum(len(items) for items in plan.values()), 5)
        self.assertEqual([len(plan[seed_index]) for seed_index in range(5)], [1, 1, 1, 1, 1])

    def test_full_sweep_tiles_entire_40x40_map_in_nine_calls_per_seed(self) -> None:
        plan = build_round_viewport_plan(round_detail=self._round_detail(), total_queries=45, viewport_size=15)
        self.assertEqual(sum(len(items) for items in plan.values()), 45)
        for seed_index in range(5):
            requests = plan[seed_index]
            self.assertEqual(len(requests), 9)
            covered = set()
            sizes = set()
            for request in requests:
                sizes.add((request.viewport_w, request.viewport_h))
                for y in range(request.viewport_y, request.viewport_y + request.viewport_h):
                    for x in range(request.viewport_x, request.viewport_x + request.viewport_w):
                        covered.add((x, y))
            self.assertEqual(len(covered), 40 * 40)
            self.assertIn((15, 15), sizes)
            self.assertIn((10, 10), sizes)

    def test_budget_beyond_full_sweep_is_used_for_repeats(self) -> None:
        plan = build_round_viewport_plan(round_detail=self._round_detail(), total_queries=50, viewport_size=15)
        self.assertEqual(sum(len(items) for items in plan.values()), 50)
        self.assertEqual([len(plan[seed_index]) for seed_index in range(5)], [10, 10, 10, 10, 10])
        for seed_index in range(5):
            unique_windows = {
                (item.viewport_x, item.viewport_y, item.viewport_w, item.viewport_h)
                for item in plan[seed_index]
            }
            self.assertEqual(len(unique_windows), 9)

    def test_select_next_uses_repeat_phase_after_unique_coverage(self) -> None:
        round_detail = self._round_detail()
        full_unique_plan = build_round_viewport_plan(round_detail=round_detail, total_queries=45, viewport_size=15)
        uncertain_sample_a = {
            "grid": [[1 for _ in range(15)] for _ in range(15)],
            "settlements": [],
            "viewport": {"x": 0, "y": 0, "w": 15, "h": 15},
            "width": 40,
            "height": 40,
            "queries_used": 1,
            "queries_max": 50,
        }
        uncertain_sample_b = {
            "grid": [[4 for _ in range(15)] for _ in range(15)],
            "settlements": [],
            "viewport": {"x": 0, "y": 0, "w": 15, "h": 15},
            "width": 40,
            "height": 40,
            "queries_used": 2,
            "queries_max": 50,
        }
        selection = select_next_viewport_request(
            round_detail=round_detail,
            viewport_size=15,
            observations_by_seed={0: [uncertain_sample_a, uncertain_sample_b]},
            already_selected=full_unique_plan,
        )
        self.assertIsNotNone(selection)
        assert selection is not None
        self.assertEqual(selection["phase"], "exploit")
        self.assertIn("predicted_dynamic_mass", selection["score_components"])
        self.assertIn("observed_activity_mass", selection["score_components"])

    def test_regime_disagreement_is_reported_in_selection(self) -> None:
        round_detail = self._round_detail()
        round_detail["initial_states"][0]["grid"][10][10] = 1
        round_detail["initial_states"][0]["settlements"] = [{"x": 10, "y": 10, "has_port": False}]
        model = HistoryPriorModel(
            round_priors=(
                RoundPrior(
                    round_id="round-a",
                    round_number=1,
                    terrain_probs={1: np.array([0.05, 0.75, 0.05, 0.05, 0.05, 0.05], dtype=float)},
                    terrain_counts={1: 1},
                    settlement_probs={False: np.array([0.05, 0.75, 0.05, 0.05, 0.05, 0.05], dtype=float)},
                    settlement_counts={False: 1},
                    global_class_probs=np.array([0.70, 0.10, 0.05, 0.03, 0.09, 0.03], dtype=float),
                    summary_features={"development_mass": 0.15, "conflict_mass": 0.03, "port_mass": 0.05, "forest_mass": 0.09, "mountain_mass": 0.03, "port_ratio": 0.05},
                    seeds_used=1,
                    cells_used=1,
                ),
                RoundPrior(
                    round_id="round-b",
                    round_number=2,
                    terrain_probs={1: np.array([0.05, 0.10, 0.05, 0.70, 0.05, 0.05], dtype=float)},
                    terrain_counts={1: 1},
                    settlement_probs={False: np.array([0.05, 0.10, 0.05, 0.70, 0.05, 0.05], dtype=float)},
                    settlement_counts={False: 1},
                    global_class_probs=np.array([0.72, 0.08, 0.04, 0.04, 0.08, 0.04], dtype=float),
                    summary_features={"development_mass": 0.12, "conflict_mass": 0.04, "port_mass": 0.04, "forest_mass": 0.08, "mountain_mass": 0.04, "port_ratio": 0.04},
                    seeds_used=1,
                    cells_used=1,
                ),
            ),
            round_weights={"round-a": 0.5, "round-b": 0.5},
            rounds_used=2,
            seeds_used=2,
            cells_used=2,
        )
        selection = select_next_viewport_request(
            round_detail=round_detail,
            viewport_size=15,
            observations_by_seed={},
            history_prior_model=model,
        )
        self.assertIsNotNone(selection)
        assert selection is not None
        self.assertIn("regime_disagreement", selection["score_components"])
        self.assertGreaterEqual(selection["score_components"]["regime_disagreement"], 0.0)


if __name__ == "__main__":
    unittest.main()

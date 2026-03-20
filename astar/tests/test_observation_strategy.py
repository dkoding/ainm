from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from observation_strategy import build_round_viewport_plan


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


if __name__ == "__main__":
    unittest.main()

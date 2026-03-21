from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import numpy as np
    from scoring import entropy_weighted_kl, seed_score
except ImportError as exc:  # pragma: no cover - environment guard
    raise unittest.SkipTest(f"missing runtime dependency: {exc}") from exc


class ScoringTests(unittest.TestCase):
    def test_perfect_prediction_scores_100(self) -> None:
        ground_truth = np.array([[[0.1, 0.4, 0.2, 0.1, 0.1, 0.1]]], dtype=float)
        self.assertAlmostEqual(entropy_weighted_kl(ground_truth, ground_truth), 0.0)
        self.assertAlmostEqual(seed_score(ground_truth, ground_truth), 100.0)

    def test_worse_prediction_scores_lower(self) -> None:
        ground_truth = np.array([[[0.1, 0.4, 0.2, 0.1, 0.1, 0.1]]], dtype=float)
        better = np.array([[[0.12, 0.35, 0.18, 0.1, 0.13, 0.12]]], dtype=float)
        worse = np.array([[[0.7, 0.05, 0.05, 0.05, 0.1, 0.05]]], dtype=float)
        self.assertLess(seed_score(ground_truth, worse), seed_score(ground_truth, better))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import numpy as np
    from sklearn_model import build_round_predictions_from_model, train_random_forest_from_history
except ImportError as exc:  # pragma: no cover - environment guard
    raise unittest.SkipTest(f"missing runtime dependency: {exc}") from exc


@unittest.skipUnless(importlib.util.find_spec("sklearn") is not None, "scikit-learn not installed")
class SklearnModelTests(unittest.TestCase):
    def test_train_and_predict_round_tensor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            history_root = root / "history"
            rounds_root = history_root / "rounds"

            index = {"rounds": []}
            for round_number, round_id, base_grid, truth in [
                (
                    1,
                    "round-1",
                    [[11, 4], [10, 1]],
                    np.array(
                        [
                            [[1, 0, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0]],
                            [[1, 0, 0, 0, 0, 0], [0, 1, 0, 0, 0, 0]],
                        ],
                        dtype=float,
                    ),
                ),
                (
                    2,
                    "round-2",
                    [[11, 4], [10, 2]],
                    np.array(
                        [
                            [[1, 0, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0]],
                            [[1, 0, 0, 0, 0, 0], [0, 0, 1, 0, 0, 0]],
                        ],
                        dtype=float,
                    ),
                ),
            ]:
                analysis_dir = rounds_root / round_id / "team" / "analysis"
                public_dir = rounds_root / round_id / "public"
                analysis_dir.mkdir(parents=True)
                public_dir.mkdir(parents=True)

                round_detail = {
                    "round_number": round_number,
                    "map_width": 2,
                    "map_height": 2,
                    "seeds_count": 1,
                    "initial_states": [
                        {
                            "grid": base_grid,
                            "settlements": [{"x": 1, "y": 1, "has_port": base_grid[1][1] == 2}],
                        }
                    ],
                }
                (public_dir / "round_detail.json").write_text(json.dumps(round_detail))

                analysis = {
                    "width": 2,
                    "height": 2,
                    "initial_grid": base_grid,
                    "prediction": None,
                    "ground_truth": truth.tolist(),
                    "score": 100.0,
                }
                (analysis_dir / "seed_0.json").write_text(json.dumps(analysis))
                index["rounds"].append(
                    {
                        "round_id": round_id,
                        "round_number": round_number,
                        "analysis_cached_seeds": [0],
                    }
                )

            (history_root / "index.json").write_text(json.dumps(index))

            artifact = train_random_forest_from_history(root=root, n_estimators=20, min_samples_leaf=1, random_state=7)
            round_detail = json.loads((rounds_root / "round-1" / "public" / "round_detail.json").read_text())
            predictions = build_round_predictions_from_model(artifact, round_detail)

            self.assertEqual(len(predictions), 1)
            self.assertEqual(predictions[0].shape, (2, 2, 6))
            self.assertTrue(np.allclose(predictions[0].sum(axis=-1), 1.0))
            self.assertGreater(artifact.calibration_temperature, 0.0)
            self.assertIn("calibration_temperature", artifact.to_metadata())


if __name__ == "__main__":
    unittest.main()

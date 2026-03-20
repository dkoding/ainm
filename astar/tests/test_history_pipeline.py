from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_history_dataset import write_history_dataset
from evaluate_history import evaluate_history_cache
from history_priors import build_history_prior_model


class HistoryPipelineTests(unittest.TestCase):
    def test_history_prior_and_dataset_can_be_built(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            history_root = root / "history"
            analysis_dir = history_root / "rounds" / "round-1" / "team" / "analysis"
            public_dir = history_root / "rounds" / "round-1" / "public"
            analysis_dir.mkdir(parents=True)
            public_dir.mkdir(parents=True)

            (history_root / "index.json").write_text(
                json.dumps(
                    {
                        "rounds": [
                            {
                                "round_id": "round-1",
                                "round_number": 1,
                                "analysis_cached_seeds": [0],
                            }
                        ]
                    }
                )
            )

            round_detail = {
                "round_number": 1,
                "map_width": 2,
                "map_height": 2,
                "seeds_count": 1,
                "initial_states": [
                    {
                        "grid": [[11, 4], [10, 1]],
                        "settlements": [{"x": 1, "y": 1, "has_port": False}],
                    }
                ],
            }
            (public_dir / "round_detail.json").write_text(json.dumps(round_detail))

            ground_truth = np.array(
                [
                    [[1, 0, 0, 0, 0, 0], [0, 0, 0, 0, 1, 0]],
                    [[1, 0, 0, 0, 0, 0], [0, 1, 0, 0, 0, 0]],
                ],
                dtype=float,
            )
            analysis = {
                "width": 2,
                "height": 2,
                "initial_grid": [[11, 4], [10, 1]],
                "prediction": ground_truth.tolist(),
                "ground_truth": ground_truth.tolist(),
                "score": 100.0,
            }
            (analysis_dir / "seed_0.json").write_text(json.dumps(analysis))

            prior_model = build_history_prior_model(root=root)
            self.assertIsNotNone(prior_model)

            dataset_summary = write_history_dataset(root=root, output_path=root / "dataset.jsonl")
            self.assertEqual(dataset_summary["records_written"], 4)

            evaluation = evaluate_history_cache(root=root, leave_one_round_out=False)
            self.assertEqual(evaluation["summary"]["completed_rounds_evaluated"], 1)


if __name__ == "__main__":
    unittest.main()

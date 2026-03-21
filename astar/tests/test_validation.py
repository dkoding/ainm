from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import numpy as np
    from validation import AstarValidationError, validate_prediction_array, validate_submission_payload
except ImportError as exc:  # pragma: no cover - environment guard
    raise unittest.SkipTest(f"missing runtime dependency: {exc}") from exc


class ValidationTests(unittest.TestCase):
    def test_validate_prediction_array_accepts_normalized_tensor(self) -> None:
        tensor = np.full((2, 3, 6), 1 / 6, dtype=float)
        validated = validate_prediction_array(tensor, expected_height=2, expected_width=3)
        self.assertEqual(validated.shape, (2, 3, 6))

    def test_validate_prediction_array_rejects_bad_sum(self) -> None:
        tensor = np.full((2, 2, 6), 0.2, dtype=float)
        with self.assertRaises(AstarValidationError):
            validate_prediction_array(tensor)

    def test_validate_submission_payload_rejects_zero_probability(self) -> None:
        tensor = np.full((1, 1, 6), 0.2, dtype=float)
        tensor[0, 0, 0] = 0.0
        tensor[0, 0] /= tensor[0, 0].sum()
        with self.assertRaises(AstarValidationError):
            validate_submission_payload({"round_id": "round-1", "seed_index": 0, "prediction": tensor.tolist()})


if __name__ == "__main__":
    unittest.main()

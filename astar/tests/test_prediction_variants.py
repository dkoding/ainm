from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import numpy as np
    from prediction_variants import (
        apply_observation_conditioning_to_prediction_set,
        score_prediction_variants_for_live_round,
        strategy_signature,
    )
    from run_round import (
        apply_prediction_mass_guardrails,
        load_cached_strategy_evaluation,
        load_strategy_feedback_summary,
        select_prediction_variant,
    )
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

    def test_live_variant_ranking_prefers_better_observation_fit(self) -> None:
        round_detail = {
            "initial_states": [
                {
                    "grid": [
                        [11, 11, 11],
                        [11, 11, 11],
                        [11, 11, 11],
                    ],
                    "settlements": [{"x": 1, "y": 1, "has_port": False}],
                }
            ]
        }
        observations = {
            0: [
                {
                    "grid": [[1, 1], [1, 1]],
                    "settlements": [{"x": 1, "y": 1, "has_port": False, "alive": True, "owner_id": "a"}],
                    "viewport": {"x": 0, "y": 0, "w": 2, "h": 2},
                    "width": 3,
                    "height": 3,
                }
            ]
        }
        weak = np.full((3, 3, 6), 1.0 / 6.0, dtype=float)
        strong = np.full((3, 3, 6), 1.0 / 6.0, dtype=float)
        strong[:, :, 1] = 0.55
        strong[:, :, 0] = 0.15
        strong[:, :, 2] = 0.10
        strong[:, :, 3] = 0.05
        strong[:, :, 4] = 0.10
        strong[:, :, 5] = 0.05
        strong /= strong.sum(axis=-1, keepdims=True)
        live = score_prediction_variants_for_live_round(
            round_detail=round_detail,
            prediction_variants={"weak": [weak], "strong": [strong]},
            observations_by_seed=observations,
            strategy_evaluation_summary=None,
        )
        self.assertIsNotNone(live)
        assert live is not None
        self.assertEqual(live["best_variant"], "strong")

    def test_live_variant_ranking_respects_blocked_variants(self) -> None:
        selected = select_prediction_variant(
            requested_model="auto",
            strategy_evaluation_summary=None,
            strategy_feedback_summary={"blocked_variants": ["strong"]},
            prediction_variants={"strong": [], "weak": []},
            live_variant_summary={
                "variants": [
                    {"variant": "strong", "live_score": 1.0},
                    {"variant": "weak", "live_score": 0.5},
                ]
            },
        )
        self.assertEqual(selected, "weak")

    def test_live_variant_ranking_does_not_switch_to_raw_sklearn_without_clear_activity_win(self) -> None:
        selected = select_prediction_variant(
            requested_model="auto",
            strategy_evaluation_summary={
                "summary": {
                    "variants": [
                        {"variant": "sklearn_observation_context", "mean_round_score": 78.0},
                        {"variant": "sklearn", "mean_round_score": 75.0},
                    ]
                }
            },
            strategy_feedback_summary={"blocked_variants": []},
            prediction_variants={"sklearn": [], "sklearn_observation_context": []},
            live_variant_summary={
                "variants": [
                    {
                        "variant": "sklearn",
                        "live_score": 0.69,
                        "observation_match": 0.68,
                        "activity_gap": 0.53,
                    },
                    {
                        "variant": "sklearn_observation_context",
                        "live_score": 0.60,
                        "observation_match": 0.56,
                        "activity_gap": 0.50,
                    },
                ]
            },
        )
        self.assertEqual(selected, "sklearn_observation_context")

    def test_prediction_mass_guardrail_blends_back_extreme_dynamic_shift(self) -> None:
        anchor = np.zeros((2, 2, 6), dtype=float)
        anchor[:, :, 0] = 0.80
        anchor[:, :, 1] = 0.10
        anchor[:, :, 4] = 0.10
        selected = np.zeros((2, 2, 6), dtype=float)
        selected[:, :, 0] = 0.40
        selected[:, :, 1] = 0.45
        selected[:, :, 2] = 0.10
        selected[:, :, 4] = 0.05
        guarded, summary = apply_prediction_mass_guardrails(
            predictions=[selected],
            anchor_predictions=[anchor],
            observed_summary={
                "development_signal": 0.2,
                "trade_signal": 0.1,
                "conflict_signal": 0.05,
                "harshness_signal": 0.1,
                "port_signal": 0.1,
            },
            selected_variant="sklearn",
            anchor_variant="sklearn_observation_context",
        )
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertLess(summary["blend_alpha"], 1.0)
        self.assertLess(summary["final_class_mass"][1], summary["selected_class_mass"][1])


if __name__ == "__main__":
    unittest.main()

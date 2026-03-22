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
        apply_resource_post_observation_to_seed,
        build_round_observation_context,
        build_prediction_variants,
        apply_observation_conditioning_to_prediction_set,
        score_prediction_variants_for_live_round,
        strategy_signature,
    )
    from run_round import (
        apply_prediction_mass_guardrails,
        load_cached_strategy_evaluation,
        load_strategy_feedback_summary,
        select_guardrail_anchor_variant,
        select_prediction_variant,
    )
    from sklearn_model import (
        FEATURE_COLUMNS,
        POST_OBSERVATION_FEATURE_COLUMNS,
        PostObservationModelArtifact,
        SklearnModelArtifact,
        apply_post_observation_model_to_prediction_set,
    )
except ImportError as exc:  # pragma: no cover - environment guard
    raise unittest.SkipTest(f"missing runtime dependency: {exc}") from exc


class PredictionVariantTests(unittest.TestCase):
    class _DummyEstimator:
        def __init__(self, probs: list[float]) -> None:
            self._probs = np.asarray(probs, dtype=float)

        def predict(self, X: np.ndarray) -> np.ndarray:
            return np.tile(self._probs, (X.shape[0], 1))

    def _round_detail_with_coast(self) -> dict:
        return {
            "map_width": 3,
            "map_height": 3,
            "initial_states": [
                {
                    "grid": [
                        [11, 11, 11],
                        [11, 11, 11],
                        [10, 10, 10],
                    ],
                    "settlements": [{"x": 1, "y": 1, "has_port": False}],
                }
            ],
        }

    def _trade_heavy_observations(self) -> dict[int, list[dict]]:
        return {
            0: [
                {
                    "grid": [[2, 2], [2, 2]],
                    "settlements": [{"x": 1, "y": 1, "has_port": True, "alive": True, "owner_id": "a"}],
                    "viewport": {"x": 1, "y": 1, "w": 2, "h": 2},
                    "width": 3,
                    "height": 3,
                }
            ]
        }

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
                history_summary={"rounds": [{"round_id": "round-1", "analysis_cached_seeds": [0]}]},
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

    def test_cached_strategy_evaluation_ignores_unlabeled_completed_rounds(self) -> None:
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
                history_summary={
                    "rounds": [
                        {"round_id": "round-1", "analysis_cached_seeds": [0]},
                        {"round_id": "round-2", "analysis_cached_seeds": []},
                    ]
                },
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
            self.assertIsNotNone(cached)

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

    def test_live_variant_ranking_backfills_missing_offline_score_for_new_variant(self) -> None:
        round_detail = self._round_detail_with_coast()
        observations = self._trade_heavy_observations()
        learned = np.zeros((3, 3, 6), dtype=float)
        learned[:, :, 0] = 0.58
        learned[:, :, 1] = 0.10
        learned[:, :, 2] = 0.08
        learned[:, :, 3] = 0.04
        learned[:, :, 4] = 0.15
        learned[:, :, 5] = 0.05
        conditioned = np.zeros((3, 3, 6), dtype=float)
        conditioned[:, :, 0] = 0.60
        conditioned[:, :, 1] = 0.10
        conditioned[:, :, 2] = 0.05
        conditioned[:, :, 3] = 0.05
        conditioned[:, :, 4] = 0.15
        conditioned[:, :, 5] = 0.05
        live = score_prediction_variants_for_live_round(
            round_detail=round_detail,
            prediction_variants={
                "sklearn_learned_post_observation": [learned],
                "sklearn_observation_context": [conditioned],
            },
            observations_by_seed=observations,
            strategy_evaluation_summary={
                "summary": {
                    "variants": [
                        {"variant": "sklearn_observation_context", "mean_round_score": 78.0},
                        {"variant": "sklearn", "mean_round_score": 75.0},
                    ]
                }
            },
        )
        self.assertIsNotNone(live)
        assert live is not None
        learned_report = next(
            item for item in live["variants"] if item["variant"] == "sklearn_learned_post_observation"
        )
        self.assertEqual(learned_report["offline_score_source"], "fallback:sklearn_observation_context")
        self.assertAlmostEqual(learned_report["offline_mean_round_score"], 78.0)

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

    def test_low_activity_round_prefers_safer_conditioned_baseline_family(self) -> None:
        def tensor(empty: float, settlement: float, port: float, ruin: float, forest: float, mountain: float) -> list[np.ndarray]:
            arr = np.zeros((1, 1, 6), dtype=float)
            arr[0, 0] = np.array([empty, settlement, port, ruin, forest, mountain], dtype=float)
            arr /= arr.sum(axis=-1, keepdims=True)
            return [arr]

        selected = select_prediction_variant(
            requested_model="auto",
            strategy_evaluation_summary={
                "summary": {
                    "variants": [
                        {"variant": "sklearn_observation_context", "mean_round_score": 78.0},
                        {"variant": "ensemble_observation_context_50", "mean_round_score": 75.0},
                        {"variant": "baseline_history_global_post_observation", "mean_round_score": 72.1},
                        {"variant": "baseline_history_observation_context", "mean_round_score": 71.8},
                        {"variant": "baseline_history", "mean_round_score": 59.7},
                    ]
                }
            },
            strategy_feedback_summary={"blocked_variants": []},
            prediction_variants={
                "baseline_history": tensor(0.68, 0.066, 0.009, 0.014, 0.204, 0.028),
                "baseline_history_observation_context": tensor(0.713, 0.037, 0.004, 0.008, 0.214, 0.024),
                "baseline_history_global_post_observation": tensor(0.706, 0.038, 0.004, 0.009, 0.219, 0.024),
                "ensemble_observation_context_50": tensor(0.701, 0.050, 0.004, 0.010, 0.213, 0.022),
                "sklearn_observation_context": tensor(0.692, 0.059, 0.004, 0.012, 0.212, 0.021),
            },
            live_variant_summary={
                "observed_summary": {
                    "class_probs": [0.733, 0.0097, 0.0001, 0.0023, 0.2314, 0.0235],
                },
                "variants": [
                    {"variant": "baseline_history", "live_score": 0.8301, "observation_match": 0.8491, "activity_gap": 0.5542, "offline_mean_round_score": 59.7},
                    {"variant": "baseline_history_observation_context", "live_score": 0.8236, "observation_match": 0.8137, "activity_gap": 0.5352, "offline_mean_round_score": 71.8},
                    {"variant": "baseline_history_global_post_observation", "live_score": 0.8180, "observation_match": 0.8071, "activity_gap": 0.5332, "offline_mean_round_score": 72.1},
                    {"variant": "ensemble_observation_context_50", "live_score": 0.8080, "observation_match": 0.7932, "activity_gap": 0.5444, "offline_mean_round_score": 75.5},
                    {"variant": "sklearn_observation_context", "live_score": 0.8018, "observation_match": 0.7834, "activity_gap": 0.5506, "offline_mean_round_score": 78.0},
                ]
            },
        )
        self.assertEqual(selected, "baseline_history_observation_context")

    def test_moderately_sparse_round_prefers_conditioned_ensemble_over_aggressive_live_winner(self) -> None:
        selected = select_prediction_variant(
            requested_model="auto",
            strategy_evaluation_summary={
                "summary": {
                    "variants": [
                        {"variant": "sklearn_observation_context", "mean_round_score": 78.0},
                        {"variant": "ensemble_observation_context_50", "mean_round_score": 75.5},
                        {"variant": "ensemble_global_post_observation_50", "mean_round_score": 75.3},
                        {"variant": "sklearn_global_post_observation", "mean_round_score": 77.4},
                    ]
                }
            },
            strategy_feedback_summary={"blocked_variants": []},
            prediction_variants={
                "sklearn": [],
                "ensemble_sklearn_75": [],
                "ensemble_observation_context_50": [],
                "ensemble_global_post_observation_50": [],
                "sklearn_global_post_observation": [],
                "sklearn_observation_context": [],
                "baseline_history_observation_context": [],
                "baseline_history_global_post_observation": [],
            },
            live_variant_summary={
                "observed_summary": {
                    "class_probs": [0.6881, 0.0579, 0.0027, 0.0089, 0.2182, 0.0242],
                    "development_signal": 0.0641,
                    "trade_signal": 0.0226,
                    "port_signal": 0.0441,
                    "harshness_signal": 0.4489,
                },
                "variants": [
                    {"variant": "sklearn", "live_score": 0.8578, "observation_match": 0.8402, "activity_gap": 0.5315, "offline_mean_round_score": 75.2},
                    {"variant": "ensemble_sklearn_75", "live_score": 0.8478, "observation_match": 0.8294, "activity_gap": 0.5246, "offline_mean_round_score": 74.8},
                    {"variant": "sklearn_observation_context", "live_score": 0.7947, "observation_match": 0.7650, "activity_gap": 0.5052, "offline_mean_round_score": 78.0},
                    {"variant": "ensemble_observation_context_50", "live_score": 0.7825, "observation_match": 0.7563, "activity_gap": 0.4991, "offline_mean_round_score": 75.5},
                    {"variant": "baseline_history_observation_context", "live_score": 0.7788, "observation_match": 0.7578, "activity_gap": 0.4911, "offline_mean_round_score": 71.8},
                    {"variant": "ensemble_global_post_observation_50", "live_score": 0.7761, "observation_match": 0.7500, "activity_gap": 0.4979, "offline_mean_round_score": 75.3},
                    {"variant": "baseline_history_global_post_observation", "live_score": 0.7733, "observation_match": 0.7514, "activity_gap": 0.4895, "offline_mean_round_score": 72.1},
                    {"variant": "sklearn_global_post_observation", "live_score": 0.7873, "observation_match": 0.7586, "activity_gap": 0.5045, "offline_mean_round_score": 77.4},
                ],
            },
        )
        self.assertEqual(selected, "ensemble_observation_context_50")

    def test_ultra_low_activity_round_allows_safer_conditioned_baseline_when_gap_is_small(self) -> None:
        def tensor(empty: float, settlement: float, port: float, ruin: float, forest: float, mountain: float) -> list[np.ndarray]:
            arr = np.zeros((1, 1, 6), dtype=float)
            arr[0, 0] = np.array([empty, settlement, port, ruin, forest, mountain], dtype=float)
            arr /= arr.sum(axis=-1, keepdims=True)
            return [arr]

        selected = select_prediction_variant(
            requested_model="auto",
            strategy_evaluation_summary={
                "summary": {
                    "variants": [
                        {"variant": "baseline_history_observation_context", "mean_round_score": 71.8},
                        {"variant": "baseline_history_global_post_observation", "mean_round_score": 72.1},
                        {"variant": "ensemble_observation_context_50", "mean_round_score": 75.5},
                        {"variant": "sklearn_observation_context", "mean_round_score": 78.0},
                        {"variant": "baseline_history", "mean_round_score": 59.7},
                    ]
                }
            },
            strategy_feedback_summary={"blocked_variants": []},
            prediction_variants={
                "baseline_history": tensor(0.69, 0.064, 0.009, 0.013, 0.200, 0.024),
                "baseline_history_observation_context": tensor(0.714, 0.036, 0.003, 0.007, 0.216, 0.024),
                "baseline_history_global_post_observation": tensor(0.709, 0.037, 0.003, 0.008, 0.219, 0.024),
                "ensemble_observation_context_50": tensor(0.699, 0.048, 0.004, 0.010, 0.217, 0.022),
                "sklearn_observation_context": tensor(0.690, 0.057, 0.004, 0.011, 0.217, 0.021),
            },
            live_variant_summary={
                "observed_summary": {
                    "class_probs": [0.7321, 0.0278, 0.0012, 0.0037, 0.2108, 0.0244],
                },
                "variants": [
                    {"variant": "baseline_history", "live_score": 0.8505, "observation_match": 0.8638, "activity_gap": 0.5314, "offline_mean_round_score": 59.7},
                    {"variant": "baseline_history_observation_context", "live_score": 0.8282, "observation_match": 0.8139, "activity_gap": 0.5175, "offline_mean_round_score": 71.8},
                    {"variant": "baseline_history_global_post_observation", "live_score": 0.8228, "observation_match": 0.8076, "activity_gap": 0.5159, "offline_mean_round_score": 72.1},
                    {"variant": "ensemble_observation_context_50", "live_score": 0.8036, "observation_match": 0.7850, "activity_gap": 0.5293, "offline_mean_round_score": 75.5},
                    {"variant": "sklearn_observation_context", "live_score": 0.7879, "observation_match": 0.7666, "activity_gap": 0.5389, "offline_mean_round_score": 78.0},
                ],
            },
        )
        self.assertEqual(selected, "baseline_history_observation_context")

    def test_guardrail_anchor_prefers_moderately_sparse_conditioned_variant_for_aggressive_selection(self) -> None:
        anchor = select_guardrail_anchor_variant(
            requested_model="auto",
            strategy_evaluation_summary=None,
            strategy_feedback_summary={"blocked_variants": []},
            prediction_variants={
                "sklearn": [],
                "ensemble_sklearn_75": [],
                "ensemble_observation_context_50": [],
                "ensemble_global_post_observation_50": [],
                "sklearn_global_post_observation": [],
                "sklearn_observation_context": [],
                "baseline_history_observation_context": [],
                "baseline_history_global_post_observation": [],
            },
            selected_variant="sklearn",
            live_variant_summary={
                "observed_summary": {
                    "class_probs": [0.6881, 0.0579, 0.0027, 0.0089, 0.2182, 0.0242],
                    "development_signal": 0.0641,
                    "trade_signal": 0.0226,
                    "port_signal": 0.0441,
                    "harshness_signal": 0.4489,
                },
                "variants": [
                    {"variant": "sklearn", "live_score": 0.8578, "observation_match": 0.8402, "activity_gap": 0.5315, "offline_mean_round_score": 75.2},
                    {"variant": "ensemble_observation_context_50", "live_score": 0.7825, "observation_match": 0.7563, "activity_gap": 0.4991, "offline_mean_round_score": 75.5},
                    {"variant": "ensemble_global_post_observation_50", "live_score": 0.7761, "observation_match": 0.7500, "activity_gap": 0.4979, "offline_mean_round_score": 75.3},
                    {"variant": "sklearn_global_post_observation", "live_score": 0.7873, "observation_match": 0.7586, "activity_gap": 0.5045, "offline_mean_round_score": 77.4},
                    {"variant": "sklearn_observation_context", "live_score": 0.7947, "observation_match": 0.7650, "activity_gap": 0.5052, "offline_mean_round_score": 78.0},
                    {"variant": "baseline_history_observation_context", "live_score": 0.7788, "observation_match": 0.7578, "activity_gap": 0.4911, "offline_mean_round_score": 71.8},
                    {"variant": "baseline_history_global_post_observation", "live_score": 0.7733, "observation_match": 0.7514, "activity_gap": 0.4895, "offline_mean_round_score": 72.1},
                ],
            },
        )
        self.assertEqual(anchor, "ensemble_observation_context_50")

    def test_learned_post_observation_model_lifts_trade_near_coast(self) -> None:
        coefficients = np.zeros((len(POST_OBSERVATION_FEATURE_COLUMNS), 6), dtype=float)
        coefficients[POST_OBSERVATION_FEATURE_COLUMNS.index("obs_trade_signal"), 2] = 0.10
        coefficients[POST_OBSERVATION_FEATURE_COLUMNS.index("obs_trade_signal"), 0] = -0.07
        coefficients[POST_OBSERVATION_FEATURE_COLUMNS.index("trade_x_coast_adjacent"), 2] = 0.35
        coefficients[POST_OBSERVATION_FEATURE_COLUMNS.index("trade_x_coast_adjacent"), 0] = -0.20
        model = PostObservationModelArtifact(
            feature_columns=list(POST_OBSERVATION_FEATURE_COLUMNS),
            feature_mean=np.zeros(len(POST_OBSERVATION_FEATURE_COLUMNS), dtype=float),
            feature_scale=np.ones(len(POST_OBSERVATION_FEATURE_COLUMNS), dtype=float),
            coefficients=coefficients,
            intercept=np.zeros(6, dtype=float),
            ridge_alpha=1.0,
            training_summary={},
        )
        artifact = SklearnModelArtifact(
            estimator=None,
            model_type="random_forest_regressor",
            feature_columns=list(FEATURE_COLUMNS),
            class_labels=list(range(6)),
            neighborhood_radius=1,
            floor_distribution=np.full(6, 1.0 / 6.0, dtype=float),
            calibration_temperature=1.0,
            training_summary={},
            post_observation_model=model,
        )
        base = np.zeros((3, 3, 6), dtype=float)
        base[:, :, 0] = 0.60
        base[:, :, 1] = 0.10
        base[:, :, 2] = 0.05
        base[:, :, 3] = 0.05
        base[:, :, 4] = 0.15
        base[:, :, 5] = 0.05
        adjusted = apply_post_observation_model_to_prediction_set(
            artifact=artifact,
            round_detail=self._round_detail_with_coast(),
            predictions=[base],
            observations_by_seed=self._trade_heavy_observations(),
            floor=0.0,
        )
        coastal_port_prob = float(adjusted[0][1, 1, 2])
        inland_port_prob = float(adjusted[0][0, 0, 2])
        self.assertGreater(coastal_port_prob, float(base[1, 1, 2]))
        self.assertGreater(coastal_port_prob, inland_port_prob)
        self.assertTrue(np.allclose(adjusted[0].sum(axis=-1), 1.0))

    def test_resource_post_observation_lifts_nearby_high_wealth_non_port(self) -> None:
        round_detail = {
            "initial_states": [
                {
                    "grid": [
                        [11, 11, 11, 11, 11],
                        [11, 11, 11, 11, 11],
                        [11, 11, 11, 11, 11],
                        [11, 11, 11, 11, 11],
                        [11, 11, 11, 11, 11],
                    ],
                    "settlements": [],
                }
            ]
        }
        base = np.zeros((5, 5, 6), dtype=float)
        base[:, :, 0] = 0.70
        base[:, :, 1] = 0.10
        base[:, :, 2] = 0.05
        base[:, :, 3] = 0.04
        base[:, :, 4] = 0.08
        base[:, :, 5] = 0.03
        base /= base.sum(axis=-1, keepdims=True)
        observations = {
            0: [
                {
                    "grid": [[1, 1, 1], [1, 1, 1], [1, 1, 1]],
                    "settlements": [
                        {
                            "x": 2,
                            "y": 2,
                            "has_port": False,
                            "alive": True,
                            "owner_id": "a",
                            "population": 2.0,
                            "food": 0.32,
                            "wealth": 0.065,
                            "defense": 0.15,
                        }
                    ],
                    "viewport": {"x": 1, "y": 1, "w": 3, "h": 3},
                    "width": 5,
                    "height": 5,
                },
                {
                    "grid": [[1, 1], [1, 1]],
                    "settlements": [
                        {
                            "x": 0,
                            "y": 0,
                            "has_port": False,
                            "alive": True,
                            "owner_id": "b",
                            "population": 1.6,
                            "food": 0.70,
                            "wealth": 0.002,
                            "defense": 0.10,
                        }
                    ],
                    "viewport": {"x": 0, "y": 0, "w": 2, "h": 2},
                    "width": 5,
                    "height": 5,
                },
            ]
        }
        round_context = build_round_observation_context(round_detail=round_detail, observations_by_seed=observations)
        adjusted = apply_resource_post_observation_to_seed(
            round_detail=round_detail,
            seed_index=0,
            prediction=base,
            round_context=round_context,
            floor=0.0,
            floor_distribution=np.full(6, 1.0 / 6.0, dtype=float),
        )
        center_lift = float(adjusted[2, 2, 1] - base[2, 2, 1])
        far_lift = float(adjusted[4, 4, 1] - base[4, 4, 1])
        self.assertGreater(center_lift, far_lift)
        self.assertGreater(adjusted[2, 2, 1], adjusted[4, 4, 1])

    def test_build_prediction_variants_includes_learned_post_observation_variant(self) -> None:
        coefficients = np.zeros((len(POST_OBSERVATION_FEATURE_COLUMNS), 6), dtype=float)
        coefficients[POST_OBSERVATION_FEATURE_COLUMNS.index("obs_trade_signal"), 2] = 0.08
        coefficients[POST_OBSERVATION_FEATURE_COLUMNS.index("trade_x_coast_adjacent"), 2] = 0.15
        model = PostObservationModelArtifact(
            feature_columns=list(POST_OBSERVATION_FEATURE_COLUMNS),
            feature_mean=np.zeros(len(POST_OBSERVATION_FEATURE_COLUMNS), dtype=float),
            feature_scale=np.ones(len(POST_OBSERVATION_FEATURE_COLUMNS), dtype=float),
            coefficients=coefficients,
            intercept=np.zeros(6, dtype=float),
            ridge_alpha=1.0,
            training_summary={},
        )
        artifact = SklearnModelArtifact(
            estimator=self._DummyEstimator([0.60, 0.10, 0.05, 0.05, 0.15, 0.05]),
            model_type="random_forest_regressor",
            feature_columns=list(FEATURE_COLUMNS),
            class_labels=list(range(6)),
            neighborhood_radius=1,
            floor_distribution=np.full(6, 1.0 / 6.0, dtype=float),
            calibration_temperature=1.0,
            training_summary={},
            post_observation_model=model,
        )
        variants = build_prediction_variants(
            round_detail=self._round_detail_with_coast(),
            floor=0.0,
            observations_by_seed=self._trade_heavy_observations(),
            sklearn_artifact=artifact,
        )
        self.assertIn("sklearn_learned_post_observation", variants)
        self.assertTrue(np.allclose(variants["sklearn_learned_post_observation"][0].sum(axis=-1), 1.0))

    def test_auto_selection_can_choose_learned_post_observation_variant(self) -> None:
        selected = select_prediction_variant(
            requested_model="auto",
            strategy_evaluation_summary={
                "summary": {
                    "variants": [
                        {"variant": "sklearn_learned_post_observation", "mean_round_score": 79.4},
                        {"variant": "sklearn_observation_context", "mean_round_score": 78.0},
                    ]
                }
            },
            strategy_feedback_summary={"blocked_variants": []},
            prediction_variants={"sklearn_learned_post_observation": [], "sklearn_observation_context": []},
        )
        self.assertEqual(selected, "sklearn_learned_post_observation")

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

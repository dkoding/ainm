from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from baseline import apply_probability_floor, blend_observations, build_round_predictions, summarize_observations
from config import DEFAULT_HISTORY_CACHE_PREFIX, DEFAULT_OUTPUT_DIR, DEFAULT_PREDICTION_FLOOR
from history_cache import history_round_entries_with_analysis, load_history_index
from history_priors import (
    HistoryPriorModel,
    infer_regime_history_prior_model,
    load_history_prior_model,
    summarize_observed_round_behavior,
)
from observation_replay import load_cached_round_observations, synthesize_observations_from_analysis
from scoring import round_score, seed_score
from sklearn_model import (
    FEATURE_COLUMNS,
    SklearnModelArtifact,
    apply_post_observation_model_to_prediction_set,
    build_round_predictions_from_model,
    train_random_forest_from_history,
)


ENSEMBLE_SKLEARN_WEIGHTS = (0.25, 0.5, 0.75)
OFFLINE_SCORE_FALLBACKS = {
    "baseline_history_observation_context": ("baseline_history",),
    "baseline_history_global_post_observation": ("baseline_history_observation_context", "baseline_history"),
    "ensemble_observation_context_50": ("ensemble_sklearn_50", "sklearn_observation_context"),
    "ensemble_global_post_observation_50": (
        "ensemble_observation_context_50",
        "sklearn_global_post_observation",
        "ensemble_sklearn_50",
    ),
    "sklearn_global_post_observation": ("sklearn_observation_context", "sklearn"),
    "sklearn_learned_post_observation": ("sklearn_global_post_observation", "sklearn_observation_context", "sklearn"),
    "sklearn_resource_post_observation": ("sklearn_global_post_observation", "sklearn_observation_context", "sklearn"),
    "sklearn_rare_class_lift": ("sklearn_global_post_observation", "sklearn_observation_context", "sklearn"),
}


def build_prediction_variants(
    *,
    round_detail: dict[str, Any],
    floor: float = DEFAULT_PREDICTION_FLOOR,
    observations_by_seed: dict[int, list[dict[str, Any]]] | None = None,
    prior_strength: float = 2.0,
    history_prior_model: HistoryPriorModel | None = None,
    history_prior_strength: float = 2.0,
    sklearn_artifact: SklearnModelArtifact | None = None,
) -> dict[str, list[np.ndarray]]:
    variants: dict[str, list[np.ndarray]] = {}
    floor_distributions: dict[str, np.ndarray] = {}
    observations_by_seed = observations_by_seed or {}

    baseline_predictions = build_round_predictions(
        round_detail=round_detail,
        floor=floor,
        observations_by_seed=observations_by_seed,
        prior_strength=prior_strength,
        history_prior_model=history_prior_model,
        history_prior_strength=history_prior_strength,
    )
    baseline_name = "baseline_history" if history_prior_model is not None else "baseline_static"
    variants[baseline_name] = baseline_predictions
    if history_prior_model is not None:
        floor_distributions[baseline_name] = history_prior_model.global_class_probs

    if observations_by_seed and any(observations_by_seed.values()):
        conditioned_baseline = apply_observation_conditioning_to_prediction_set(
            round_detail=round_detail,
            predictions=baseline_predictions,
            observations_by_seed=observations_by_seed,
            floor=floor,
            floor_distribution=floor_distributions.get(baseline_name),
        )
        conditioned_baseline_name = f"{baseline_name}_observation_context"
        variants[conditioned_baseline_name] = conditioned_baseline
        if baseline_name in floor_distributions:
            floor_distributions[conditioned_baseline_name] = floor_distributions[baseline_name]
        global_baseline_name = f"{baseline_name}_global_post_observation"
        variants[global_baseline_name] = apply_global_post_observation_to_prediction_set(
            round_detail=round_detail,
            predictions=conditioned_baseline,
            observations_by_seed=observations_by_seed,
            floor=floor,
            floor_distribution=floor_distributions.get(conditioned_baseline_name),
        )
        floor_distributions[global_baseline_name] = floor_distributions.get(conditioned_baseline_name)

    if sklearn_artifact is not None:
        sklearn_predictions = build_round_predictions_from_model(
            artifact=sklearn_artifact,
            round_detail=round_detail,
            floor=floor,
        )
        sklearn_predictions = blend_predictions_with_observations(
            predictions=sklearn_predictions,
            observations_by_seed=observations_by_seed,
            prior_strength=prior_strength,
            floor=floor,
            floor_distribution=sklearn_artifact.floor_distribution,
        )
        variants["sklearn"] = sklearn_predictions
        floor_distributions["sklearn"] = sklearn_artifact.floor_distribution

        if observations_by_seed and any(observations_by_seed.values()):
            conditioned_sklearn = apply_observation_conditioning_to_prediction_set(
                round_detail=round_detail,
                predictions=sklearn_predictions,
                observations_by_seed=observations_by_seed,
                floor=floor,
                floor_distribution=sklearn_artifact.floor_distribution,
            )
            variants["sklearn_observation_context"] = conditioned_sklearn
            floor_distributions["sklearn_observation_context"] = sklearn_artifact.floor_distribution
            if sklearn_artifact.post_observation_model is not None:
                variants["sklearn_learned_post_observation"] = apply_post_observation_model_to_prediction_set(
                    artifact=sklearn_artifact,
                    round_detail=round_detail,
                    predictions=conditioned_sklearn,
                    observations_by_seed=observations_by_seed,
                    floor=floor,
                )
                floor_distributions["sklearn_learned_post_observation"] = sklearn_artifact.floor_distribution
            variants["sklearn_global_post_observation"] = apply_global_post_observation_to_prediction_set(
                round_detail=round_detail,
                predictions=conditioned_sklearn,
                observations_by_seed=observations_by_seed,
                floor=floor,
                floor_distribution=sklearn_artifact.floor_distribution,
            )
            floor_distributions["sklearn_global_post_observation"] = sklearn_artifact.floor_distribution
            variants["sklearn_resource_post_observation"] = apply_resource_post_observation_to_prediction_set(
                round_detail=round_detail,
                predictions=conditioned_sklearn,
                observations_by_seed=observations_by_seed,
                floor=floor,
                floor_distribution=sklearn_artifact.floor_distribution,
            )
            floor_distributions["sklearn_resource_post_observation"] = sklearn_artifact.floor_distribution
            variants["sklearn_rare_class_lift"] = apply_rare_class_lifting_to_prediction_set(
                round_detail=round_detail,
                predictions=variants["sklearn_global_post_observation"],
                observations_by_seed=observations_by_seed,
                floor=floor,
                floor_distribution=sklearn_artifact.floor_distribution,
            )
            floor_distributions["sklearn_rare_class_lift"] = sklearn_artifact.floor_distribution

        for sklearn_weight in ENSEMBLE_SKLEARN_WEIGHTS:
            variant_name = ensemble_variant_name(sklearn_weight)
            variants[variant_name] = blend_prediction_sets(
                primary=sklearn_predictions,
                secondary=baseline_predictions,
                primary_weight=sklearn_weight,
                floor=floor,
                floor_distribution=combine_floor_distributions(
                    floor_distributions["sklearn"],
                    floor_distributions.get(baseline_name),
                    primary_weight=sklearn_weight,
                ),
            )
        if observations_by_seed and any(observations_by_seed.values()):
            variants["ensemble_observation_context_50"] = blend_prediction_sets(
                primary=variants["sklearn_observation_context"],
                secondary=variants[conditioned_baseline_name],
                primary_weight=0.5,
                floor=floor,
                floor_distribution=combine_floor_distributions(
                    floor_distributions.get("sklearn_observation_context"),
                    floor_distributions.get(conditioned_baseline_name),
                    primary_weight=0.5,
                ),
            )
            variants["ensemble_global_post_observation_50"] = blend_prediction_sets(
                primary=variants["sklearn_global_post_observation"],
                secondary=variants[global_baseline_name],
                primary_weight=0.5,
                floor=floor,
                floor_distribution=combine_floor_distributions(
                    floor_distributions.get("sklearn_global_post_observation"),
                    floor_distributions.get(global_baseline_name),
                    primary_weight=0.5,
                ),
            )

    return variants


def blend_predictions_with_observations(
    *,
    predictions: list[np.ndarray],
    observations_by_seed: dict[int, list[dict[str, Any]]],
    prior_strength: float,
    floor: float,
    floor_distribution: Any,
) -> list[np.ndarray]:
    blended_predictions: list[np.ndarray] = []
    for seed_index, prediction in enumerate(predictions):
        observation_samples = observations_by_seed.get(seed_index, [])
        adjusted = prediction
        if observation_samples:
            adjusted = blend_observations(adjusted, observation_samples, prior_strength=prior_strength)
            adjusted = apply_probability_floor(adjusted, floor=floor, floor_distribution=floor_distribution)
        blended_predictions.append(adjusted)
    return blended_predictions


def blend_prediction_sets(
    *,
    primary: list[np.ndarray],
    secondary: list[np.ndarray],
    primary_weight: float,
    floor: float,
    floor_distribution: np.ndarray | None = None,
) -> list[np.ndarray]:
    secondary_weight = 1.0 - primary_weight
    combined: list[np.ndarray] = []
    for primary_seed, secondary_seed in zip(primary, secondary, strict=True):
        tensor = (primary_seed * primary_weight) + (secondary_seed * secondary_weight)
        tensor = np.clip(tensor, 0.0, None)
        tensor /= tensor.sum(axis=-1, keepdims=True)
        combined.append(apply_probability_floor(tensor, floor=floor, floor_distribution=floor_distribution))
    return combined


def combine_floor_distributions(
    primary: np.ndarray | None,
    secondary: np.ndarray | None,
    primary_weight: float,
) -> np.ndarray | None:
    if primary is None and secondary is None:
        return None
    if primary is None:
        return np.asarray(secondary, dtype=float)
    if secondary is None:
        return np.asarray(primary, dtype=float)
    return (np.asarray(primary, dtype=float) * primary_weight) + (np.asarray(secondary, dtype=float) * (1.0 - primary_weight))


def ensemble_variant_name(sklearn_weight: float) -> str:
    return f"ensemble_sklearn_{int(round(sklearn_weight * 100)):02d}"


def evaluate_prediction_variants(
    *,
    root: str | Path = DEFAULT_OUTPUT_DIR,
    cache_prefix: str = DEFAULT_HISTORY_CACHE_PREFIX,
    floor: float = DEFAULT_PREDICTION_FLOOR,
    prior_strength: float = 2.0,
    history_prior_strength: float = 2.0,
    neighborhood_radius: int = 1,
    n_estimators: int = 300,
    min_samples_leaf: int = 5,
    random_state: int = 0,
    simulate_queries: int = 50,
    viewport_size: int = 15,
) -> dict[str, Any]:
    root_path = Path(root)
    index = load_history_index(root=root_path, cache_prefix=cache_prefix)
    if not index:
        raise SystemExit(f"No history cache found under {root_path / cache_prefix}.")

    round_entries = history_round_entries_with_analysis(index)
    variant_round_scores: dict[str, list[float]] = {}
    rounds_report: list[dict[str, Any]] = []

    for round_entry in round_entries:
        round_id = str(round_entry["round_id"])
        round_detail_path = root_path / cache_prefix / "rounds" / round_id / "public" / "round_detail.json"
        if not round_detail_path.exists():
            continue
        round_detail = json.loads(round_detail_path.read_text())

        sklearn_artifact = train_random_forest_from_history(
            root=root_path,
            cache_prefix=cache_prefix,
            neighborhood_radius=neighborhood_radius,
            exclude_round_ids={round_id},
            n_estimators=n_estimators,
            min_samples_leaf=min_samples_leaf,
            random_state=random_state,
        )
        history_prior_model = load_history_prior_model(
            root=root_path,
            cache_prefix=cache_prefix,
            exclude_round_ids={round_id},
        )
        replay_observations, replay_mode = load_replay_observations(
            round_detail=round_detail,
            round_id=round_id,
            root=root_path,
            cache_prefix=cache_prefix,
            total_queries=simulate_queries,
            viewport_size=viewport_size,
            history_prior_model=history_prior_model,
            history_prior_strength=history_prior_strength,
            prior_strength=prior_strength,
            floor=floor,
            random_state=random_state,
        )
        regime_prior_model = history_prior_model
        if regime_prior_model is not None:
            regime_prior_model, _ = infer_regime_history_prior_model(
                history_prior_model=regime_prior_model,
                round_detail=round_detail,
                observations_by_seed=replay_observations,
            )
        variants = build_prediction_variants(
            round_detail=round_detail,
            floor=floor,
            observations_by_seed=replay_observations,
            prior_strength=prior_strength,
            history_prior_model=regime_prior_model,
            history_prior_strength=history_prior_strength,
            sklearn_artifact=sklearn_artifact,
        )

        variant_reports = []
        for variant_name, predictions in variants.items():
            seed_scores = []
            for seed_index in round_entry.get("analysis_cached_seeds", []):
                analysis_path = (
                    root_path / cache_prefix / "rounds" / round_id / "team" / "analysis" / f"seed_{int(seed_index)}.json"
                )
                if not analysis_path.exists():
                    continue
                analysis = json.loads(analysis_path.read_text())
                score = seed_score(analysis["ground_truth"], predictions[int(seed_index)])
                seed_scores.append(score)
            if not seed_scores:
                continue
            score_value = round_score(seed_scores)
            variant_round_scores.setdefault(variant_name, []).append(score_value)
            variant_reports.append(
                {
                    "variant": variant_name,
                    "round_score": score_value,
                    "seed_scores": seed_scores,
                }
            )

        rounds_report.append(
            {
                "round_id": round_id,
                "round_number": round_entry.get("round_number"),
                "replay_mode": replay_mode,
                "variant_reports": sorted(variant_reports, key=lambda item: item["round_score"], reverse=True),
            }
        )

    summary_variants = []
    for variant_name, scores in sorted(variant_round_scores.items()):
        summary_variants.append(
            {
                "variant": variant_name,
                "completed_rounds_evaluated": len(scores),
                "mean_round_score": float(sum(scores) / len(scores)),
                "round_scores": [float(score) for score in scores],
            }
        )
    best_variant = max(summary_variants, key=lambda item: item["mean_round_score"]) if summary_variants else None
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "best_variant": best_variant["variant"] if best_variant is not None else None,
            "best_variant_mean_round_score": best_variant["mean_round_score"] if best_variant is not None else None,
            "completed_rounds_evaluated": len(rounds_report),
            "strategy_signature": strategy_signature(
                history_round_ids=[str(round_entry["round_id"]) for round_entry in round_entries],
                floor=floor,
                prior_strength=prior_strength,
                history_prior_strength=history_prior_strength,
                neighborhood_radius=neighborhood_radius,
                n_estimators=n_estimators,
                min_samples_leaf=min_samples_leaf,
                random_state=random_state,
                simulate_queries=simulate_queries,
                viewport_size=viewport_size,
            ),
            "history_round_ids": [str(round_entry["round_id"]) for round_entry in round_entries],
            "history_round_numbers": [int(round_entry.get("round_number", 0) or 0) for round_entry in round_entries],
            "variants": summary_variants,
            "floor": floor,
            "prior_strength": prior_strength,
            "history_prior_strength": history_prior_strength,
            "neighborhood_radius": neighborhood_radius,
            "n_estimators": n_estimators,
            "min_samples_leaf": min_samples_leaf,
            "random_state": random_state,
            "simulate_queries": simulate_queries,
            "viewport_size": viewport_size,
        },
        "rounds": rounds_report,
    }


def strategy_signature(
    *,
    history_round_ids: list[str],
    floor: float,
    prior_strength: float,
    history_prior_strength: float,
    neighborhood_radius: int,
    n_estimators: int,
    min_samples_leaf: int,
    random_state: int,
    simulate_queries: int,
    viewport_size: int,
) -> str:
    payload = {
        "version": 4,
        "history_round_ids": list(history_round_ids),
        "floor": float(floor),
        "prior_strength": float(prior_strength),
        "history_prior_strength": float(history_prior_strength),
        "neighborhood_radius": int(neighborhood_radius),
        "n_estimators": int(n_estimators),
        "min_samples_leaf": int(min_samples_leaf),
        "random_state": int(random_state),
        "simulate_queries": int(simulate_queries),
        "viewport_size": int(viewport_size),
        "ensemble_weights": list(ENSEMBLE_SKLEARN_WEIGHTS),
        "feature_columns": list(FEATURE_COLUMNS),
        "planner": "adaptive_information_gain_v3_triggered",
        "observation_mode": "cached_or_synthetic_replay_v3",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def load_replay_observations(
    *,
    round_detail: dict[str, Any],
    round_id: str,
    root: Path,
    cache_prefix: str,
    total_queries: int,
    viewport_size: int,
    history_prior_model: HistoryPriorModel | None,
    history_prior_strength: float,
    prior_strength: float,
    floor: float,
    random_state: int,
) -> tuple[dict[int, list[dict[str, Any]]], str]:
    cached = load_cached_round_observations(root=root, round_id=round_id, max_queries=total_queries)
    if any(cached.values()):
        return cached, "real_cached_simulations"
    synthetic = synthesize_observations_from_analysis(
        round_detail=round_detail,
        round_id=round_id,
        root=root,
        cache_prefix=cache_prefix,
        total_queries=total_queries,
        viewport_size=viewport_size,
        history_prior_model=history_prior_model,
        history_prior_strength=history_prior_strength,
        prior_strength=prior_strength,
        floor=floor,
        random_state=random_state,
    )
    return synthetic, "synthetic_analysis_sampling"


def apply_observation_conditioning_to_prediction_set(
    *,
    round_detail: dict[str, Any],
    predictions: list[np.ndarray],
    observations_by_seed: dict[int, list[dict[str, Any]]],
    floor: float,
    floor_distribution: np.ndarray | None = None,
) -> list[np.ndarray]:
    if not observations_by_seed or not any(observations_by_seed.values()):
        return [prediction.copy() for prediction in predictions]
    round_context = build_round_observation_context(round_detail=round_detail, observations_by_seed=observations_by_seed)
    conditioned: list[np.ndarray] = []
    for seed_index, prediction in enumerate(predictions):
        conditioned.append(
            apply_observation_conditioning_to_seed(
                round_detail=round_detail,
                seed_index=seed_index,
                prediction=prediction,
                round_context=round_context,
                floor=floor,
                floor_distribution=floor_distribution,
            )
        )
    return conditioned


def apply_global_post_observation_to_prediction_set(
    *,
    round_detail: dict[str, Any],
    predictions: list[np.ndarray],
    observations_by_seed: dict[int, list[dict[str, Any]]],
    floor: float,
    floor_distribution: np.ndarray | None = None,
) -> list[np.ndarray]:
    if not observations_by_seed or not any(observations_by_seed.values()):
        return [prediction.copy() for prediction in predictions]
    round_context = build_round_observation_context(round_detail=round_detail, observations_by_seed=observations_by_seed)
    conditioned: list[np.ndarray] = []
    for seed_index, prediction in enumerate(predictions):
        conditioned.append(
            apply_global_post_observation_to_seed(
                round_detail=round_detail,
                seed_index=seed_index,
                prediction=prediction,
                round_context=round_context,
                floor=floor,
                floor_distribution=floor_distribution,
            )
        )
    return conditioned


def apply_rare_class_lifting_to_prediction_set(
    *,
    round_detail: dict[str, Any],
    predictions: list[np.ndarray],
    observations_by_seed: dict[int, list[dict[str, Any]]],
    floor: float,
    floor_distribution: np.ndarray | None = None,
) -> list[np.ndarray]:
    if not observations_by_seed or not any(observations_by_seed.values()):
        return [prediction.copy() for prediction in predictions]
    round_context = build_round_observation_context(round_detail=round_detail, observations_by_seed=observations_by_seed)
    conditioned: list[np.ndarray] = []
    for seed_index, prediction in enumerate(predictions):
        conditioned.append(
            apply_rare_class_lifting_to_seed(
                round_detail=round_detail,
                seed_index=seed_index,
                prediction=prediction,
                round_context=round_context,
                floor=floor,
                floor_distribution=floor_distribution,
            )
        )
    return conditioned


def apply_resource_post_observation_to_prediction_set(
    *,
    round_detail: dict[str, Any],
    predictions: list[np.ndarray],
    observations_by_seed: dict[int, list[dict[str, Any]]],
    floor: float,
    floor_distribution: np.ndarray | None = None,
) -> list[np.ndarray]:
    if not observations_by_seed or not any(observations_by_seed.values()):
        return [prediction.copy() for prediction in predictions]
    round_context = build_round_observation_context(round_detail=round_detail, observations_by_seed=observations_by_seed)
    conditioned: list[np.ndarray] = []
    for seed_index, prediction in enumerate(predictions):
        conditioned.append(
            apply_resource_post_observation_to_seed(
                round_detail=round_detail,
                seed_index=seed_index,
                prediction=prediction,
                round_context=round_context,
                floor=floor,
                floor_distribution=floor_distribution,
            )
        )
    return conditioned


def build_round_observation_context(
    *,
    round_detail: dict[str, Any],
    observations_by_seed: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    global_class_totals = np.zeros(6, dtype=float)
    global_terrain_totals: dict[int, np.ndarray] = {}
    global_coastal_totals = np.zeros(6, dtype=float)
    seed_contexts: dict[int, dict[str, Any]] = {}
    observed_summary = summarize_observed_round_behavior(observations_by_seed)

    for seed_index, state in enumerate(round_detail["initial_states"]):
        grid = np.asarray(state["grid"], dtype=int)
        coastal_mask = _build_coastal_mask(grid)
        summary = summarize_observations(
            observations_by_seed.get(seed_index, []),
            map_height=grid.shape[0],
            map_width=grid.shape[1],
        )
        seed_class_totals = np.zeros(6, dtype=float)
        seed_terrain_totals: dict[int, np.ndarray] = {}
        seed_coastal_totals = np.zeros(6, dtype=float)
        observed_cells: list[dict[str, Any]] = []
        for (y, x), counts in summary["cell_class_counts"].items():
            probs = counts / counts.sum()
            terrain_code = int(grid[y, x])
            is_coastal = bool(coastal_mask[y, x])
            observed_cells.append(
                {
                    "x": int(x),
                    "y": int(y),
                    "terrain_code": terrain_code,
                    "is_coastal": is_coastal,
                    "probs": probs,
                }
            )
            seed_class_totals += probs
            seed_terrain_totals.setdefault(terrain_code, np.zeros(6, dtype=float))
            seed_terrain_totals[terrain_code] += probs
            global_class_totals += probs
            global_terrain_totals.setdefault(terrain_code, np.zeros(6, dtype=float))
            global_terrain_totals[terrain_code] += probs
            if is_coastal:
                seed_coastal_totals += probs
                global_coastal_totals += probs
        seed_contexts[seed_index] = {
            "observed_cells": observed_cells,
            "observed_settlements": _summarize_observed_settlements(
                samples=observations_by_seed.get(seed_index, []),
                grid=grid,
                coastal_mask=coastal_mask,
            ),
            "class_probs": _normalize_prob_vector(seed_class_totals),
            "terrain_probs": {code: _normalize_prob_vector(totals) for code, totals in seed_terrain_totals.items()},
            "coastal_probs": _normalize_prob_vector(seed_coastal_totals),
            "coverage_fraction": float(len(observed_cells) / max(grid.size, 1)),
        }

    return {
        "global_class_probs": _normalize_prob_vector(global_class_totals),
        "global_terrain_probs": {code: _normalize_prob_vector(totals) for code, totals in global_terrain_totals.items()},
        "global_coastal_probs": _normalize_prob_vector(global_coastal_totals),
        "seed_contexts": seed_contexts,
        "observed_summary": observed_summary,
        "round_axes": infer_round_observation_axes(observed_summary),
    }


def apply_observation_conditioning_to_seed(
    *,
    round_detail: dict[str, Any],
    seed_index: int,
    prediction: np.ndarray,
    round_context: dict[str, Any],
    floor: float,
    floor_distribution: np.ndarray | None,
) -> np.ndarray:
    state = round_detail["initial_states"][seed_index]
    grid = np.asarray(state["grid"], dtype=int)
    coastal_mask = _build_coastal_mask(grid)
    seed_context = round_context["seed_contexts"].get(seed_index, {})
    observed_cells = list(seed_context.get("observed_cells", []))
    adjusted = prediction.astype(float, copy=True)
    for y in range(grid.shape[0]):
        for x in range(grid.shape[1]):
            base = adjusted[y, x]
            terrain_code = int(grid[y, x])
            pieces = [(base, 1.0)]
            seed_terrain_probs = seed_context.get("terrain_probs", {}).get(terrain_code)
            if seed_terrain_probs is not None:
                pieces.append((seed_terrain_probs, 0.35))
            global_terrain_probs = round_context.get("global_terrain_probs", {}).get(terrain_code)
            if global_terrain_probs is not None:
                pieces.append((global_terrain_probs, 0.30))
            if bool(coastal_mask[y, x]):
                coastal_probs = seed_context.get("coastal_probs")
                if coastal_probs is not None:
                    pieces.append((coastal_probs, 0.18))
                global_coastal_probs = round_context.get("global_coastal_probs")
                if global_coastal_probs is not None:
                    pieces.append((global_coastal_probs, 0.12))
            if observed_cells:
                spatial_probs, spatial_weight = _spatial_observation_prior(
                    x=x,
                    y=y,
                    terrain_code=terrain_code,
                    is_coastal=bool(coastal_mask[y, x]),
                    observed_cells=observed_cells,
                )
                if spatial_probs is not None and spatial_weight > 0:
                    pieces.append((spatial_probs, spatial_weight))
            combined = np.zeros(6, dtype=float)
            total_weight = 0.0
            for probs, weight in pieces:
                combined += np.asarray(probs, dtype=float) * float(weight)
                total_weight += float(weight)
            if total_weight > 0:
                adjusted[y, x] = combined / total_weight
    return apply_probability_floor(adjusted, floor=floor, floor_distribution=floor_distribution)


def apply_global_post_observation_to_seed(
    *,
    round_detail: dict[str, Any],
    seed_index: int,
    prediction: np.ndarray,
    round_context: dict[str, Any],
    floor: float,
    floor_distribution: np.ndarray | None,
) -> np.ndarray:
    state = round_detail["initial_states"][seed_index]
    grid = np.asarray(state["grid"], dtype=int)
    coastal_mask = _build_coastal_mask(grid)
    settlement_distance = _build_settlement_distance_map(state=state, width=grid.shape[1], height=grid.shape[0])
    axes = round_context.get("round_axes", {})
    coverage_fraction = float(np.mean([float(item.get("coverage_fraction", 0.0)) for item in round_context.get("seed_contexts", {}).values()])) if round_context.get("seed_contexts") else 0.0
    strength = float(np.clip(0.15 + 0.80 * coverage_fraction, 0.0, 0.70))
    adjusted = prediction.astype(float, copy=True)
    for y in range(grid.shape[0]):
        for x in range(grid.shape[1]):
            terrain_code = int(grid[y, x])
            if terrain_code == 10 or terrain_code == 5:
                continue
            base = adjusted[y, x]
            near_settlement = _proximity_signal(settlement_distance[y, x], radius=5.0)
            coastal_signal = 1.0 if bool(coastal_mask[y, x]) else 0.0
            frontier_signal = _local_frontier_score(grid=grid, x=x, y=y)
            lifted = np.array(base, copy=True)
            development_gain = float(axes.get("development", 0.0)) * (0.25 + 0.65 * near_settlement + 0.25 * frontier_signal)
            trade_gain = float(axes.get("trade", 0.0)) * (0.15 + 0.70 * coastal_signal + 0.35 * near_settlement)
            conflict_gain = float(axes.get("conflict", 0.0)) * (0.20 + 0.60 * frontier_signal + 0.35 * near_settlement)
            harshness_gain = float(axes.get("harshness", 0.0)) * (0.20 + 0.45 * near_settlement + 0.20 * (1.0 - coastal_signal))
            lifted[1] *= 1.0 + 0.55 * development_gain
            lifted[2] *= 1.0 + 0.90 * trade_gain
            lifted[3] *= 1.0 + 0.75 * conflict_gain + 0.55 * harshness_gain
            lifted[4] *= 1.0 + 0.25 * harshness_gain - 0.10 * development_gain
            lifted[0] *= max(0.45, 1.0 - 0.22 * development_gain - 0.18 * trade_gain - 0.18 * conflict_gain)
            lifted = np.clip(lifted, 1e-12, None)
            lifted /= lifted.sum()
            adjusted[y, x] = ((1.0 - strength) * base) + (strength * lifted)
    return apply_probability_floor(adjusted, floor=floor, floor_distribution=floor_distribution)


def apply_rare_class_lifting_to_seed(
    *,
    round_detail: dict[str, Any],
    seed_index: int,
    prediction: np.ndarray,
    round_context: dict[str, Any],
    floor: float,
    floor_distribution: np.ndarray | None,
) -> np.ndarray:
    state = round_detail["initial_states"][seed_index]
    grid = np.asarray(state["grid"], dtype=int)
    coastal_mask = _build_coastal_mask(grid)
    settlement_distance = _build_settlement_distance_map(state=state, width=grid.shape[1], height=grid.shape[0])
    axes = round_context.get("round_axes", {})
    coverage_fraction = float(np.mean([float(item.get("coverage_fraction", 0.0)) for item in round_context.get("seed_contexts", {}).values()])) if round_context.get("seed_contexts") else 0.0
    strength = float(np.clip(0.20 + 0.90 * coverage_fraction, 0.0, 0.75))
    adjusted = prediction.astype(float, copy=True)
    for y in range(grid.shape[0]):
        for x in range(grid.shape[1]):
            terrain_code = int(grid[y, x])
            if terrain_code in {10, 5}:
                continue
            base = adjusted[y, x]
            near_settlement = _proximity_signal(settlement_distance[y, x], radius=4.0)
            coastal_signal = 1.0 if bool(coastal_mask[y, x]) else 0.0
            frontier_signal = _local_frontier_score(grid=grid, x=x, y=y)
            if (near_settlement + coastal_signal + frontier_signal) <= 0.1:
                continue
            lifted = np.array(base, copy=True)
            settlement_boost = float(axes.get("development", 0.0)) * (0.40 + 0.80 * near_settlement + 0.30 * frontier_signal)
            port_boost = float(axes.get("trade", 0.0)) * (0.35 + 1.20 * coastal_signal + 0.45 * near_settlement)
            ruin_boost = (float(axes.get("conflict", 0.0)) + float(axes.get("harshness", 0.0))) * (
                0.25 + 0.80 * frontier_signal + 0.45 * near_settlement
            )
            lifted[1] *= 1.0 + 0.85 * settlement_boost
            lifted[2] *= 1.0 + 1.35 * port_boost
            lifted[3] *= 1.0 + 1.10 * ruin_boost
            lifted[0] *= max(0.35, 1.0 - 0.25 * settlement_boost - 0.25 * port_boost - 0.22 * ruin_boost)
            lifted = np.clip(lifted, 1e-12, None)
            lifted /= lifted.sum()
            adjusted[y, x] = ((1.0 - strength) * base) + (strength * lifted)
    return apply_probability_floor(adjusted, floor=floor, floor_distribution=floor_distribution)


def apply_resource_post_observation_to_seed(
    *,
    round_detail: dict[str, Any],
    seed_index: int,
    prediction: np.ndarray,
    round_context: dict[str, Any],
    floor: float,
    floor_distribution: np.ndarray | None,
) -> np.ndarray:
    state = round_detail["initial_states"][seed_index]
    grid = np.asarray(state["grid"], dtype=int)
    coastal_mask = _build_coastal_mask(grid)
    seed_context = round_context.get("seed_contexts", {}).get(seed_index, {})
    observed_settlements = list(seed_context.get("observed_settlements", []))
    if not observed_settlements:
        return apply_probability_floor(prediction, floor=floor, floor_distribution=floor_distribution)

    observed_summary = round_context.get("observed_summary", {})
    mean_food = float(observed_summary.get("mean_food", 0.0))
    mean_wealth = float(observed_summary.get("mean_wealth", 0.0))
    coverage_fraction = (
        float(np.mean([float(item.get("coverage_fraction", 0.0)) for item in round_context.get("seed_contexts", {}).values()]))
        if round_context.get("seed_contexts")
        else 0.0
    )
    strength = float(np.clip(0.10 + 0.60 * coverage_fraction, 0.0, 0.32))

    adjusted = prediction.astype(float, copy=True)
    for y in range(grid.shape[0]):
        for x in range(grid.shape[1]):
            terrain_code = int(grid[y, x])
            if terrain_code in {10, 5}:
                continue
            coastal_signal = 1.0 if bool(coastal_mask[y, x]) else 0.0
            frontier_signal = _local_frontier_score(grid=grid, x=x, y=y)
            settlement_pull = 0.0
            port_pull = 0.0
            ruin_pull = 0.0
            stability_pull = 0.0

            for observed in observed_settlements:
                distance = abs(int(observed["x"]) - x) + abs(int(observed["y"]) - y)
                proximity = _proximity_signal(distance, radius=3.25)
                if proximity <= 0.05:
                    continue

                wealth_signal = float(
                    np.clip(
                        (float(observed.get("wealth", 0.0)) - max(0.75 * mean_wealth, 0.006))
                        / max(0.018, 1.4 * mean_wealth),
                        0.0,
                        1.6,
                    )
                )
                food_signal = float(
                    np.clip(
                        (float(observed.get("food", 0.0)) - max(mean_food, 0.45)) / 0.28,
                        0.0,
                        1.5,
                    )
                )
                low_food_signal = float(
                    np.clip((max(mean_food, 0.45) - float(observed.get("food", 0.0))) / 0.24, 0.0, 1.5)
                )
                pressure_signal = float(
                    np.clip(
                        max(
                            -float(observed.get("population_delta_first_last", 0.0)) / 0.22,
                            0.55 * low_food_signal
                            + 0.30 * float(observed.get("defense", 0.0))
                            + 0.20 * max(-float(observed.get("food_delta_first_last", 0.0)), 0.0) / 0.12,
                        ),
                        0.0,
                        1.8,
                    )
                )

                if bool(observed.get("has_port")):
                    port_pull += proximity * (0.35 + 0.55 * wealth_signal) * (0.70 + 0.30 * coastal_signal)
                else:
                    settlement_pull += proximity * wealth_signal * (0.60 + 0.20 * frontier_signal)
                    port_pull += proximity * wealth_signal * coastal_signal * 0.18
                    stability_pull += proximity * food_signal * (0.55 + 0.20 * (1.0 - coastal_signal))

                if int(observed.get("observation_count", 1)) > 1 or pressure_signal > 0.35:
                    ruin_pull += proximity * pressure_signal * (0.35 + 0.45 * frontier_signal)
                    settlement_pull -= proximity * 0.12 * pressure_signal

            settlement_pull = float(np.clip(settlement_pull, -0.35, 1.8))
            port_pull = float(np.clip(port_pull, 0.0, 1.4))
            ruin_pull = float(np.clip(ruin_pull, 0.0, 1.8))
            stability_pull = float(np.clip(stability_pull, 0.0, 1.3))

            base = adjusted[y, x]
            lifted = np.array(base, copy=True)
            lifted[1] *= 1.0 + strength * 0.75 * settlement_pull
            lifted[2] *= 1.0 + strength * 0.95 * port_pull
            lifted[3] *= 1.0 + strength * 0.85 * ruin_pull
            lifted[4] *= 1.0 + strength * 0.18 * stability_pull
            lifted[0] *= max(
                0.35,
                1.0
                + strength * 0.22 * stability_pull
                - strength * 0.20 * max(settlement_pull, 0.0)
                - strength * 0.24 * port_pull
                - strength * 0.18 * ruin_pull,
            )
            lifted = np.clip(lifted, 1e-12, None)
            lifted /= lifted.sum()
            adjusted[y, x] = lifted
    return apply_probability_floor(adjusted, floor=floor, floor_distribution=floor_distribution)


def infer_round_observation_axes(observed_summary: dict[str, Any]) -> dict[str, float]:
    return {
        "development": float(np.clip(observed_summary.get("development_signal", 0.0), 0.0, 1.0)),
        "conflict": float(np.clip(observed_summary.get("conflict_signal", 0.0), 0.0, 1.0)),
        "trade": float(np.clip(max(observed_summary.get("port_signal", 0.0), observed_summary.get("trade_signal", 0.0)), 0.0, 1.0)),
        "harshness": float(np.clip(observed_summary.get("harshness_signal", 0.0), 0.0, 1.0)),
    }


def score_prediction_variants_for_live_round(
    *,
    round_detail: dict[str, Any],
    prediction_variants: dict[str, list[np.ndarray]],
    observations_by_seed: dict[int, list[dict[str, Any]]],
    strategy_evaluation_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not observations_by_seed or not any(observations_by_seed.values()):
        return None
    round_context = build_round_observation_context(round_detail=round_detail, observations_by_seed=observations_by_seed)
    offline_scores = {
        str(item.get("variant")): float(item.get("mean_round_score", 0.0))
        for item in (strategy_evaluation_summary or {}).get("summary", {}).get("variants", [])
    }
    variant_reports = []
    for variant_name, predictions in prediction_variants.items():
        observation_match = _variant_observation_match_score(
            predictions=predictions,
            round_detail=round_detail,
            observations_by_seed=observations_by_seed,
        )
        activity_gap = _variant_activity_gap(predictions=predictions, round_context=round_context)
        offline_mean, offline_score_source = _resolve_offline_variant_score(
            variant_name=variant_name,
            offline_scores=offline_scores,
        )
        live_score = float(observation_match - (0.25 * activity_gap) + (0.002 * offline_mean))
        variant_reports.append(
            {
                "variant": variant_name,
                "live_score": live_score,
                "observation_match": observation_match,
                "activity_gap": activity_gap,
                "offline_mean_round_score": offline_mean,
                "offline_score_source": offline_score_source,
            }
        )
    variant_reports = sorted(variant_reports, key=lambda item: (item["live_score"], item["offline_mean_round_score"]), reverse=True)
    return {
        "round_axes": round_context.get("round_axes", {}),
        "observed_summary": round_context.get("observed_summary", {}),
        "variants": variant_reports,
        "best_variant": variant_reports[0]["variant"] if variant_reports else None,
    }


def _resolve_offline_variant_score(
    *,
    variant_name: str,
    offline_scores: dict[str, float],
) -> tuple[float, str]:
    exact = offline_scores.get(variant_name)
    if exact is not None:
        return float(exact), "exact"

    for fallback_name in OFFLINE_SCORE_FALLBACKS.get(variant_name, ()):
        fallback_score = offline_scores.get(fallback_name)
        if fallback_score is not None:
            return float(fallback_score), f"fallback:{fallback_name}"

    family_candidates: list[str] = []
    if variant_name.startswith("sklearn_") or variant_name == "sklearn":
        family_candidates = [
            name
            for name in ("sklearn_observation_context", "sklearn_global_post_observation", "sklearn")
            if name in offline_scores
        ]
    elif variant_name.startswith("baseline_history"):
        family_candidates = [
            name
            for name in ("baseline_history_observation_context", "baseline_history_global_post_observation", "baseline_history")
            if name in offline_scores
        ]
    elif variant_name.startswith("ensemble_"):
        family_candidates = [
            name
            for name in (
                "ensemble_observation_context_50",
                "ensemble_global_post_observation_50",
                "ensemble_sklearn_75",
                "ensemble_sklearn_50",
                "ensemble_sklearn_25",
            )
            if name in offline_scores
        ]
    if family_candidates:
        scores = np.asarray([float(offline_scores[name]) for name in family_candidates], dtype=float)
        return float(scores.mean()), "fallback:family_mean"

    if offline_scores:
        scores = np.asarray(list(offline_scores.values()), dtype=float)
        return float(np.median(scores)), "fallback:median"
    return 0.0, "missing"


def _spatial_observation_prior(
    *,
    x: int,
    y: int,
    terrain_code: int,
    is_coastal: bool,
    observed_cells: list[dict[str, Any]],
) -> tuple[np.ndarray | None, float]:
    weighted = np.zeros(6, dtype=float)
    total_weight = 0.0
    for item in observed_cells:
        distance = abs(int(item["x"]) - x) + abs(int(item["y"]) - y)
        base_weight = float(np.exp(-distance / 6.0))
        if int(item["terrain_code"]) == terrain_code:
            base_weight *= 1.35
        if bool(item["is_coastal"]) == is_coastal:
            base_weight *= 1.15
        if distance == 0:
            base_weight *= 1.5
        if base_weight <= 1e-4:
            continue
        weighted += np.asarray(item["probs"], dtype=float) * base_weight
        total_weight += base_weight
    if total_weight <= 0:
        return None, 0.0
    normalized = weighted / total_weight
    return normalized, float(min(0.45, total_weight / 6.0))


def _normalize_prob_vector(values: np.ndarray) -> np.ndarray | None:
    total = float(np.asarray(values, dtype=float).sum())
    if total <= 0:
        return None
    return np.asarray(values, dtype=float) / total


def _summarize_observed_settlements(
    *,
    samples: list[dict[str, Any]],
    grid: np.ndarray,
    coastal_mask: np.ndarray,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for query_index, sample in enumerate(samples):
        for settlement in sample.get("settlements", []):
            x = int(settlement["x"])
            y = int(settlement["y"])
            grouped.setdefault((x, y), []).append(
                {
                    "x": x,
                    "y": y,
                    "query_index": int(query_index),
                    "has_port": bool(settlement.get("has_port")),
                    "alive": bool(settlement.get("alive", True)),
                    "owner_id": settlement.get("owner_id"),
                    "population": float(settlement.get("population", 0.0) or 0.0),
                    "food": float(settlement.get("food", 0.0) or 0.0),
                    "wealth": float(settlement.get("wealth", 0.0) or 0.0),
                    "defense": float(settlement.get("defense", 0.0) or 0.0),
                }
            )

    summarized: list[dict[str, Any]] = []
    for (x, y), records in grouped.items():
        ordered = sorted(records, key=lambda item: int(item["query_index"]))
        representative = dict(ordered[-1])
        representative["observation_count"] = len(ordered)
        representative["coast_adjacent"] = bool(coastal_mask[y, x])
        representative["frontier_score"] = _local_frontier_score(grid=grid, x=x, y=y)
        for key in ("population", "food", "wealth", "defense"):
            values = np.asarray([float(item[key]) for item in ordered], dtype=float)
            representative[key] = float(values.mean())
            representative[f"{key}_delta_first_last"] = float(values[-1] - values[0]) if len(values) > 1 else 0.0
        summarized.append(representative)
    return summarized


def _build_coastal_mask(grid: np.ndarray) -> np.ndarray:
    mask = np.zeros(grid.shape, dtype=bool)
    for y in range(grid.shape[0]):
        for x in range(grid.shape[1]):
            center_is_ocean = int(grid[y, x]) == 10
            for nx, ny in _neighbors(x=x, y=y, width=grid.shape[1], height=grid.shape[0]):
                if (int(grid[ny, nx]) == 10) != center_is_ocean:
                    mask[y, x] = True
                    break
    return mask


def _neighbors(x: int, y: int, width: int, height: int) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx = x + dx
        ny = y + dy
        if 0 <= nx < width and 0 <= ny < height:
            result.append((nx, ny))
    return result


def _build_settlement_distance_map(*, state: dict[str, Any], width: int, height: int) -> np.ndarray:
    settlements = [(int(item["x"]), int(item["y"])) for item in state.get("settlements", [])]
    if not settlements:
        return np.full((height, width), float(width + height), dtype=float)
    distances = np.zeros((height, width), dtype=float)
    for y in range(height):
        for x in range(width):
            distances[y, x] = min(abs(sx - x) + abs(sy - y) for sx, sy in settlements)
    return distances


def _proximity_signal(distance: float, radius: float) -> float:
    return float(np.exp(-max(float(distance), 0.0) / max(float(radius), 1e-6)))


def _local_frontier_score(*, grid: np.ndarray, x: int, y: int) -> float:
    center = int(grid[y, x])
    differing = 0
    total = 0
    for nx, ny in _neighbors(x=x, y=y, width=grid.shape[1], height=grid.shape[0]):
        total += 1
        if int(grid[ny, nx]) != center:
            differing += 1
    return float(differing / total) if total > 0 else 0.0


def _variant_observation_match_score(
    *,
    predictions: list[np.ndarray],
    round_detail: dict[str, Any],
    observations_by_seed: dict[int, list[dict[str, Any]]],
) -> float:
    weighted_total = 0.0
    total_weight = 0.0
    for seed_index, seed_predictions in enumerate(predictions):
        state = round_detail["initial_states"][seed_index]
        summary = summarize_observations(
            observations_by_seed.get(seed_index, []),
            map_height=len(state["grid"]),
            map_width=len(state["grid"][0]),
        )
        for (y, x), counts in summary["cell_class_counts"].items():
            empirical = np.asarray(counts, dtype=float)
            empirical /= empirical.sum()
            predicted = np.asarray(seed_predictions[int(y), int(x)], dtype=float)
            entropy = float(-(empirical * np.log(np.clip(empirical, 1e-12, 1.0))).sum())
            weight = float(counts.sum()) * (1.0 + entropy)
            weighted_total += float(np.dot(empirical, predicted)) * weight
            total_weight += weight
    if total_weight <= 0:
        return 0.0
    return float(weighted_total / total_weight)


def _variant_activity_gap(
    *,
    predictions: list[np.ndarray],
    round_context: dict[str, Any],
) -> float:
    observed_summary = round_context.get("observed_summary", {})
    development_signal = float(observed_summary.get("development_signal", 0.0))
    conflict_signal = float(observed_summary.get("conflict_signal", 0.0))
    trade_signal = float(max(observed_summary.get("trade_signal", 0.0), observed_summary.get("port_signal", 0.0)))
    harshness_signal = float(observed_summary.get("harshness_signal", 0.0))
    stacked = np.stack(predictions, axis=0)
    mean_probs = stacked.mean(axis=(0, 1, 2))
    predicted_development = float(mean_probs[1] + mean_probs[2])
    predicted_conflict = float(mean_probs[3])
    predicted_trade = float(mean_probs[2])
    predicted_harshness = float(mean_probs[3] + (0.25 * mean_probs[4]))
    return float(
        abs(predicted_development - development_signal)
        + abs(predicted_conflict - conflict_signal)
        + abs(predicted_trade - trade_signal)
        + abs(predicted_harshness - harshness_signal)
    )

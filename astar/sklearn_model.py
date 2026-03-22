from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from baseline import CLASS_COUNT, apply_probability_floor, blend_observations, summarize_observations
from config import DEFAULT_HISTORY_CACHE_PREFIX, DEFAULT_OUTPUT_DIR, DEFAULT_PREDICTION_FLOOR
from feature_engineering import FEATURE_COLUMNS, feature_matrix_from_records, iter_state_feature_records
from history_cache import load_history_index
from history_dataset import iter_history_dataset_records
from history_priors import summarize_observed_round_behavior
from observation_replay import synthesize_observations_from_analysis


POST_OBSERVATION_SUMMARY_COLUMNS = [
    "obs_class_prob_0",
    "obs_class_prob_1",
    "obs_class_prob_2",
    "obs_class_prob_3",
    "obs_class_prob_4",
    "obs_class_prob_5",
    "obs_development_signal",
    "obs_conflict_signal",
    "obs_trade_signal",
    "obs_harshness_signal",
    "obs_port_signal",
    "obs_forest_signal",
    "obs_alive_ratio",
    "obs_owner_diversity",
    "obs_mean_population",
    "obs_mean_food",
    "obs_mean_wealth",
    "obs_mean_defense",
    "obs_settlement_density",
    "obs_coverage_fraction",
]
POST_OBSERVATION_INTERACTION_COLUMNS = [
    "base_prob_0",
    "base_prob_1",
    "base_prob_2",
    "base_prob_3",
    "base_prob_4",
    "base_prob_5",
    "base_dynamic_mass",
    "settlement_proximity",
    "port_proximity",
    "frontier_signal",
    "development_x_settlement_proximity",
    "trade_x_coast_adjacent",
    "trade_x_port_proximity",
    "conflict_x_frontier",
    "harshness_x_settlement_proximity",
    "dynamic_signal_x_base_dynamic",
]
POST_OBSERVATION_FEATURE_COLUMNS = list(FEATURE_COLUMNS) + POST_OBSERVATION_SUMMARY_COLUMNS + POST_OBSERVATION_INTERACTION_COLUMNS


@dataclass
class PostObservationModelArtifact:
    feature_columns: list[str]
    feature_mean: np.ndarray
    feature_scale: np.ndarray
    coefficients: np.ndarray
    intercept: np.ndarray
    ridge_alpha: float
    training_summary: dict[str, Any]

    def to_metadata(self) -> dict[str, Any]:
        metadata = dict(self.training_summary)
        metadata.update(
            {
                "feature_columns": list(self.feature_columns),
                "ridge_alpha": float(self.ridge_alpha),
                "feature_count": len(self.feature_columns),
                "coefficient_l2_norm": float(np.linalg.norm(self.coefficients)),
            }
        )
        return metadata


@dataclass
class SklearnModelArtifact:
    estimator: Any
    model_type: str
    feature_columns: list[str]
    class_labels: list[int]
    neighborhood_radius: int
    floor_distribution: np.ndarray
    calibration_temperature: float
    training_summary: dict[str, Any]
    post_observation_model: PostObservationModelArtifact | None = None

    def to_metadata(self) -> dict[str, Any]:
        metadata = dict(self.training_summary)
        metadata.update(
            {
                "model_type": self.model_type,
                "feature_columns": list(self.feature_columns),
                "class_labels": list(self.class_labels),
                "neighborhood_radius": int(self.neighborhood_radius),
                "floor_distribution": self.floor_distribution.tolist(),
                "calibration_temperature": float(self.calibration_temperature),
            }
        )
        if self.post_observation_model is not None:
            metadata["post_observation_model"] = self.post_observation_model.to_metadata()
        return metadata


def train_random_forest_from_history(
    root: str | Path = DEFAULT_OUTPUT_DIR,
    cache_prefix: str = DEFAULT_HISTORY_CACHE_PREFIX,
    neighborhood_radius: int = 1,
    include_round_ids: set[str] | None = None,
    exclude_round_ids: set[str] | None = None,
    n_estimators: int = 300,
    min_samples_leaf: int = 5,
    random_state: int = 0,
) -> SklearnModelArtifact:
    RandomForestRegressor = _load_random_forest_regressor()
    records = load_training_records(
        root=root,
        cache_prefix=cache_prefix,
        neighborhood_radius=neighborhood_radius,
        include_round_ids=include_round_ids,
        exclude_round_ids=exclude_round_ids,
    )
    if not records:
        raise SystemExit("No cached history records available for sklearn training.")

    X = feature_matrix_from_records(records, feature_columns=FEATURE_COLUMNS)
    y = np.asarray([record["target_probs"] for record in records], dtype=np.float32)
    target_argmax = np.asarray([int(record["target_argmax"]) for record in records], dtype=int)
    class_counts = np.bincount(target_argmax, minlength=CLASS_COUNT)
    sample_weights = compute_entropy_sample_weights(records)

    calibration_temperature, calibration_summary = fit_temperature_calibration_from_heldout_rounds(
        records=records,
        neighborhood_radius=neighborhood_radius,
        n_estimators=n_estimators,
        min_samples_leaf=min_samples_leaf,
        random_state=random_state,
    )
    estimator = train_regressor_estimator(
        RandomForestRegressor=RandomForestRegressor,
        X=X,
        y=y,
        sample_weights=sample_weights,
        n_estimators=n_estimators,
        min_samples_leaf=min_samples_leaf,
        random_state=random_state,
    )

    target_mass = np.zeros(CLASS_COUNT, dtype=float)
    for record in records:
        target_mass += np.asarray(record["target_probs"], dtype=float)
    floor_distribution = target_mass / target_mass.sum() if float(target_mass.sum()) > 0 else np.full(CLASS_COUNT, 1.0 / CLASS_COUNT)

    rounds_used = sorted({str(record["round_id"]) for record in records})
    round_numbers = sorted({int(record["round_number"]) for record in records})
    dynamic_cell_share = float(np.mean([float(record.get("dynamic_cell", 0)) for record in records])) if records else 0.0
    training_summary = {
        "records_used": len(records),
        "rounds_used": len(rounds_used),
        "round_ids": rounds_used,
        "round_numbers": round_numbers,
        "class_counts": {str(index): int(count) for index, count in enumerate(class_counts)},
        "target_mass": {str(index): float(value) for index, value in enumerate(target_mass)},
        "n_estimators": int(n_estimators),
        "min_samples_leaf": int(min_samples_leaf),
        "random_state": int(random_state),
        "calibration_temperature": float(calibration_temperature),
        "calibration_summary": calibration_summary,
        "dynamic_cell_share": dynamic_cell_share,
        "sample_weight_summary": {
            "min": float(sample_weights.min()) if sample_weights.size else 0.0,
            "max": float(sample_weights.max()) if sample_weights.size else 0.0,
            "mean": float(sample_weights.mean()) if sample_weights.size else 0.0,
        },
    }

    base_artifact = SklearnModelArtifact(
        estimator=estimator,
        model_type="random_forest_regressor",
        feature_columns=list(FEATURE_COLUMNS),
        class_labels=list(range(CLASS_COUNT)),
        neighborhood_radius=neighborhood_radius,
        floor_distribution=floor_distribution,
        calibration_temperature=float(calibration_temperature),
        training_summary=training_summary,
    )
    post_observation_model = train_post_observation_residual_model(
        base_artifact=base_artifact,
        root=root,
        cache_prefix=cache_prefix,
        include_round_ids=include_round_ids,
        exclude_round_ids=exclude_round_ids,
        random_state=random_state,
    )
    if post_observation_model is not None:
        training_summary["post_observation_model"] = post_observation_model.to_metadata()

    return SklearnModelArtifact(
        estimator=estimator,
        model_type="random_forest_regressor",
        feature_columns=list(FEATURE_COLUMNS),
        class_labels=list(range(CLASS_COUNT)),
        neighborhood_radius=neighborhood_radius,
        floor_distribution=floor_distribution,
        calibration_temperature=float(calibration_temperature),
        training_summary=training_summary,
        post_observation_model=post_observation_model,
    )


def load_training_records(
    root: str | Path = DEFAULT_OUTPUT_DIR,
    cache_prefix: str = DEFAULT_HISTORY_CACHE_PREFIX,
    neighborhood_radius: int = 1,
    include_round_ids: set[str] | None = None,
    exclude_round_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for record in iter_history_dataset_records(root=root, cache_prefix=cache_prefix, neighborhood_radius=neighborhood_radius):
        round_id = str(record["round_id"])
        if include_round_ids is not None and round_id not in include_round_ids:
            continue
        if exclude_round_ids is not None and round_id in exclude_round_ids:
            continue
        records.append(record)
    return records


def build_round_predictions_from_model(
    artifact: SklearnModelArtifact,
    round_detail: dict[str, Any],
    floor: float = DEFAULT_PREDICTION_FLOOR,
) -> list[np.ndarray]:
    predictions: list[np.ndarray] = []
    for seed_index, state in enumerate(round_detail["initial_states"]):
        predictions.append(
            predict_seed_tensor(
                artifact=artifact,
                state=state,
                seed_index=seed_index,
                floor=floor,
            )
        )
    return predictions


def predict_seed_tensor(
    artifact: SklearnModelArtifact,
    state: dict[str, Any],
    seed_index: int,
    floor: float = DEFAULT_PREDICTION_FLOOR,
) -> np.ndarray:
    records = list(
        iter_state_feature_records(
            state=state,
            seed_index=seed_index,
            neighborhood_radius=artifact.neighborhood_radius,
        )
    )
    if not records:
        raise ValueError(f"State for seed {seed_index} produced no feature rows.")

    grid = np.asarray(state["grid"], dtype=int)
    height, width = grid.shape
    X = feature_matrix_from_records(records, feature_columns=artifact.feature_columns)
    if artifact.model_type == "random_forest_regressor":
        full_probs = np.asarray(artifact.estimator.predict(X), dtype=float)
    else:
        raw_probs = artifact.estimator.predict_proba(X)
        full_probs = np.zeros((len(records), CLASS_COUNT), dtype=float)
        for column_index, class_label in enumerate(artifact.class_labels):
            full_probs[:, int(class_label)] = raw_probs[:, column_index]
    full_probs = np.clip(full_probs, 0.0, None)
    row_sums = full_probs.sum(axis=-1, keepdims=True)
    zero_rows = row_sums.squeeze(-1) <= 0
    if np.any(zero_rows):
        full_probs[zero_rows] = artifact.floor_distribution
        row_sums = full_probs.sum(axis=-1, keepdims=True)
    full_probs /= row_sums
    full_probs = apply_temperature_calibration(full_probs, artifact.calibration_temperature)
    tensor = full_probs.reshape(height, width, CLASS_COUNT)
    return apply_probability_floor(tensor, floor=floor, floor_distribution=artifact.floor_distribution)


def apply_post_observation_model_to_prediction_set(
    *,
    artifact: SklearnModelArtifact,
    round_detail: dict[str, Any],
    predictions: list[np.ndarray],
    observations_by_seed: dict[int, list[dict[str, Any]]],
    floor: float,
) -> list[np.ndarray]:
    model = artifact.post_observation_model
    if model is None or not observations_by_seed or not any(observations_by_seed.values()):
        return [prediction.copy() for prediction in predictions]

    total_round_cells = max(_round_total_cell_count(round_detail), 1)
    observed_summary = summarize_observed_round_behavior(observations_by_seed)
    coverage_fraction = float(observed_summary.get("observed_cells", 0.0) / float(total_round_cells))
    adjusted_predictions: list[np.ndarray] = []
    for seed_index, state in enumerate(round_detail["initial_states"]):
        base_prediction = np.asarray(predictions[seed_index], dtype=float)
        feature_records = list(
            iter_state_feature_records(
                state=state,
                seed_index=seed_index,
                neighborhood_radius=artifact.neighborhood_radius,
            )
        )
        if not feature_records:
            adjusted_predictions.append(base_prediction.copy())
            continue
        observed_counts = summarize_observations(
            observations_by_seed.get(seed_index, []),
            map_height=base_prediction.shape[0],
            map_width=base_prediction.shape[1],
        )["cell_observation_counts"]
        augmented_records: list[dict[str, Any]] = []
        positions: list[tuple[int, int]] = []
        for feature_record in feature_records:
            x = int(feature_record["x"])
            y = int(feature_record["y"])
            augmented_records.append(
                build_post_observation_feature_record(
                    feature_record=feature_record,
                    base_probs=base_prediction[y, x],
                    observed_summary=observed_summary,
                    coverage_fraction=coverage_fraction,
                )
            )
            positions.append((y, x))
        residuals = _predict_post_observation_residuals(
            model=model,
            X=feature_matrix_from_records(augmented_records, feature_columns=model.feature_columns),
        )
        adjusted = base_prediction.copy()
        for row_index, (y, x) in enumerate(positions):
            blend_alpha = 0.35 if int(observed_counts[y, x]) > 0 else 1.0
            candidate = np.clip(base_prediction[y, x] + (blend_alpha * residuals[row_index]), 1e-12, None)
            candidate /= candidate.sum()
            adjusted[y, x] = candidate
        adjusted_predictions.append(
            apply_probability_floor(adjusted, floor=floor, floor_distribution=artifact.floor_distribution)
        )
    return adjusted_predictions


def train_post_observation_residual_model(
    *,
    base_artifact: SklearnModelArtifact,
    root: str | Path = DEFAULT_OUTPUT_DIR,
    cache_prefix: str = DEFAULT_HISTORY_CACHE_PREFIX,
    include_round_ids: set[str] | None = None,
    exclude_round_ids: set[str] | None = None,
    random_state: int = 0,
    total_queries: int = 50,
    viewport_size: int = 15,
    prior_strength: float = 2.0,
    ridge_alpha: float = 2.5,
) -> PostObservationModelArtifact | None:
    root_path = Path(root)
    index = load_history_index(root=root_path, cache_prefix=cache_prefix)
    if not index:
        return None

    feature_rows: list[dict[str, Any]] = []
    residual_rows: list[np.ndarray] = []
    baseline_rows: list[np.ndarray] = []
    target_rows: list[np.ndarray] = []
    sample_weights: list[float] = []
    rounds_used: list[str] = []
    observed_cell_share: list[float] = []

    for round_entry in index.get("rounds", []):
        round_id = str(round_entry["round_id"])
        if include_round_ids is not None and round_id not in include_round_ids:
            continue
        if exclude_round_ids is not None and round_id in exclude_round_ids:
            continue
        round_detail_path = root_path / cache_prefix / "rounds" / round_id / "public" / "round_detail.json"
        if not round_detail_path.exists():
            continue
        round_detail = json.loads(round_detail_path.read_text())
        observations_by_seed = synthesize_observations_from_analysis(
            round_detail=round_detail,
            round_id=round_id,
            root=root_path,
            cache_prefix=cache_prefix,
            total_queries=total_queries,
            viewport_size=viewport_size,
            history_prior_model=None,
            history_prior_strength=prior_strength,
            prior_strength=prior_strength,
            floor=DEFAULT_PREDICTION_FLOOR,
            random_state=random_state,
        )
        if not any(observations_by_seed.values()):
            continue
        observed_summary = summarize_observed_round_behavior(observations_by_seed)
        total_round_cells = max(_round_total_cell_count(round_detail), 1)
        coverage_fraction = float(observed_summary.get("observed_cells", 0.0) / float(total_round_cells))

        base_predictions = build_round_predictions_from_model(
            artifact=base_artifact,
            round_detail=round_detail,
            floor=DEFAULT_PREDICTION_FLOOR,
        )
        conditioned_predictions: list[np.ndarray] = []
        for seed_index, prediction in enumerate(base_predictions):
            observation_samples = observations_by_seed.get(seed_index, [])
            adjusted = prediction
            if observation_samples:
                adjusted = blend_observations(adjusted, observation_samples, prior_strength=prior_strength)
                adjusted = apply_probability_floor(
                    adjusted,
                    floor=DEFAULT_PREDICTION_FLOOR,
                    floor_distribution=base_artifact.floor_distribution,
                )
            conditioned_predictions.append(adjusted)

        round_used = False
        for seed_index in round_entry.get("analysis_cached_seeds", []):
            analysis_path = root_path / cache_prefix / "rounds" / round_id / "team" / "analysis" / f"seed_{int(seed_index)}.json"
            if not analysis_path.exists() or int(seed_index) >= len(round_detail["initial_states"]):
                continue
            analysis = json.loads(analysis_path.read_text())
            target_tensor = np.asarray(analysis["ground_truth"], dtype=float)
            state = round_detail["initial_states"][int(seed_index)]
            grid = np.asarray(state["grid"], dtype=int)
            if target_tensor.shape[:2] != grid.shape:
                continue
            feature_records = list(
                iter_state_feature_records(
                    state=state,
                    seed_index=int(seed_index),
                    round_id=round_id,
                    round_number=int(round_detail.get("round_number", 0) or 0),
                    neighborhood_radius=base_artifact.neighborhood_radius,
                )
            )
            observed_counts = summarize_observations(
                observations_by_seed.get(int(seed_index), []),
                map_height=grid.shape[0],
                map_width=grid.shape[1],
            )["cell_observation_counts"]
            for feature_record in feature_records:
                x = int(feature_record["x"])
                y = int(feature_record["y"])
                base_probs = np.asarray(conditioned_predictions[int(seed_index)][y, x], dtype=float)
                target_probs = np.asarray(target_tensor[y, x], dtype=float)
                feature_rows.append(
                    build_post_observation_feature_record(
                        feature_record=feature_record,
                        base_probs=base_probs,
                        observed_summary=observed_summary,
                        coverage_fraction=coverage_fraction,
                    )
                )
                residual_rows.append(target_probs - base_probs)
                baseline_rows.append(base_probs)
                target_rows.append(target_probs)
                entropy_weight = float(feature_record.get("entropy_sample_weight", _target_entropy_weight(target_probs)))
                if int(observed_counts[y, x]) > 0:
                    entropy_weight *= 0.35
                    observed_cell_share.append(1.0)
                else:
                    observed_cell_share.append(0.0)
                sample_weights.append(entropy_weight)
                round_used = True
        if round_used:
            rounds_used.append(round_id)

    if len(rounds_used) < 2 or not feature_rows:
        return None

    X = feature_matrix_from_records(feature_rows, feature_columns=POST_OBSERVATION_FEATURE_COLUMNS)
    Y = np.asarray(residual_rows, dtype=np.float32)
    baseline = np.asarray(baseline_rows, dtype=np.float32)
    targets = np.asarray(target_rows, dtype=np.float32)
    weights = np.asarray(sample_weights, dtype=np.float32)
    model = _fit_post_observation_ridge_regression(
        X=X,
        Y=Y,
        sample_weights=weights,
        ridge_alpha=ridge_alpha,
    )
    predicted_residuals = _predict_post_observation_residuals(model=model, X=X)
    fitted = normalize_prediction_rows(np.clip(baseline + predicted_residuals, 1e-12, None))
    training_summary = {
        "records_used": len(feature_rows),
        "rounds_used": len(rounds_used),
        "round_ids": sorted(rounds_used),
        "ridge_alpha": float(ridge_alpha),
        "synthetic_queries": int(total_queries),
        "synthetic_viewport_size": int(viewport_size),
        "baseline_weighted_kl": weighted_kl_loss(targets=targets, predictions=baseline),
        "fitted_weighted_kl": weighted_kl_loss(targets=targets, predictions=fitted),
        "mean_abs_residual": float(np.mean(np.abs(Y))),
        "observed_cell_share": float(np.mean(observed_cell_share)) if observed_cell_share else 0.0,
    }
    model.training_summary.update(training_summary)
    return model


def build_post_observation_feature_record(
    *,
    feature_record: dict[str, Any],
    base_probs: np.ndarray,
    observed_summary: dict[str, Any],
    coverage_fraction: float,
) -> dict[str, Any]:
    class_probs = list(observed_summary.get("class_probs", []))
    if len(class_probs) < CLASS_COUNT:
        class_probs = class_probs + [0.0] * (CLASS_COUNT - len(class_probs))
    class_probs = [float(value) for value in class_probs[:CLASS_COUNT]]
    settlement_proximity = _distance_signal(feature_record.get("nearest_settlement_distance", 0.0), radius=5.0)
    port_proximity = _distance_signal(feature_record.get("nearest_port_distance", 0.0), radius=5.0)
    frontier_signal = float(
        np.clip(float(feature_record.get("terrain_edge_count", 0.0)) / max(float(feature_record.get("neighbor_count", 1.0)) - 1.0, 1.0), 0.0, 1.0)
    )
    coast_adjacent = float(feature_record.get("coast_adjacent", 0.0))
    base_dynamic_mass = float(np.asarray(base_probs, dtype=float)[1:4].sum())
    settlement_density = float(observed_summary.get("observed_settlements", 0.0)) / max(
        float(observed_summary.get("observed_cells", 0.0)),
        1.0,
    )

    record = {column: float(feature_record.get(column, 0.0)) for column in FEATURE_COLUMNS}
    for class_index, value in enumerate(np.asarray(base_probs, dtype=float)):
        record[f"base_prob_{class_index}"] = float(value)
        record[f"obs_class_prob_{class_index}"] = class_probs[class_index]
    record.update(
        {
            "obs_development_signal": float(observed_summary.get("development_signal", 0.0)),
            "obs_conflict_signal": float(observed_summary.get("conflict_signal", 0.0)),
            "obs_trade_signal": float(observed_summary.get("trade_signal", 0.0)),
            "obs_harshness_signal": float(observed_summary.get("harshness_signal", 0.0)),
            "obs_port_signal": float(observed_summary.get("port_signal", 0.0)),
            "obs_forest_signal": float(observed_summary.get("forest_signal", 0.0)),
            "obs_alive_ratio": float(observed_summary.get("alive_ratio", 0.0)),
            "obs_owner_diversity": float(observed_summary.get("owner_diversity", 0.0)),
            "obs_mean_population": _bounded_observation_mean(observed_summary.get("mean_population", 0.0)),
            "obs_mean_food": _bounded_observation_mean(observed_summary.get("mean_food", 0.0)),
            "obs_mean_wealth": _bounded_observation_mean(observed_summary.get("mean_wealth", 0.0)),
            "obs_mean_defense": _bounded_observation_mean(observed_summary.get("mean_defense", 0.0)),
            "obs_settlement_density": settlement_density,
            "obs_coverage_fraction": float(np.clip(coverage_fraction, 0.0, 1.0)),
            "base_dynamic_mass": base_dynamic_mass,
            "settlement_proximity": settlement_proximity,
            "port_proximity": port_proximity,
            "frontier_signal": frontier_signal,
            "development_x_settlement_proximity": float(observed_summary.get("development_signal", 0.0)) * settlement_proximity,
            "trade_x_coast_adjacent": float(observed_summary.get("trade_signal", 0.0)) * coast_adjacent,
            "trade_x_port_proximity": float(observed_summary.get("trade_signal", 0.0)) * port_proximity,
            "conflict_x_frontier": float(observed_summary.get("conflict_signal", 0.0)) * frontier_signal,
            "harshness_x_settlement_proximity": float(observed_summary.get("harshness_signal", 0.0)) * settlement_proximity,
            "dynamic_signal_x_base_dynamic": float(observed_summary.get("development_signal", 0.0) + observed_summary.get("conflict_signal", 0.0)) * base_dynamic_mass,
        }
    )
    return record


def save_model_artifact(artifact: SklearnModelArtifact, output_path: str | Path) -> dict[str, str]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(artifact, handle)

    metadata_path = metadata_path_for_model(path)
    metadata_path.write_text(json.dumps(artifact.to_metadata(), indent=2, sort_keys=True))
    return {"model_path": str(path), "metadata_path": str(metadata_path)}


def load_model_artifact(model_path: str | Path) -> SklearnModelArtifact:
    path = Path(model_path)
    with path.open("rb") as handle:
        artifact = pickle.load(handle)
    if not isinstance(artifact, SklearnModelArtifact):
        raise ValueError(f"Unsupported model artifact type at {path}.")
    return artifact


def metadata_path_for_model(model_path: str | Path) -> Path:
    path = Path(model_path)
    return path.with_name(f"{path.stem}.metadata.json")


def _load_random_forest_regressor() -> Any:
    try:
        from sklearn.ensemble import RandomForestRegressor
    except ImportError as exc:  # pragma: no cover - optional training dependency
        raise SystemExit("Missing training dependency. Install `pip install -r requirements-training.txt`.") from exc
    return RandomForestRegressor


def train_regressor_estimator(
    *,
    RandomForestRegressor: Any,
    X: np.ndarray,
    y: np.ndarray,
    sample_weights: np.ndarray,
    n_estimators: int,
    min_samples_leaf: int,
    random_state: int,
) -> Any:
    estimator = RandomForestRegressor(
        n_estimators=n_estimators,
        min_samples_leaf=min_samples_leaf,
        random_state=random_state,
        n_jobs=-1,
    )
    estimator.fit(X, y, sample_weight=sample_weights)
    return estimator


def fit_temperature_calibration(
    *,
    raw_predictions: np.ndarray,
    targets: np.ndarray,
    candidate_temperatures: tuple[float, ...] = (0.75, 0.9, 1.0, 1.1, 1.25, 1.5),
) -> tuple[float, dict[str, Any]]:
    normalized = normalize_prediction_rows(raw_predictions)
    best_temperature = 1.0
    best_loss = None
    results = []
    for temperature in candidate_temperatures:
        calibrated = apply_temperature_calibration(normalized, temperature)
        loss = weighted_kl_loss(targets=targets, predictions=calibrated)
        results.append({"temperature": float(temperature), "weighted_kl": float(loss)})
        if best_loss is None or loss < best_loss:
            best_loss = loss
            best_temperature = float(temperature)
    return best_temperature, {"results": results, "best_weighted_kl": float(best_loss or 0.0)}


def fit_temperature_calibration_from_heldout_rounds(
    *,
    records: list[dict[str, Any]],
    neighborhood_radius: int,
    n_estimators: int,
    min_samples_leaf: int,
    random_state: int,
) -> tuple[float, dict[str, Any]]:
    round_items = sorted(
        {(int(record["round_number"]), str(record["round_id"])) for record in records},
        key=lambda item: item[0],
    )
    if len(round_items) < 3:
        return 1.0, {
            "method": "insufficient_rounds_fallback",
            "calibration_round_ids": [],
            "calibration_round_numbers": [],
            "calibration_records": 0,
            "results": [{"temperature": 1.0, "weighted_kl": 0.0}],
            "best_weighted_kl": 0.0,
        }

    calibration_count = 1 if len(round_items) < 8 else 2
    calibration_rounds = round_items[-calibration_count:]
    calibration_round_ids = {round_id for _round_number, round_id in calibration_rounds}
    calibration_records = [record for record in records if str(record["round_id"]) in calibration_round_ids]
    training_records = [record for record in records if str(record["round_id"]) not in calibration_round_ids]
    if not calibration_records or not training_records:
        return 1.0, {
            "method": "insufficient_records_fallback",
            "calibration_round_ids": sorted(calibration_round_ids),
            "calibration_round_numbers": [round_number for round_number, _round_id in calibration_rounds],
            "calibration_records": len(calibration_records),
            "results": [{"temperature": 1.0, "weighted_kl": 0.0}],
            "best_weighted_kl": 0.0,
        }

    RandomForestRegressor = _load_random_forest_regressor()
    train_X = feature_matrix_from_records(training_records, feature_columns=FEATURE_COLUMNS)
    train_y = np.asarray([record["target_probs"] for record in training_records], dtype=np.float32)
    train_sample_weights = compute_entropy_sample_weights(training_records)
    estimator = train_regressor_estimator(
        RandomForestRegressor=RandomForestRegressor,
        X=train_X,
        y=train_y,
        sample_weights=train_sample_weights,
        n_estimators=n_estimators,
        min_samples_leaf=min_samples_leaf,
        random_state=random_state,
    )
    calibration_X = feature_matrix_from_records(calibration_records, feature_columns=FEATURE_COLUMNS)
    calibration_targets = np.asarray([record["target_probs"] for record in calibration_records], dtype=np.float32)
    raw_predictions = np.asarray(estimator.predict(calibration_X), dtype=float)
    temperature, summary = fit_temperature_calibration(raw_predictions=raw_predictions, targets=calibration_targets)
    summary.update(
        {
            "method": "heldout_recent_rounds",
            "calibration_round_ids": sorted(calibration_round_ids),
            "calibration_round_numbers": [round_number for round_number, _round_id in calibration_rounds],
            "calibration_records": len(calibration_records),
            "training_records_for_calibration": len(training_records),
            "neighborhood_radius": int(neighborhood_radius),
        }
    )
    return temperature, summary


def apply_temperature_calibration(predictions: np.ndarray, temperature: float) -> np.ndarray:
    tensor = np.asarray(predictions, dtype=float)
    normalized = normalize_prediction_rows(tensor)
    if float(temperature) <= 0:
        return normalized
    logits = np.log(np.clip(normalized, 1e-12, 1.0))
    scaled = np.exp(logits / float(temperature))
    scaled /= scaled.sum(axis=-1, keepdims=True)
    return scaled


def normalize_prediction_rows(predictions: np.ndarray) -> np.ndarray:
    tensor = np.asarray(predictions, dtype=float)
    tensor = np.clip(tensor, 0.0, None)
    row_sums = tensor.sum(axis=-1, keepdims=True)
    zero_rows = row_sums.squeeze(-1) <= 0
    if np.any(zero_rows):
        tensor = tensor.copy()
        tensor[zero_rows] = 1.0 / CLASS_COUNT
        row_sums = tensor.sum(axis=-1, keepdims=True)
    tensor /= row_sums
    return tensor


def compute_entropy_sample_weights(records: list[dict[str, Any]]) -> np.ndarray:
    if not records:
        return np.zeros((0,), dtype=np.float32)
    weights = np.asarray(
        [float(record.get("entropy_sample_weight", float(record.get("target_entropy", 0.0)))) for record in records],
        dtype=np.float32,
    )
    weights = np.clip(weights, 0.05, None)
    mean_value = float(weights.mean()) if weights.size else 1.0
    if mean_value > 0:
        weights = weights / mean_value
    return weights


def weighted_kl_loss(*, targets: np.ndarray, predictions: np.ndarray) -> float:
    target_tensor = np.asarray(targets, dtype=float)
    pred_tensor = np.asarray(predictions, dtype=float)
    target_tensor = normalize_prediction_rows(target_tensor)
    pred_tensor = normalize_prediction_rows(pred_tensor)
    clipped_target = np.clip(target_tensor, 1e-12, 1.0)
    clipped_pred = np.clip(pred_tensor, 1e-12, 1.0)
    entropy = -np.sum(clipped_target * np.log(clipped_target), axis=-1)
    kl = np.sum(clipped_target * (np.log(clipped_target) - np.log(clipped_pred)), axis=-1)
    total_entropy = float(np.sum(entropy))
    if total_entropy <= 0:
        return float(np.mean(kl))
    return float(np.sum(entropy * kl) / total_entropy)


def _fit_post_observation_ridge_regression(
    *,
    X: np.ndarray,
    Y: np.ndarray,
    sample_weights: np.ndarray,
    ridge_alpha: float,
) -> PostObservationModelArtifact:
    X = np.asarray(X, dtype=np.float32)
    Y = np.asarray(Y, dtype=np.float32)
    weights = np.asarray(sample_weights, dtype=np.float32)
    if weights.size != X.shape[0]:
        raise ValueError("sample_weights length must match training rows.")

    feature_mean = X.mean(axis=0)
    feature_scale = X.std(axis=0)
    feature_scale[feature_scale < 1e-6] = 1.0
    standardized = (X - feature_mean) / feature_scale
    sqrt_weights = np.sqrt(np.clip(weights, 1e-6, None)).reshape(-1, 1)
    weighted_X = standardized * sqrt_weights
    weighted_Y = Y * sqrt_weights
    xtx = weighted_X.T @ weighted_X
    xtx += np.eye(xtx.shape[0], dtype=np.float32) * float(ridge_alpha)
    xty = weighted_X.T @ weighted_Y
    coefficients = np.linalg.solve(xtx, xty)
    intercept = np.average(Y, axis=0, weights=weights) if weights.sum() > 0 else Y.mean(axis=0)
    return PostObservationModelArtifact(
        feature_columns=list(POST_OBSERVATION_FEATURE_COLUMNS),
        feature_mean=np.asarray(feature_mean, dtype=np.float32),
        feature_scale=np.asarray(feature_scale, dtype=np.float32),
        coefficients=np.asarray(coefficients, dtype=np.float32),
        intercept=np.asarray(intercept, dtype=np.float32),
        ridge_alpha=float(ridge_alpha),
        training_summary={},
    )


def _predict_post_observation_residuals(
    *,
    model: PostObservationModelArtifact,
    X: np.ndarray,
) -> np.ndarray:
    standardized = (np.asarray(X, dtype=np.float32) - model.feature_mean) / model.feature_scale
    return np.asarray(model.intercept + (standardized @ model.coefficients), dtype=np.float32)


def _round_total_cell_count(round_detail: dict[str, Any]) -> int:
    total = 0
    for state in round_detail.get("initial_states", []):
        grid = np.asarray(state["grid"], dtype=int)
        total += int(grid.size)
    return total


def _target_entropy_weight(target_probs: np.ndarray) -> float:
    probs = np.asarray(target_probs, dtype=float)
    clipped = np.clip(probs, 1e-12, 1.0)
    entropy = float(-(clipped * np.log(clipped)).sum())
    normalized_entropy = entropy / float(np.log(len(clipped))) if len(clipped) > 1 else 0.0
    return float(0.15 + (1.85 * normalized_entropy))


def _distance_signal(distance: Any, *, radius: float) -> float:
    return float(np.exp(-max(float(distance), 0.0) / max(float(radius), 1e-6)))


def _bounded_observation_mean(value: Any) -> float:
    return float(1.0 - np.exp(-max(float(value), 0.0) / 100.0))

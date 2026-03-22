from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from baseline import CLASS_COUNT, apply_probability_floor
from config import DEFAULT_HISTORY_CACHE_PREFIX, DEFAULT_OUTPUT_DIR, DEFAULT_PREDICTION_FLOOR
from feature_engineering import FEATURE_COLUMNS, feature_matrix_from_records, iter_state_feature_records
from history_dataset import iter_history_dataset_records


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

    return SklearnModelArtifact(
        estimator=estimator,
        model_type="random_forest_regressor",
        feature_columns=list(FEATURE_COLUMNS),
        class_labels=list(range(CLASS_COUNT)),
        neighborhood_radius=neighborhood_radius,
        floor_distribution=floor_distribution,
        calibration_temperature=float(calibration_temperature),
        training_summary=training_summary,
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

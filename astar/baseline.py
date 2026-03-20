from __future__ import annotations

from typing import Any

import numpy as np

CLASS_COUNT = 6
DEFAULT_FLOOR = 0.01

STATIC_PRIORS = {
    10: np.array([0.93, 0.01, 0.01, 0.01, 0.02, 0.02], dtype=float),  # Ocean
    11: np.array([0.84, 0.04, 0.02, 0.03, 0.04, 0.03], dtype=float),  # Plains
    0: np.array([0.84, 0.04, 0.02, 0.03, 0.04, 0.03], dtype=float),   # Empty
    1: np.array([0.18, 0.45, 0.10, 0.14, 0.08, 0.05], dtype=float),   # Settlement
    2: np.array([0.14, 0.18, 0.48, 0.10, 0.05, 0.05], dtype=float),   # Port
    3: np.array([0.18, 0.08, 0.05, 0.50, 0.14, 0.05], dtype=float),   # Ruin
    4: np.array([0.08, 0.05, 0.02, 0.05, 0.75, 0.05], dtype=float),   # Forest
    5: np.array([0.03, 0.01, 0.01, 0.01, 0.02, 0.92], dtype=float),   # Mountain
}


def terrain_code_to_class_index(terrain_code: int) -> int:
    if terrain_code in {0, 10, 11}:
        return 0
    return int(terrain_code)


def build_round_predictions(
    round_detail: dict[str, Any],
    floor: float = DEFAULT_FLOOR,
    observations_by_seed: dict[int, list[dict[str, Any]]] | None = None,
    prior_strength: float = 2.0,
) -> list[np.ndarray]:
    predictions: list[np.ndarray] = []
    observations_by_seed = observations_by_seed or {}
    for seed_index, state in enumerate(round_detail["initial_states"]):
        predictions.append(
            build_seed_prediction(
                state,
                floor=floor,
                observation_samples=observations_by_seed.get(seed_index),
                prior_strength=prior_strength,
            )
        )
    return predictions


def build_seed_prediction(
    state: dict[str, Any],
    floor: float = DEFAULT_FLOOR,
    observation_samples: list[dict[str, Any]] | None = None,
    prior_strength: float = 2.0,
) -> np.ndarray:
    grid = np.asarray(state["grid"], dtype=int)
    height, width = grid.shape
    prediction = np.zeros((height, width, CLASS_COUNT), dtype=float)

    for y in range(height):
        for x in range(width):
            prediction[y, x] = STATIC_PRIORS.get(int(grid[y, x]), STATIC_PRIORS[0]).copy()

    for settlement in state.get("settlements", []):
        x = int(settlement["x"])
        y = int(settlement["y"])
        has_port = bool(settlement.get("has_port"))
        if has_port:
            prediction[y, x] = np.array([0.10, 0.18, 0.50, 0.10, 0.07, 0.05], dtype=float)
        else:
            prediction[y, x] = np.array([0.12, 0.48, 0.10, 0.15, 0.10, 0.05], dtype=float)

    if observation_samples:
        prediction = blend_observations(prediction, observation_samples, prior_strength=prior_strength)

    prediction = np.maximum(prediction, floor)
    prediction /= prediction.sum(axis=-1, keepdims=True)
    return prediction


def blend_observations(
    prior_prediction: np.ndarray,
    observation_samples: list[dict[str, Any]],
    prior_strength: float = 2.0,
) -> np.ndarray:
    posterior = prior_prediction.astype(float, copy=True) * max(prior_strength, 0.0)
    for sample in observation_samples:
        viewport = sample["viewport"]
        grid = np.asarray(sample["grid"], dtype=int)
        x0 = int(viewport["x"])
        y0 = int(viewport["y"])
        for dy in range(grid.shape[0]):
            for dx in range(grid.shape[1]):
                posterior[y0 + dy, x0 + dx, terrain_code_to_class_index(int(grid[dy, dx]))] += 1.0
    return posterior

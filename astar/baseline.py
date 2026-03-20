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


def build_round_predictions(round_detail: dict[str, Any], floor: float = DEFAULT_FLOOR) -> list[np.ndarray]:
    predictions: list[np.ndarray] = []
    for state in round_detail["initial_states"]:
        predictions.append(build_seed_prediction(state, floor=floor))
    return predictions


def build_seed_prediction(state: dict[str, Any], floor: float = DEFAULT_FLOOR) -> np.ndarray:
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

    prediction = np.maximum(prediction, floor)
    prediction /= prediction.sum(axis=-1, keepdims=True)
    return prediction

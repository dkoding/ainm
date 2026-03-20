from __future__ import annotations

from typing import Any

import numpy as np

CLASS_COUNT = 6
DEFAULT_FLOOR = 0.02

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
    history_prior_model: Any | None = None,
    history_prior_strength: float = 2.0,
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
                history_prior_model=history_prior_model,
                history_prior_strength=history_prior_strength,
            )
        )
    return predictions


def build_seed_prediction(
    state: dict[str, Any],
    floor: float = DEFAULT_FLOOR,
    observation_samples: list[dict[str, Any]] | None = None,
    prior_strength: float = 2.0,
    history_prior_model: Any | None = None,
    history_prior_strength: float = 2.0,
) -> np.ndarray:
    grid = np.asarray(state["grid"], dtype=int)
    height, width = grid.shape
    prediction = np.zeros((height, width, CLASS_COUNT), dtype=float)

    for y in range(height):
        for x in range(width):
            base_prior = build_contextual_prior(grid=grid, x=x, y=y)
            history_prior = None
            if history_prior_model is not None:
                history_prior = history_prior_model.terrain_prior(int(grid[y, x]))
            prediction[y, x] = blend_prior_sources(
                base_prior,
                learned_prior=history_prior,
                learned_strength=history_prior_strength,
            )

    for settlement in state.get("settlements", []):
        x = int(settlement["x"])
        y = int(settlement["y"])
        has_port = bool(settlement.get("has_port"))
        if has_port:
            base_prior = np.array([0.10, 0.18, 0.50, 0.10, 0.07, 0.05], dtype=float)
        else:
            base_prior = np.array([0.12, 0.48, 0.10, 0.15, 0.10, 0.05], dtype=float)
        history_prior = None
        if history_prior_model is not None:
            history_prior = history_prior_model.settlement_prior(has_port)
        prediction[y, x] = blend_prior_sources(
            base_prior,
            learned_prior=history_prior,
            learned_strength=history_prior_strength,
        )

    if observation_samples:
        prediction = blend_observations(prediction, observation_samples, prior_strength=prior_strength)

    floor_distribution = None
    if history_prior_model is not None:
        floor_distribution = history_prior_model.global_class_probs
    prediction = apply_probability_floor(prediction, floor=floor, floor_distribution=floor_distribution)
    return prediction


def blend_observations(
    prior_prediction: np.ndarray,
    observation_samples: list[dict[str, Any]],
    prior_strength: float = 2.0,
) -> np.ndarray:
    posterior = prior_prediction.astype(float, copy=True) * max(prior_strength, 0.0)
    summary = summarize_observations(observation_samples, posterior.shape[0], posterior.shape[1])
    for (y, x), counts in summary["cell_class_counts"].items():
        posterior[y, x] += counts
    return posterior


def blend_prior_sources(
    base_prior: np.ndarray,
    learned_prior: np.ndarray | None,
    learned_strength: float,
) -> np.ndarray:
    if learned_prior is None or learned_strength <= 0:
        return base_prior.copy()
    posterior = base_prior.astype(float, copy=True) + learned_prior.astype(float, copy=False) * float(learned_strength)
    posterior /= posterior.sum()
    return posterior


def build_contextual_prior(grid: np.ndarray, x: int, y: int) -> np.ndarray:
    terrain_code = int(grid[y, x])
    prior = STATIC_PRIORS.get(terrain_code, STATIC_PRIORS[0]).copy()

    neighbors = [(nx, ny) for nx, ny in _neighbors(x=x, y=y, width=grid.shape[1], height=grid.shape[0])]
    neighbor_codes = [int(grid[ny, nx]) for nx, ny in neighbors]
    ocean_neighbors = sum(code == 10 for code in neighbor_codes)
    settlement_neighbors = sum(code in {1, 2, 3} for code in neighbor_codes)
    mountain_neighbors = sum(code == 5 for code in neighbor_codes)
    forest_neighbors = sum(code == 4 for code in neighbor_codes)
    edge_count = sum(code != terrain_code for code in neighbor_codes)

    if terrain_code == 5 and mountain_neighbors >= 2:
        prior = np.array([0.02, 0.005, 0.005, 0.01, 0.01, 0.95], dtype=float)
    elif terrain_code == 4 and forest_neighbors >= 2:
        prior = np.array([0.05, 0.03, 0.015, 0.04, 0.83, 0.035], dtype=float)

    if terrain_code in {0, 11, 4} and ocean_neighbors > 0:
        prior = prior + np.array([0.0, 0.02, 0.025, 0.0, -0.01, -0.005], dtype=float)
    if terrain_code in {0, 11, 4} and settlement_neighbors > 0:
        prior = prior + np.array([-0.03, 0.04, 0.01, 0.03, -0.02, -0.03], dtype=float)
    if terrain_code in {0, 11, 4} and edge_count >= 3:
        prior = 0.75 * prior + 0.25 * np.array([0.25, 0.18, 0.08, 0.12, 0.22, 0.15], dtype=float)
    if terrain_code in {0, 11} and mountain_neighbors >= 2:
        prior = prior + np.array([-0.02, -0.01, -0.01, 0.0, 0.0, 0.04], dtype=float)

    prior = np.clip(prior, 1e-6, None)
    prior /= prior.sum()
    return prior


def apply_probability_floor(
    prediction: np.ndarray,
    floor: float,
    floor_distribution: np.ndarray | None = None,
) -> np.ndarray:
    if floor_distribution is None:
        floor_distribution = np.full(CLASS_COUNT, 1.0 / CLASS_COUNT, dtype=float)
    floor_distribution = np.asarray(floor_distribution, dtype=float)
    floor_distribution = floor_distribution / floor_distribution.sum()
    adjusted = prediction.astype(float, copy=True)
    adjusted += floor * floor_distribution
    adjusted = np.maximum(adjusted, 1e-12)
    adjusted /= adjusted.sum(axis=-1, keepdims=True)
    return adjusted


def summarize_observations(
    observation_samples: list[dict[str, Any]],
    map_height: int,
    map_width: int,
) -> dict[str, Any]:
    cell_class_counts: dict[tuple[int, int], np.ndarray] = {}
    cell_observation_counts = np.zeros((map_height, map_width), dtype=int)

    for sample in observation_samples:
        viewport = sample["viewport"]
        grid = np.asarray(sample["grid"], dtype=int)
        x0 = int(viewport["x"])
        y0 = int(viewport["y"])
        for dy in range(grid.shape[0]):
            for dx in range(grid.shape[1]):
                y = y0 + dy
                x = x0 + dx
                key = (y, x)
                if key not in cell_class_counts:
                    cell_class_counts[key] = np.zeros(CLASS_COUNT, dtype=float)
                cell_class_counts[key][terrain_code_to_class_index(int(grid[dy, dx]))] += 1.0
                cell_observation_counts[y, x] += 1

    entropy_by_cell: dict[tuple[int, int], float] = {}
    for key, counts in cell_class_counts.items():
        probs = counts / counts.sum()
        positive = probs > 0
        entropy_by_cell[key] = float(-np.sum(probs[positive] * np.log(probs[positive])))

    return {
        "cell_class_counts": cell_class_counts,
        "cell_observation_counts": cell_observation_counts,
        "cell_entropy": entropy_by_cell,
    }


def _neighbors(x: int, y: int, width: int, height: int) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx = x + dx
        ny = y + dy
        if 0 <= nx < width and 0 <= ny < height:
            result.append((nx, ny))
    return result

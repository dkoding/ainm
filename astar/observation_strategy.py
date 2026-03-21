from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from baseline import build_seed_prediction, summarize_observations
from history_priors import HistoryPriorModel


@dataclass(frozen=True)
class ViewportRequest:
    seed_index: int
    viewport_x: int
    viewport_y: int
    viewport_w: int
    viewport_h: int

    def to_payload(self, round_id: str) -> dict[str, Any]:
        payload = asdict(self)
        payload["round_id"] = round_id
        return payload


def build_round_viewport_plan(
    round_detail: dict[str, Any],
    total_queries: int,
    viewport_size: int = 15,
    observations_by_seed: dict[int, list[dict[str, Any]]] | None = None,
    history_prior_model: Any | None = None,
    history_prior_strength: float = 2.0,
    prior_strength: float = 2.0,
    floor: float = 0.02,
) -> dict[int, list[ViewportRequest]]:
    plan, _ = build_round_viewport_plan_with_trace(
        round_detail=round_detail,
        total_queries=total_queries,
        viewport_size=viewport_size,
        observations_by_seed=observations_by_seed,
        history_prior_model=history_prior_model,
        history_prior_strength=history_prior_strength,
        prior_strength=prior_strength,
        floor=floor,
    )
    return plan


def build_round_viewport_plan_with_trace(
    round_detail: dict[str, Any],
    total_queries: int,
    viewport_size: int = 15,
    observations_by_seed: dict[int, list[dict[str, Any]]] | None = None,
    history_prior_model: Any | None = None,
    history_prior_strength: float = 2.0,
    prior_strength: float = 2.0,
    floor: float = 0.02,
) -> tuple[dict[int, list[ViewportRequest]], list[dict[str, Any]]]:
    if total_queries < 0:
        raise ValueError("total_queries must be non-negative.")
    height = int(round_detail["map_height"])
    width = int(round_detail["map_width"])
    seeds_count = len(round_detail["initial_states"])
    plan: dict[int, list[ViewportRequest]] = {seed_index: [] for seed_index in range(seeds_count)}
    trace: list[dict[str, Any]] = []
    if total_queries == 0:
        return plan, trace

    current_observations = {int(seed_index): list(samples) for seed_index, samples in (observations_by_seed or {}).items()}
    for _ in range(total_queries):
        selection = select_next_viewport_request(
            round_detail=round_detail,
            viewport_size=viewport_size,
            observations_by_seed=current_observations,
            already_selected=plan,
            history_prior_model=history_prior_model,
            history_prior_strength=history_prior_strength,
            prior_strength=prior_strength,
            floor=floor,
            map_width=width,
            map_height=height,
        )
        if selection is None:
            break
        request = selection["request"]
        assert isinstance(request, ViewportRequest)
        plan[request.seed_index].append(request)
        trace.append(
            {
                "query_index": len(trace),
                "seed_index": request.seed_index,
                "viewport_x": request.viewport_x,
                "viewport_y": request.viewport_y,
                "viewport_w": request.viewport_w,
                "viewport_h": request.viewport_h,
                "phase": selection["phase"],
                "score": float(selection["score"]),
                "score_components": selection["score_components"],
            }
        )
    return plan, trace


def select_next_viewport_request(
    *,
    round_detail: dict[str, Any],
    viewport_size: int,
    observations_by_seed: dict[int, list[dict[str, Any]]] | None,
    already_selected: dict[int, list[ViewportRequest]] | None = None,
    history_prior_model: Any | None = None,
    history_prior_strength: float = 2.0,
    prior_strength: float = 2.0,
    floor: float = 0.02,
    existing_window_counts: dict[tuple[int, int, int, int, int], int] | None = None,
    map_width: int | None = None,
    map_height: int | None = None,
) -> dict[str, Any] | None:
    observations_by_seed = observations_by_seed or {}
    already_selected = already_selected or {}
    existing_window_counts = dict(existing_window_counts or {})
    for seed_requests in already_selected.values():
        for request in seed_requests:
            key = request_key(request)
            existing_window_counts[key] = existing_window_counts.get(key, 0) + 1
    for key, count in _window_counts_from_observations(observations_by_seed).items():
        existing_window_counts[key] = max(existing_window_counts.get(key, 0), int(count))
    if map_width is None:
        map_width = int(round_detail["map_width"])
    if map_height is None:
        map_height = int(round_detail["map_height"])

    coverage = seed_unique_coverage(round_detail=round_detail, observations_by_seed=observations_by_seed, already_selected=already_selected)
    minimum_seed_coverage = min(coverage.values(), default=0)

    candidates: list[dict[str, Any]] = []
    unique_candidates_exist = False
    for seed_index, state in enumerate(round_detail["initial_states"]):
        current_prediction = build_seed_prediction(
            state=state,
            floor=floor,
            observation_samples=observations_by_seed.get(seed_index, []),
            prior_strength=prior_strength,
            history_prior_model=history_prior_model,
            history_prior_strength=history_prior_strength,
        )
        entropy_grid = _entropy_grid(current_prediction)
        observation_summary = summarize_observations(
            observations_by_seed.get(seed_index, []),
            map_height=map_height,
            map_width=map_width,
        )

        for request in build_seed_tiled_sweep_requests(
            seed_index=seed_index,
            map_width=map_width,
            map_height=map_height,
            viewport_size=viewport_size,
        ):
            key = request_key(request)
            repeat_count = int(existing_window_counts.get(key, 0))
            is_unique_candidate = repeat_count == 0
            if minimum_seed_coverage == 0 and coverage.get(seed_index, 0) > minimum_seed_coverage and is_unique_candidate:
                # First ensure one explored window per seed before doubling up.
                continue
            if minimum_seed_coverage == 0 and not is_unique_candidate:
                continue
            scored = score_viewport_request(
                state=state,
                request=request,
                entropy_grid=entropy_grid,
                observation_summary=observation_summary,
                repeat_count=repeat_count,
                seed_unique_coverage=coverage.get(seed_index, 0),
                history_prior_model=history_prior_model,
            )
            phase = "explore" if is_unique_candidate else "exploit"
            if is_unique_candidate:
                unique_candidates_exist = True
            candidates.append(
                {
                    "request": request,
                    "phase": phase,
                    "score": scored["score"],
                    "score_components": scored["score_components"],
                    "repeat_count": repeat_count,
                }
            )

    if not candidates:
        return None
    if unique_candidates_exist:
        candidates = [item for item in candidates if item["repeat_count"] == 0]
    return max(candidates, key=lambda item: (item["score"], -item["repeat_count"], -item["request"].seed_index))


def seed_unique_coverage(
    *,
    round_detail: dict[str, Any],
    observations_by_seed: dict[int, list[dict[str, Any]]] | None,
    already_selected: dict[int, list[ViewportRequest]] | None,
) -> dict[int, int]:
    observations_by_seed = observations_by_seed or {}
    already_selected = already_selected or {}
    coverage: dict[int, int] = {}
    for seed_index, _state in enumerate(round_detail["initial_states"]):
        windows = set()
        for request in already_selected.get(seed_index, []):
            windows.add(request_key(request))
        for sample in observations_by_seed.get(seed_index, []):
            viewport = sample["viewport"]
            windows.add(
                (
                    seed_index,
                    int(viewport["x"]),
                    int(viewport["y"]),
                    int(viewport["w"]),
                    int(viewport["h"]),
                )
            )
        coverage[seed_index] = len(windows)
    return coverage


def build_seed_tiled_sweep_requests(
    seed_index: int,
    map_width: int,
    map_height: int,
    viewport_size: int = 15,
) -> list[ViewportRequest]:
    requests: list[ViewportRequest] = []
    x_segments = _axis_segments(map_width, viewport_size)
    y_segments = _axis_segments(map_height, viewport_size)
    for viewport_y, viewport_h in y_segments:
        for viewport_x, viewport_w in x_segments:
            requests.append(
                ViewportRequest(
                    seed_index=seed_index,
                    viewport_x=viewport_x,
                    viewport_y=viewport_y,
                    viewport_w=viewport_w,
                    viewport_h=viewport_h,
                )
            )
    return requests


def score_viewport_request(
    *,
    state: dict[str, Any],
    request: ViewportRequest,
    entropy_grid: np.ndarray,
    observation_summary: dict[str, Any],
    repeat_count: int,
    seed_unique_coverage: int,
    history_prior_model: HistoryPriorModel | None = None,
) -> dict[str, Any]:
    grid = np.asarray(state["grid"], dtype=int)
    settlements = list(state.get("settlements", []))
    x0 = request.viewport_x
    y0 = request.viewport_y
    x1 = x0 + request.viewport_w
    y1 = y0 + request.viewport_h

    patch = grid[y0:y1, x0:x1]
    entropy_patch = entropy_grid[y0:y1, x0:x1]
    observed_counts = observation_summary["cell_observation_counts"][y0:y1, x0:x1]
    observation_entropy = observation_summary["cell_entropy"]

    unobserved_fraction = float(np.mean(observed_counts == 0))
    predicted_entropy_mean = float(entropy_patch.mean())
    historical_volatility = float(np.mean(_terrain_volatility_proxy(patch)))
    settlement_importance = _settlement_importance(settlements=settlements, request=request)
    coastline_importance = _coastline_importance(grid=grid, request=request)
    frontier_importance = _frontier_importance(grid=grid, request=request)
    regime_disagreement = _regime_disagreement(state=state, request=request, history_prior_model=history_prior_model)

    observed_uncertainty_sum = 0.0
    observed_uncertainty_cells = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            value = observation_entropy.get((y, x))
            if value is None:
                continue
            observed_uncertainty_sum += float(value)
            observed_uncertainty_cells += 1
    observed_uncertainty_mean = (
        float(observed_uncertainty_sum / observed_uncertainty_cells) if observed_uncertainty_cells > 0 else 0.0
    )

    coverage_bonus = 1.0 / float(seed_unique_coverage + 1)
    repeat_penalty = 1.0 / float(repeat_count + 1)
    if repeat_count == 0:
        phase_boost = 1.0
        score = (
            2.0 * unobserved_fraction
            + 1.6 * predicted_entropy_mean
            + 0.8 * historical_volatility
            + 0.45 * settlement_importance
            + 0.25 * coastline_importance
            + 0.30 * frontier_importance
            + 0.90 * regime_disagreement
            + 0.55 * coverage_bonus
        )
    else:
        phase_boost = 0.0
        score = (
            2.2 * observed_uncertainty_mean
            + 1.0 * predicted_entropy_mean
            + 0.5 * historical_volatility
            + 0.30 * settlement_importance
            + 0.20 * coastline_importance
            + 0.25 * frontier_importance
            + 0.25 * regime_disagreement
        ) * repeat_penalty

    return {
        "score": float(score),
        "score_components": {
            "predicted_entropy_mean": predicted_entropy_mean,
            "historical_volatility": historical_volatility,
            "unobserved_fraction": unobserved_fraction,
            "observed_uncertainty_mean": observed_uncertainty_mean,
            "settlement_importance": settlement_importance,
            "coastline_importance": coastline_importance,
            "frontier_importance": frontier_importance,
            "regime_disagreement": regime_disagreement,
            "coverage_bonus": coverage_bonus,
            "repeat_penalty": repeat_penalty,
            "repeat_count": repeat_count,
            "phase_boost": phase_boost,
        },
    }


def request_key(request: ViewportRequest) -> tuple[int, int, int, int, int]:
    return (
        int(request.seed_index),
        int(request.viewport_x),
        int(request.viewport_y),
        int(request.viewport_w),
        int(request.viewport_h),
    )


def _window_counts_from_observations(observations_by_seed: dict[int, list[dict[str, Any]]]) -> dict[tuple[int, int, int, int, int], int]:
    counts: dict[tuple[int, int, int, int, int], int] = {}
    for seed_index, samples in observations_by_seed.items():
        for sample in samples:
            viewport = sample["viewport"]
            key = (
                int(seed_index),
                int(viewport["x"]),
                int(viewport["y"]),
                int(viewport["w"]),
                int(viewport["h"]),
            )
            counts[key] = counts.get(key, 0) + 1
    return counts


def _axis_segments(length: int, viewport_size: int) -> list[tuple[int, int]]:
    if length <= 0:
        return []
    if viewport_size <= 0:
        raise ValueError("viewport_size must be positive.")
    segments: list[tuple[int, int]] = []
    start = 0
    while start < length:
        size = min(viewport_size, length - start)
        segments.append((start, size))
        start += viewport_size
    return segments


def _entropy_grid(prediction: np.ndarray) -> np.ndarray:
    clipped = np.clip(prediction, 1e-12, 1.0)
    return -np.sum(clipped * np.log(clipped), axis=-1)


def _terrain_volatility_proxy(patch: np.ndarray) -> np.ndarray:
    volatility = np.full(patch.shape, 0.3, dtype=float)
    volatility[np.isin(patch, [10, 5])] = 0.05
    volatility[np.isin(patch, [4])] = 0.45
    volatility[np.isin(patch, [0, 11])] = 0.55
    volatility[np.isin(patch, [1, 2, 3])] = 0.85
    return volatility


def _settlement_importance(settlements: list[dict[str, Any]], request: ViewportRequest) -> float:
    score = 0.0
    x0 = request.viewport_x
    y0 = request.viewport_y
    x1 = x0 + request.viewport_w
    y1 = y0 + request.viewport_h
    for settlement in settlements:
        sx = int(settlement["x"])
        sy = int(settlement["y"])
        if x0 <= sx < x1 and y0 <= sy < y1:
            score += 1.0
            if settlement.get("has_port"):
                score += 0.5
    return score / max(1.0, float(request.viewport_w * request.viewport_h) / 25.0)


def _coastline_importance(grid: np.ndarray, request: ViewportRequest) -> float:
    x0 = request.viewport_x
    y0 = request.viewport_y
    x1 = x0 + request.viewport_w
    y1 = y0 + request.viewport_h
    score = 0.0
    for y in range(y0, y1):
        for x in range(x0, x1):
            center = int(grid[y, x])
            neighbor_codes = [int(grid[ny, nx]) for nx, ny in _neighbors(x, y, grid.shape[1], grid.shape[0])]
            if any((code == 10) != (center == 10) for code in neighbor_codes):
                score += 1.0
    return score / max(1.0, float(request.viewport_w * request.viewport_h))


def _frontier_importance(grid: np.ndarray, request: ViewportRequest) -> float:
    x0 = request.viewport_x
    y0 = request.viewport_y
    x1 = x0 + request.viewport_w
    y1 = y0 + request.viewport_h
    score = 0.0
    for y in range(y0, y1):
        for x in range(x0, x1):
            center = int(grid[y, x])
            neighbor_codes = [int(grid[ny, nx]) for nx, ny in _neighbors(x, y, grid.shape[1], grid.shape[0])]
            score += sum(1 for code in neighbor_codes if code != center)
    return score / max(1.0, float(request.viewport_w * request.viewport_h) * 4.0)


def _regime_disagreement(
    *,
    state: dict[str, Any],
    request: ViewportRequest,
    history_prior_model: HistoryPriorModel | None,
) -> float:
    if history_prior_model is None or len(history_prior_model.round_priors) < 2:
        return 0.0
    grid = np.asarray(state["grid"], dtype=int)
    settlement_map = {
        (int(settlement["x"]), int(settlement["y"])): bool(settlement.get("has_port"))
        for settlement in state.get("settlements", [])
    }
    x0 = request.viewport_x
    y0 = request.viewport_y
    x1 = x0 + request.viewport_w
    y1 = y0 + request.viewport_h
    round_vectors: list[np.ndarray] = []
    round_weights: list[float] = []
    for round_prior in history_prior_model.round_priors:
        weight = float(history_prior_model.round_weights.get(round_prior.round_id, 0.0))
        if weight <= 0:
            continue
        aggregate = np.zeros(6, dtype=float)
        cells = 0
        for y in range(y0, y1):
            for x in range(x0, x1):
                terrain_code = int(grid[y, x])
                prior = round_prior.terrain_probs.get(terrain_code, round_prior.global_class_probs)
                has_port = settlement_map.get((x, y))
                if has_port is not None:
                    settlement_prior = round_prior.settlement_probs.get(has_port)
                    if settlement_prior is not None:
                        prior = 0.5 * prior + 0.5 * settlement_prior
                aggregate += prior
                cells += 1
        if cells <= 0:
            continue
        round_vectors.append(aggregate / float(cells))
        round_weights.append(weight)
    if len(round_vectors) < 2:
        return 0.0
    weights = np.asarray(round_weights, dtype=float)
    weights /= weights.sum()
    mean_vector = np.zeros_like(round_vectors[0])
    for vector, weight in zip(round_vectors, weights, strict=True):
        mean_vector += vector * float(weight)
    disagreement = 0.0
    for vector, weight in zip(round_vectors, weights, strict=True):
        disagreement += float(weight) * float(np.abs(vector - mean_vector).sum())
    return disagreement


def _neighbors(x: int, y: int, width: int, height: int) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx = x + dx
        ny = y + dy
        if 0 <= nx < width and 0 <= ny < height:
            result.append((nx, ny))
    return result

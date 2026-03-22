from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from history_priors import HistoryPriorModel, infer_regime_history_prior_model
from observation_strategy import select_next_viewport_request


def load_cached_round_observations(root: Path, round_id: str, max_queries: int) -> dict[int, list[dict[str, Any]]]:
    observations_by_seed: dict[int, list[dict[str, Any]]] = {}
    sim_root = root / round_id / "team" / "simulations"
    if not sim_root.exists():
        return observations_by_seed
    total_loaded = 0
    for seed_dir in sorted(sim_root.glob("seed_*")):
        seed_index = int(seed_dir.name.split("_")[1])
        observations_by_seed[seed_index] = []
        for query_path in sorted(seed_dir.glob("query_*.json")):
            if total_loaded >= max_queries:
                break
            payload = json.loads(query_path.read_text())
            observations_by_seed[seed_index].append(payload["response"])
            total_loaded += 1
        if total_loaded >= max_queries:
            break
    return observations_by_seed


def synthesize_observations_from_analysis(
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
) -> dict[int, list[dict[str, Any]]]:
    observations_by_seed: dict[int, list[dict[str, Any]]] = {
        seed_index: [] for seed_index, _state in enumerate(round_detail["initial_states"])
    }
    analysis_by_seed: dict[int, dict[str, Any]] = {}
    for seed_index, _state in enumerate(round_detail["initial_states"]):
        analysis_path = root / cache_prefix / "rounds" / round_id / "team" / "analysis" / f"seed_{seed_index}.json"
        if analysis_path.exists():
            analysis_by_seed[seed_index] = json.loads(analysis_path.read_text())
    if not analysis_by_seed:
        return observations_by_seed

    seed_material = f"{round_id}:{random_state}".encode("utf-8")
    stable_seed = int(hashlib.sha256(seed_material).hexdigest()[:8], 16)
    rng = np.random.default_rng(stable_seed)
    planned_requests: dict[int, list[Any]] = {seed_index: [] for seed_index in observations_by_seed}
    for _ in range(total_queries):
        planning_history_prior_model = history_prior_model
        if planning_history_prior_model is not None and any(observations_by_seed.values()):
            planning_history_prior_model, _ = infer_regime_history_prior_model(
                history_prior_model=planning_history_prior_model,
                round_detail=round_detail,
                observations_by_seed=observations_by_seed,
            )
        selection = select_next_viewport_request(
            round_detail=round_detail,
            viewport_size=viewport_size,
            observations_by_seed=observations_by_seed,
            already_selected=planned_requests,
            history_prior_model=planning_history_prior_model,
            history_prior_strength=history_prior_strength,
            prior_strength=prior_strength,
            floor=floor,
        )
        if selection is None:
            break
        request = selection["request"]
        planned_requests[request.seed_index].append(request)
        analysis = analysis_by_seed.get(request.seed_index)
        if analysis is None:
            continue
        observations_by_seed[request.seed_index].append(
            synthesize_single_observation(
                analysis=analysis,
                seed_index=request.seed_index,
                viewport_x=request.viewport_x,
                viewport_y=request.viewport_y,
                viewport_w=request.viewport_w,
                viewport_h=request.viewport_h,
                rng=rng,
            )
        )
    return observations_by_seed


def synthesize_single_observation(
    *,
    analysis: dict[str, Any],
    seed_index: int,
    viewport_x: int,
    viewport_y: int,
    viewport_w: int,
    viewport_h: int,
    rng: np.random.Generator,
) -> dict[str, Any]:
    ground_truth = np.asarray(analysis["ground_truth"], dtype=float)
    initial_grid = np.asarray(analysis["initial_grid"], dtype=int)
    patch_truth = ground_truth[viewport_y : viewport_y + viewport_h, viewport_x : viewport_x + viewport_w]
    patch_initial = initial_grid[viewport_y : viewport_y + viewport_h, viewport_x : viewport_x + viewport_w]
    sampled_grid = np.zeros((viewport_h, viewport_w), dtype=int)
    for y in range(viewport_h):
        for x in range(viewport_w):
            sampled_class = int(rng.choice(np.arange(patch_truth.shape[-1]), p=patch_truth[y, x]))
            sampled_grid[y, x] = sampled_class_to_terrain_code(sampled_class, int(patch_initial[y, x]))
    return {
        "seed_index": seed_index,
        "grid": sampled_grid.tolist(),
        "settlements": [],
        "viewport": {"x": viewport_x, "y": viewport_y, "w": viewport_w, "h": viewport_h},
        "width": int(analysis["width"]),
        "height": int(analysis["height"]),
        "queries_used": None,
        "queries_max": 50,
    }


def sampled_class_to_terrain_code(class_index: int, initial_code: int) -> int:
    if class_index == 0:
        if initial_code in {0, 10, 11}:
            return int(initial_code)
        return 11
    return int(class_index)

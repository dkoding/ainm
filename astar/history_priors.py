from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from baseline import CLASS_COUNT
from history_cache import load_history_index


@dataclass(frozen=True)
class HistoryPriorModel:
    terrain_probs: dict[int, np.ndarray]
    terrain_counts: dict[int, int]
    settlement_probs: dict[bool, np.ndarray]
    settlement_counts: dict[bool, int]
    global_class_probs: np.ndarray
    rounds_used: int
    seeds_used: int
    cells_used: int

    def terrain_prior(self, terrain_code: int) -> np.ndarray | None:
        prior = self.terrain_probs.get(int(terrain_code))
        if prior is None:
            return None
        return prior.copy()

    def settlement_prior(self, has_port: bool) -> np.ndarray | None:
        prior = self.settlement_probs.get(bool(has_port))
        if prior is None:
            return None
        return prior.copy()

    def to_summary(self) -> dict[str, Any]:
        return {
            "rounds_used": self.rounds_used,
            "seeds_used": self.seeds_used,
            "cells_used": self.cells_used,
            "global_class_probs": self.global_class_probs.tolist(),
            "terrain_counts": {str(code): count for code, count in sorted(self.terrain_counts.items())},
            "settlement_counts": {("port" if key else "settlement"): count for key, count in sorted(self.settlement_counts.items())},
        }


def load_history_prior_model(
    root: str | Path,
    cache_prefix: str = "history",
    include_round_ids: set[str] | None = None,
    exclude_round_ids: set[str] | None = None,
) -> HistoryPriorModel | None:
    return build_history_prior_model(
        root=root,
        cache_prefix=cache_prefix,
        include_round_ids=include_round_ids,
        exclude_round_ids=exclude_round_ids,
    )


def build_history_prior_model(
    root: str | Path,
    cache_prefix: str = "history",
    include_round_ids: set[str] | None = None,
    exclude_round_ids: set[str] | None = None,
) -> HistoryPriorModel | None:
    index = load_history_index(root=root, cache_prefix=cache_prefix)
    if not index:
        return None

    root_path = Path(root)
    cache_root = root_path / cache_prefix / "rounds"
    terrain_totals: dict[int, np.ndarray] = {}
    terrain_counts: dict[int, int] = {}
    settlement_totals: dict[bool, np.ndarray] = {}
    settlement_counts: dict[bool, int] = {}
    global_totals = np.zeros(CLASS_COUNT, dtype=float)
    rounds_used = 0
    seeds_used = 0
    cells_used = 0

    for round_entry in index.get("rounds", []):
        round_id = str(round_entry["round_id"])
        if include_round_ids is not None and round_id not in include_round_ids:
            continue
        if exclude_round_ids is not None and round_id in exclude_round_ids:
            continue
        round_detail_path = cache_root / round_id / "public" / "round_detail.json"
        if not round_detail_path.exists():
            continue

        round_detail = json.loads(round_detail_path.read_text())
        states = round_detail.get("initial_states", [])
        round_used = False

        for seed_index in round_entry.get("analysis_cached_seeds", []):
            seed_idx = int(seed_index)
            if seed_idx >= len(states):
                continue
            analysis_path = cache_root / round_id / "team" / "analysis" / f"seed_{seed_idx}.json"
            if not analysis_path.exists():
                continue

            analysis = json.loads(analysis_path.read_text())
            initial_grid = np.asarray(analysis["initial_grid"], dtype=int)
            ground_truth = np.asarray(analysis["ground_truth"], dtype=float)
            if ground_truth.ndim != 3 or ground_truth.shape[-1] != CLASS_COUNT:
                continue

            state = states[seed_idx]
            settlement_map = {
                (int(settlement["x"]), int(settlement["y"])): bool(settlement.get("has_port"))
                for settlement in state.get("settlements", [])
            }

            height, width = initial_grid.shape
            if ground_truth.shape[:2] != (height, width):
                continue

            for y in range(height):
                for x in range(width):
                    terrain_code = int(initial_grid[y, x])
                    cell_truth = ground_truth[y, x]
                    global_totals += cell_truth
                    terrain_totals.setdefault(terrain_code, np.zeros(CLASS_COUNT, dtype=float))
                    terrain_totals[terrain_code] += cell_truth
                    terrain_counts[terrain_code] = terrain_counts.get(terrain_code, 0) + 1

                    has_port = settlement_map.get((x, y))
                    if has_port is not None:
                        settlement_totals.setdefault(has_port, np.zeros(CLASS_COUNT, dtype=float))
                        settlement_totals[has_port] += cell_truth
                        settlement_counts[has_port] = settlement_counts.get(has_port, 0) + 1

                    cells_used += 1

            seeds_used += 1
            round_used = True

        if round_used:
            rounds_used += 1

    if not terrain_totals:
        return None

    terrain_probs = {code: totals / totals.sum() for code, totals in terrain_totals.items() if totals.sum() > 0}
    settlement_probs = {key: totals / totals.sum() for key, totals in settlement_totals.items() if totals.sum() > 0}
    global_class_probs = global_totals / global_totals.sum()

    return HistoryPriorModel(
        terrain_probs=terrain_probs,
        terrain_counts=terrain_counts,
        settlement_probs=settlement_probs,
        settlement_counts=settlement_counts,
        global_class_probs=global_class_probs,
        rounds_used=rounds_used,
        seeds_used=seeds_used,
        cells_used=cells_used,
    )

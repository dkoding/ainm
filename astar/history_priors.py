from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from baseline import CLASS_COUNT, terrain_code_to_class_index
from history_cache import load_history_index


@dataclass(frozen=True)
class RoundPrior:
    round_id: str
    round_number: int
    terrain_probs: dict[int, np.ndarray]
    terrain_counts: dict[int, int]
    settlement_probs: dict[bool, np.ndarray]
    settlement_counts: dict[bool, int]
    global_class_probs: np.ndarray
    seeds_used: int
    cells_used: int


@dataclass(frozen=True)
class HistoryPriorModel:
    round_priors: tuple[RoundPrior, ...]
    round_weights: dict[str, float]
    rounds_used: int
    seeds_used: int
    cells_used: int

    @property
    def global_class_probs(self) -> np.ndarray:
        aggregate = np.zeros(CLASS_COUNT, dtype=float)
        total_weight = 0.0
        for round_prior in self.round_priors:
            weight = float(self.round_weights.get(round_prior.round_id, 0.0))
            if weight <= 0:
                continue
            aggregate += round_prior.global_class_probs * weight
            total_weight += weight
        if total_weight <= 0:
            return np.full(CLASS_COUNT, 1.0 / CLASS_COUNT, dtype=float)
        return aggregate / total_weight

    def terrain_prior(self, terrain_code: int) -> np.ndarray | None:
        aggregate = np.zeros(CLASS_COUNT, dtype=float)
        total_weight = 0.0
        for round_prior in self.round_priors:
            prior = round_prior.terrain_probs.get(int(terrain_code))
            if prior is None:
                continue
            weight = float(self.round_weights.get(round_prior.round_id, 0.0))
            if weight <= 0:
                continue
            aggregate += prior * weight
            total_weight += weight
        if total_weight <= 0:
            return None
        return (aggregate / total_weight).copy()

    def settlement_prior(self, has_port: bool) -> np.ndarray | None:
        aggregate = np.zeros(CLASS_COUNT, dtype=float)
        total_weight = 0.0
        for round_prior in self.round_priors:
            prior = round_prior.settlement_probs.get(bool(has_port))
            if prior is None:
                continue
            weight = float(self.round_weights.get(round_prior.round_id, 0.0))
            if weight <= 0:
                continue
            aggregate += prior * weight
            total_weight += weight
        if total_weight <= 0:
            return None
        return (aggregate / total_weight).copy()

    def with_round_weights(self, round_weights: dict[str, float]) -> "HistoryPriorModel":
        normalized = _normalize_round_weights(self.round_priors, round_weights)
        return HistoryPriorModel(
            round_priors=self.round_priors,
            round_weights=normalized,
            rounds_used=self.rounds_used,
            seeds_used=self.seeds_used,
            cells_used=self.cells_used,
        )

    def to_summary(self) -> dict[str, Any]:
        terrain_counts: dict[int, int] = {}
        settlement_counts: dict[bool, int] = {}
        for round_prior in self.round_priors:
            for code, count in round_prior.terrain_counts.items():
                terrain_counts[code] = terrain_counts.get(code, 0) + count
            for key, count in round_prior.settlement_counts.items():
                settlement_counts[key] = settlement_counts.get(key, 0) + count

        top_round_weights = sorted(
            (
                {
                    "round_id": round_prior.round_id,
                    "round_number": round_prior.round_number,
                    "weight": float(self.round_weights.get(round_prior.round_id, 0.0)),
                }
                for round_prior in self.round_priors
            ),
            key=lambda item: item["weight"],
            reverse=True,
        )

        return {
            "rounds_used": self.rounds_used,
            "seeds_used": self.seeds_used,
            "cells_used": self.cells_used,
            "global_class_probs": self.global_class_probs.tolist(),
            "terrain_counts": {str(code): count for code, count in sorted(terrain_counts.items())},
            "settlement_counts": {
                ("port" if key else "settlement"): count for key, count in sorted(settlement_counts.items())
            },
            "round_weights": [
                item
                for item in top_round_weights
                if item["weight"] > 0
            ],
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

    cache_root = Path(root) / cache_prefix / "rounds"
    round_priors: list[RoundPrior] = []
    total_seeds = 0
    total_cells = 0

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
        terrain_totals: dict[int, np.ndarray] = {}
        terrain_counts: dict[int, int] = {}
        settlement_totals: dict[bool, np.ndarray] = {}
        settlement_counts: dict[bool, int] = {}
        global_totals = np.zeros(CLASS_COUNT, dtype=float)
        seeds_used = 0
        cells_used = 0

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

        if seeds_used <= 0:
            continue

        total_seeds += seeds_used
        total_cells += cells_used
        round_priors.append(
            RoundPrior(
                round_id=round_id,
                round_number=int(round_entry.get("round_number", 0) or 0),
                terrain_probs={code: totals / totals.sum() for code, totals in terrain_totals.items() if totals.sum() > 0},
                terrain_counts=terrain_counts,
                settlement_probs={
                    key: totals / totals.sum() for key, totals in settlement_totals.items() if totals.sum() > 0
                },
                settlement_counts=settlement_counts,
                global_class_probs=global_totals / global_totals.sum(),
                seeds_used=seeds_used,
                cells_used=cells_used,
            )
        )

    if not round_priors:
        return None

    round_weights = _normalize_round_weights(tuple(round_priors), None)
    return HistoryPriorModel(
        round_priors=tuple(round_priors),
        round_weights=round_weights,
        rounds_used=len(round_priors),
        seeds_used=total_seeds,
        cells_used=total_cells,
    )


def infer_regime_history_prior_model(
    history_prior_model: HistoryPriorModel | None,
    round_detail: dict[str, Any],
    observations_by_seed: dict[int, list[dict[str, Any]]] | None,
    temperature: float = 0.35,
    uniform_mixture: float = 0.25,
) -> tuple[HistoryPriorModel | None, dict[str, Any] | None]:
    if history_prior_model is None:
        return None, None
    observations_by_seed = observations_by_seed or {}
    if not observations_by_seed:
        summary = {
            "observed_cells": 0,
            "round_weights": history_prior_model.to_summary().get("round_weights", []),
            "temperature": temperature,
            "uniform_mixture": uniform_mixture,
        }
        return history_prior_model, summary

    log_scores: dict[str, float] = {}
    observed_cells = 0
    states = round_detail.get("initial_states", [])
    settlement_maps = [
        {
            (int(settlement["x"]), int(settlement["y"])): bool(settlement.get("has_port"))
            for settlement in state.get("settlements", [])
        }
        for state in states
    ]

    for round_prior in history_prior_model.round_priors:
        total_log_prob = 0.0
        total_count = 0
        for seed_index, samples in observations_by_seed.items():
            if seed_index >= len(states):
                continue
            initial_grid = np.asarray(states[seed_index]["grid"], dtype=int)
            settlement_map = settlement_maps[seed_index]
            for sample in samples:
                viewport = sample["viewport"]
                sample_grid = np.asarray(sample["grid"], dtype=int)
                x0 = int(viewport["x"])
                y0 = int(viewport["y"])
                for dy in range(sample_grid.shape[0]):
                    for dx in range(sample_grid.shape[1]):
                        x = x0 + dx
                        y = y0 + dy
                        initial_code = int(initial_grid[y, x])
                        observed_class = terrain_code_to_class_index(int(sample_grid[dy, dx]))
                        prior = round_prior.terrain_probs.get(initial_code, round_prior.global_class_probs)
                        has_port = settlement_map.get((x, y))
                        if has_port is not None:
                            settlement_prior = round_prior.settlement_probs.get(has_port)
                            if settlement_prior is not None:
                                prior = 0.5 * prior + 0.5 * settlement_prior
                        total_log_prob += float(np.log(np.clip(prior[observed_class], 1e-6, 1.0)))
                        total_count += 1
        if total_count > 0:
            log_scores[round_prior.round_id] = total_log_prob / total_count
            observed_cells = total_count

    if not log_scores:
        return history_prior_model, None

    max_score = max(log_scores.values())
    scaled = {}
    for round_id, score in log_scores.items():
        scaled[round_id] = float(np.exp((score - max_score) / max(temperature, 1e-6)))
    total_scaled = sum(scaled.values())
    if total_scaled <= 0:
        return history_prior_model, None

    inferred = {round_id: value / total_scaled for round_id, value in scaled.items()}
    uniform_weight = 1.0 / len(history_prior_model.round_priors)
    mixed = {}
    for round_prior in history_prior_model.round_priors:
        inferred_weight = inferred.get(round_prior.round_id, 0.0)
        mixed[round_prior.round_id] = (1.0 - uniform_mixture) * inferred_weight + uniform_mixture * uniform_weight

    adjusted_model = history_prior_model.with_round_weights(mixed)
    summary = {
        "observed_cells": observed_cells,
        "temperature": temperature,
        "uniform_mixture": uniform_mixture,
        "round_weights": adjusted_model.to_summary().get("round_weights", []),
    }
    return adjusted_model, summary


def _normalize_round_weights(
    round_priors: tuple[RoundPrior, ...],
    round_weights: dict[str, float] | None,
) -> dict[str, float]:
    if not round_priors:
        return {}
    if not round_weights:
        uniform_weight = 1.0 / len(round_priors)
        return {round_prior.round_id: uniform_weight for round_prior in round_priors}

    cleaned = {str(round_id): max(float(weight), 0.0) for round_id, weight in round_weights.items()}
    total = sum(cleaned.get(round_prior.round_id, 0.0) for round_prior in round_priors)
    if total <= 0:
        uniform_weight = 1.0 / len(round_priors)
        return {round_prior.round_id: uniform_weight for round_prior in round_priors}
    return {round_prior.round_id: cleaned.get(round_prior.round_id, 0.0) / total for round_prior in round_priors}

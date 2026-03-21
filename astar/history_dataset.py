from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from feature_engineering import iter_state_feature_records
from history_cache import iter_cached_analysis_records
from scoring import entropy_weighted_kl


def iter_history_dataset_records(root: str | Path, cache_prefix: str = "history", neighborhood_radius: int = 1) -> Iterator[dict[str, Any]]:
    root_path = Path(root)
    for record in iter_cached_analysis_records(root=root_path, cache_prefix=cache_prefix):
        round_id = str(record["round_id"])
        seed_index = int(record["seed_index"])
        analysis = record["analysis"]
        round_detail_path = root_path / cache_prefix / "rounds" / round_id / "public" / "round_detail.json"
        if not round_detail_path.exists():
            continue
        round_detail = json.loads(round_detail_path.read_text())
        states = round_detail.get("initial_states", [])
        if seed_index >= len(states):
            continue
        state = states[seed_index]
        initial_grid = np.asarray(analysis["initial_grid"], dtype=int)
        ground_truth = np.asarray(analysis["ground_truth"], dtype=float)
        for feature_record in iter_state_feature_records(
            state=state,
            seed_index=seed_index,
            round_id=round_id,
            round_number=int(round_detail.get("round_number", 0) or 0),
            neighborhood_radius=neighborhood_radius,
        ):
            x = int(feature_record["x"])
            y = int(feature_record["y"])
            if initial_grid.shape[:2] != ground_truth.shape[:2]:
                continue
            target = ground_truth[y, x]
            positive = target > 0
            entropy_terms = np.zeros_like(target)
            entropy_terms[positive] = target[positive] * np.log(target[positive])
            target_entropy = float(-np.sum(entropy_terms))
            normalized_entropy = target_entropy / float(np.log(target.shape[-1])) if target.shape[-1] > 1 else 0.0
            yield {
                **feature_record,
                "terrain_entropy": target_entropy,
                "target_entropy": target_entropy,
                "entropy_sample_weight": float(0.15 + (1.85 * normalized_entropy)),
                "dynamic_cell": int(target_entropy >= 0.05),
                "target_argmax": int(np.argmax(target)),
                "target_probs": target.tolist(),
            }


def write_history_dataset(
    root: str | Path,
    output_path: str | Path,
    cache_prefix: str = "history",
    neighborhood_radius: int = 1,
) -> dict[str, Any]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    rounds: set[str] = set()
    seeds: set[tuple[str, int]] = set()
    with output.open("w", encoding="utf-8") as handle:
        for record in iter_history_dataset_records(root=root, cache_prefix=cache_prefix, neighborhood_radius=neighborhood_radius):
            rounds.add(record["round_id"])
            seeds.add((record["round_id"], int(record["seed_index"])))
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            count += 1
    return {
        "output_path": str(output),
        "records_written": count,
        "rounds": len(rounds),
        "seeds": len(seeds),
        "format": "jsonl",
        "neighborhood_radius": neighborhood_radius,
    }


def summarize_prediction_vs_truth(ground_truth: Any, prediction: Any) -> dict[str, Any]:
    ground = np.asarray(ground_truth, dtype=float)
    pred = np.asarray(prediction, dtype=float)
    return {
        "mean_abs_error": float(np.mean(np.abs(ground - pred))),
        "weighted_kl": float(entropy_weighted_kl(ground, pred)),
    }

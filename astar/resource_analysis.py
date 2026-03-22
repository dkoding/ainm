from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from baseline import terrain_code_to_class_index
from feature_engineering import iter_state_feature_records
from history_cache import history_round_entries_with_analysis, load_history_index


RESOURCE_KEYS = ("population", "food", "wealth", "defense")
OUTCOME_CLASS_NAMES = {
    0: "empty",
    1: "settlement",
    2: "port",
    3: "ruin",
    4: "forest",
    5: "mountain",
}


def analyze_resource_dynamics(
    *,
    root: str | Path = "artifacts",
    cache_prefix: str = "history",
    output_path: str | Path | None = None,
    include_round_ids: set[str] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    raw_settlement_records, window_records, coverage_summary = collect_resource_analysis_inputs(
        root=root_path,
        cache_prefix=cache_prefix,
        include_round_ids=include_round_ids,
    )
    unique_settlement_records, duplicate_summary = dedupe_settlement_observations(raw_settlement_records)
    report = build_resource_analysis_report(
        raw_settlement_records=raw_settlement_records,
        unique_settlement_records=unique_settlement_records,
        window_records=window_records,
        coverage_summary=coverage_summary,
        duplicate_summary=duplicate_summary,
    )
    output = Path(output_path) if output_path is not None else root_path / cache_prefix / "resource_analysis.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True))
    return report


def collect_resource_analysis_inputs(
    *,
    root: str | Path,
    cache_prefix: str = "history",
    include_round_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    root_path = Path(root)
    index = load_history_index(root=root_path, cache_prefix=cache_prefix)
    if not index:
        raise SystemExit(f"No history cache found under {root_path / cache_prefix}.")

    allowed_round_ids = {str(item) for item in include_round_ids} if include_round_ids is not None else None
    raw_settlement_records: list[dict[str, Any]] = []
    window_records: list[dict[str, Any]] = []
    rounds_considered = 0
    rounds_with_simulations = 0
    seeds_with_simulations = 0
    simulation_files = 0

    for round_entry in history_round_entries_with_analysis(index):
        round_id = str(round_entry.get("round_id"))
        if allowed_round_ids is not None and round_id not in allowed_round_ids:
            continue
        rounds_considered += 1
        simulations_root = root_path / round_id / "team" / "simulations"
        if not simulations_root.exists():
            continue

        round_detail = _load_round_detail(root=root_path, round_id=round_id, cache_prefix=cache_prefix)
        round_number = int(round_entry.get("round_number", 0) or 0)
        round_had_simulations = False
        for seed_index in round_entry.get("analysis_cached_seeds", []):
            seed_idx = int(seed_index)
            simulation_paths = sorted((simulations_root / f"seed_{seed_idx}").glob("query_*.json"))
            if not simulation_paths:
                continue
            round_had_simulations = True
            seeds_with_simulations += 1
            simulation_files += len(simulation_paths)

            analysis = _load_analysis(root=root_path, round_id=round_id, seed_index=seed_idx, cache_prefix=cache_prefix)
            ground_truth = np.asarray(analysis["ground_truth"], dtype=float)
            initial_grid = np.asarray(analysis["initial_grid"], dtype=int)
            state = round_detail["initial_states"][seed_idx]
            feature_lookup = {
                (int(record["x"]), int(record["y"])): record
                for record in iter_state_feature_records(
                    state=state,
                    seed_index=seed_idx,
                    round_id=round_id,
                    round_number=round_number,
                )
            }

            for query_path in simulation_paths:
                payload = json.loads(query_path.read_text())
                response = _unwrap_simulation_payload(payload)
                viewport = response.get("viewport") or {}
                viewport_x = int(viewport.get("x", 0))
                viewport_y = int(viewport.get("y", 0))
                viewport_w = int(viewport.get("w", 0))
                viewport_h = int(viewport.get("h", 0))
                if viewport_w <= 0 or viewport_h <= 0:
                    continue
                query_index = _query_index_from_path(query_path)
                settlements = list(response.get("settlements", []))
                grid = np.asarray(response.get("grid", []), dtype=int)
                if grid.size == 0:
                    continue
                window_truth = ground_truth[viewport_y : viewport_y + viewport_h, viewport_x : viewport_x + viewport_w]
                if window_truth.shape[:2] != (viewport_h, viewport_w):
                    continue
                window_records.append(
                    _build_window_record(
                        round_id=round_id,
                        round_number=round_number,
                        seed_index=seed_idx,
                        query_index=query_index,
                        viewport=viewport,
                        grid=grid,
                        settlements=settlements,
                        window_truth=window_truth,
                    )
                )

                for settlement in settlements:
                    x = int(settlement["x"])
                    y = int(settlement["y"])
                    if y < 0 or y >= ground_truth.shape[0] or x < 0 or x >= ground_truth.shape[1]:
                        continue
                    feature_record = feature_lookup.get((x, y), {})
                    truth = ground_truth[y, x]
                    raw_settlement_records.append(
                        _build_settlement_record(
                            round_id=round_id,
                            round_number=round_number,
                            seed_index=seed_idx,
                            query_index=query_index,
                            viewport=viewport,
                            settlement=settlement,
                            initial_grid=initial_grid,
                            truth=truth,
                            neighborhood_truth=ground_truth[
                                max(0, y - 2) : min(ground_truth.shape[0], y + 3),
                                max(0, x - 2) : min(ground_truth.shape[1], x + 3),
                            ],
                            feature_record=feature_record,
                        )
                    )
        if round_had_simulations:
            rounds_with_simulations += 1

    coverage_summary = {
        "rounds_considered": rounds_considered,
        "rounds_with_simulations": rounds_with_simulations,
        "seeds_with_simulations": seeds_with_simulations,
        "simulation_files": simulation_files,
    }
    return raw_settlement_records, window_records, coverage_summary


def dedupe_settlement_observations(
    raw_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[tuple[str, int, int, int], list[dict[str, Any]]] = {}
    for record in raw_records:
        key = (
            str(record["round_id"]),
            int(record["seed_index"]),
            int(record["x"]),
            int(record["y"]),
        )
        grouped.setdefault(key, []).append(record)

    unique_records: list[dict[str, Any]] = []
    repeat_groups: list[list[dict[str, Any]]] = []
    for group in grouped.values():
        ordered_group = sorted(group, key=lambda item: int(item["query_index"]))
        representative = dict(group[0])
        representative["observation_count"] = len(group)
        representative["query_indices"] = [int(item["query_index"]) for item in ordered_group]
        representative["query_span"] = (
            int(ordered_group[-1]["query_index"]) - int(ordered_group[0]["query_index"])
            if len(ordered_group) > 1
            else 0
        )
        for resource_key in RESOURCE_KEYS:
            values = np.asarray([float(item[resource_key]) for item in ordered_group], dtype=float)
            representative[resource_key] = float(values.mean())
            representative[f"{resource_key}_std"] = float(values.std())
            representative[f"{resource_key}_delta_first_last"] = float(values[-1] - values[0]) if len(values) > 1 else 0.0
        unique_records.append(representative)
        if len(ordered_group) > 1:
            repeat_groups.append(ordered_group)

    duplicate_summary = {
        "raw_settlement_observations": len(raw_records),
        "unique_settlements": len(unique_records),
        "duplicate_observations": max(0, len(raw_records) - len(unique_records)),
        "repeated_unique_settlements": len(repeat_groups),
        "repeat_stability": {
            resource_key: {
                "mean_std": float(
                    np.mean(
                        [
                            np.std([float(item[resource_key]) for item in group], dtype=float)
                            for group in repeat_groups
                        ]
                    )
                )
                if repeat_groups
                else 0.0,
                "max_std": float(
                    np.max(
                        [
                            np.std([float(item[resource_key]) for item in group], dtype=float)
                            for group in repeat_groups
                        ]
                    )
                )
                if repeat_groups
                else 0.0,
            }
            for resource_key in RESOURCE_KEYS
        },
    }
    return unique_records, duplicate_summary


def build_resource_analysis_report(
    *,
    raw_settlement_records: list[dict[str, Any]],
    unique_settlement_records: list[dict[str, Any]],
    window_records: list[dict[str, Any]],
    coverage_summary: dict[str, Any],
    duplicate_summary: dict[str, Any],
) -> dict[str, Any]:
    settlement_contexts = {
        "all": unique_settlement_records,
        "coastal": [item for item in unique_settlement_records if int(item.get("coast_adjacent", 0)) == 1],
        "inland": [item for item in unique_settlement_records if int(item.get("coast_adjacent", 0)) == 0],
        "observed_ports": [item for item in unique_settlement_records if bool(item.get("has_port"))],
        "observed_non_ports": [item for item in unique_settlement_records if not bool(item.get("has_port"))],
        "alive": [item for item in unique_settlement_records if bool(item.get("alive"))],
        "collapsed": [item for item in unique_settlement_records if not bool(item.get("alive"))],
    }
    settlement_effects = {
        context_name: _build_resource_effects(records, value_keys=RESOURCE_KEYS)
        for context_name, records in settlement_contexts.items()
        if records
    }

    windows_with_settlements = [item for item in window_records if int(item.get("settlement_count", 0)) > 0]
    window_effects = {
        "all_windows_with_settlements": _build_resource_effects(
            windows_with_settlements,
            value_keys=tuple(f"mean_{resource_key}" for resource_key in RESOURCE_KEYS),
            metric_keys=("final_viewport_dynamic_mass", "final_viewport_port_mass", "final_viewport_ruin_mass"),
        )
        if windows_with_settlements
        else {}
    }

    return {
        "coverage": coverage_summary,
        "duplicate_summary": duplicate_summary,
        "resource_ranges": {
            resource_key: _value_range(unique_settlement_records, resource_key)
            for resource_key in RESOURCE_KEYS
        },
        "settlement_resource_effects": settlement_effects,
        "window_resource_effects": window_effects,
        "repeat_progression": _repeat_progression_summary(unique_settlement_records),
        "top_findings": _top_findings(settlement_effects, window_effects),
    }


def _build_settlement_record(
    *,
    round_id: str,
    round_number: int,
    seed_index: int,
    query_index: int,
    viewport: dict[str, Any],
    settlement: dict[str, Any],
    initial_grid: np.ndarray,
    truth: np.ndarray,
    neighborhood_truth: np.ndarray,
    feature_record: dict[str, Any],
) -> dict[str, Any]:
    x = int(settlement["x"])
    y = int(settlement["y"])
    truth = np.asarray(truth, dtype=float)
    neighborhood_truth = np.asarray(neighborhood_truth, dtype=float)
    final_class_index = int(np.argmax(truth))
    local_dynamic_mass = float(neighborhood_truth[:, :, 1:4].sum() / max(neighborhood_truth.shape[0] * neighborhood_truth.shape[1], 1))
    local_port_mass = float(neighborhood_truth[:, :, 2].mean())
    local_ruin_mass = float(neighborhood_truth[:, :, 3].mean())
    return {
        "round_id": round_id,
        "round_number": int(round_number),
        "seed_index": int(seed_index),
        "query_index": int(query_index),
        "viewport_x": int(viewport["x"]),
        "viewport_y": int(viewport["y"]),
        "viewport_w": int(viewport["w"]),
        "viewport_h": int(viewport["h"]),
        "x": x,
        "y": y,
        "population": float(settlement.get("population", 0.0) or 0.0),
        "food": float(settlement.get("food", 0.0) or 0.0),
        "wealth": float(settlement.get("wealth", 0.0) or 0.0),
        "defense": float(settlement.get("defense", 0.0) or 0.0),
        "alive": bool(settlement.get("alive", True)),
        "has_port": bool(settlement.get("has_port", False)),
        "owner_id": settlement.get("owner_id"),
        "initial_terrain_code": int(initial_grid[y, x]),
        "initial_class_index": int(terrain_code_to_class_index(int(initial_grid[y, x]))),
        "coast_adjacent": int(feature_record.get("coast_adjacent", 0)),
        "terrain_edge_count": int(feature_record.get("terrain_edge_count", 0)),
        "nearest_settlement_distance": float(feature_record.get("nearest_settlement_distance", 0.0)),
        "nearest_port_distance": float(feature_record.get("nearest_port_distance", 0.0)),
        "same_landmass_settlement_count": int(feature_record.get("same_landmass_settlement_count", 0)),
        "same_landmass_port_count": int(feature_record.get("same_landmass_port_count", 0)),
        "final_class_index": final_class_index,
        "final_class_name": OUTCOME_CLASS_NAMES.get(final_class_index, str(final_class_index)),
        "final_settlement_prob": float(truth[1]),
        "final_port_prob": float(truth[2]),
        "final_ruin_prob": float(truth[3]),
        "final_dynamic_mass": float(truth[1:4].sum()),
        "final_is_dynamic": int(final_class_index in {1, 2, 3}),
        "final_is_settlement": int(final_class_index == 1),
        "final_is_port": int(final_class_index == 2),
        "final_is_ruin": int(final_class_index == 3),
        "local_dynamic_mass_radius2": local_dynamic_mass,
        "local_port_mass_radius2": local_port_mass,
        "local_ruin_mass_radius2": local_ruin_mass,
    }


def _build_window_record(
    *,
    round_id: str,
    round_number: int,
    seed_index: int,
    query_index: int,
    viewport: dict[str, Any],
    grid: np.ndarray,
    settlements: list[dict[str, Any]],
    window_truth: np.ndarray,
) -> dict[str, Any]:
    class_counts = np.zeros(6, dtype=float)
    for value in np.asarray(grid, dtype=int).ravel():
        class_counts[terrain_code_to_class_index(int(value))] += 1.0
    class_probs = class_counts / max(float(class_counts.sum()), 1.0)
    populations = [float(item.get("population", 0.0) or 0.0) for item in settlements]
    foods = [float(item.get("food", 0.0) or 0.0) for item in settlements]
    wealths = [float(item.get("wealth", 0.0) or 0.0) for item in settlements]
    defenses = [float(item.get("defense", 0.0) or 0.0) for item in settlements]
    alive_ratio = (
        float(sum(1 for item in settlements if item.get("alive", True)) / len(settlements))
        if settlements
        else 0.0
    )
    port_ratio = (
        float(sum(1 for item in settlements if item.get("has_port", False)) / len(settlements))
        if settlements
        else 0.0
    )
    owners = {item.get("owner_id") for item in settlements if item.get("owner_id") is not None}
    owner_diversity = float(len(owners) / len(settlements)) if settlements else 0.0
    return {
        "round_id": round_id,
        "round_number": int(round_number),
        "seed_index": int(seed_index),
        "query_index": int(query_index),
        "viewport_x": int(viewport["x"]),
        "viewport_y": int(viewport["y"]),
        "viewport_w": int(viewport["w"]),
        "viewport_h": int(viewport["h"]),
        "settlement_count": int(len(settlements)),
        "port_ratio": port_ratio,
        "alive_ratio": alive_ratio,
        "owner_diversity": owner_diversity,
        "mean_population": float(np.mean(populations)) if populations else 0.0,
        "mean_food": float(np.mean(foods)) if foods else 0.0,
        "mean_wealth": float(np.mean(wealths)) if wealths else 0.0,
        "mean_defense": float(np.mean(defenses)) if defenses else 0.0,
        "observed_class_prob_empty": float(class_probs[0]),
        "observed_class_prob_settlement": float(class_probs[1]),
        "observed_class_prob_port": float(class_probs[2]),
        "observed_class_prob_ruin": float(class_probs[3]),
        "final_viewport_dynamic_mass": float(window_truth[:, :, 1:4].sum() / max(window_truth.shape[0] * window_truth.shape[1], 1)),
        "final_viewport_port_mass": float(window_truth[:, :, 2].mean()),
        "final_viewport_ruin_mass": float(window_truth[:, :, 3].mean()),
    }


def _build_resource_effects(
    records: list[dict[str, Any]],
    *,
    value_keys: tuple[str, ...],
    metric_keys: tuple[str, ...] = (
        "final_is_settlement",
        "final_is_port",
        "final_is_ruin",
        "final_is_dynamic",
        "local_dynamic_mass_radius2",
        "local_port_mass_radius2",
        "local_ruin_mass_radius2",
    ),
) -> dict[str, Any]:
    if len(records) < 8:
        return {}
    summary: dict[str, Any] = {}
    for value_key in value_keys:
        sorted_records = sorted(records, key=lambda item: float(item.get(value_key, 0.0)))
        bucket_size = max(2, len(sorted_records) // 4)
        low_records = sorted_records[:bucket_size]
        high_records = sorted_records[-bucket_size:]
        low_metrics = _mean_metrics(low_records, metric_keys)
        high_metrics = _mean_metrics(high_records, metric_keys)
        summary[value_key] = {
            "count": len(sorted_records),
            "bucket_size": bucket_size,
            "low_mean_value": float(np.mean([float(item.get(value_key, 0.0)) for item in low_records])),
            "high_mean_value": float(np.mean([float(item.get(value_key, 0.0)) for item in high_records])),
            "low_metrics": low_metrics,
            "high_metrics": high_metrics,
            "delta_metrics": {
                metric_key: float(high_metrics[metric_key] - low_metrics[metric_key]) for metric_key in metric_keys
            },
        }
    return summary


def _mean_metrics(records: list[dict[str, Any]], metric_keys: tuple[str, ...]) -> dict[str, float]:
    return {
        metric_key: float(np.mean([float(item.get(metric_key, 0.0)) for item in records]))
        for metric_key in metric_keys
    }


def _top_findings(
    settlement_effects: dict[str, Any],
    window_effects: dict[str, Any],
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for context_name, effect_summary in settlement_effects.items():
        for resource_key, resource_summary in effect_summary.items():
            for metric_key, delta in resource_summary.get("delta_metrics", {}).items():
                findings.append(
                    {
                        "scope": "settlement",
                        "context": context_name,
                        "resource": resource_key,
                        "metric": metric_key,
                        "delta": float(delta),
                        "low_mean_value": float(resource_summary.get("low_mean_value", 0.0)),
                        "high_mean_value": float(resource_summary.get("high_mean_value", 0.0)),
                    }
                )
    for context_name, effect_summary in window_effects.items():
        for resource_key, resource_summary in effect_summary.items():
            for metric_key, delta in resource_summary.get("delta_metrics", {}).items():
                findings.append(
                    {
                        "scope": "window",
                        "context": context_name,
                        "resource": resource_key,
                        "metric": metric_key,
                        "delta": float(delta),
                        "low_mean_value": float(resource_summary.get("low_mean_value", 0.0)),
                        "high_mean_value": float(resource_summary.get("high_mean_value", 0.0)),
                    }
                )
    findings.sort(key=lambda item: abs(float(item["delta"])), reverse=True)
    return findings[:limit]


def _repeat_progression_summary(unique_settlement_records: list[dict[str, Any]]) -> dict[str, Any]:
    repeated_records = [item for item in unique_settlement_records if int(item.get("observation_count", 0)) > 1]
    if not repeated_records:
        return {
            "repeated_unique_settlements": 0,
            "resource_progression": {},
            "top_dynamic_gaps": [],
        }

    resource_progression: dict[str, Any] = {}
    dynamic_gap_candidates: list[dict[str, Any]] = []
    for resource_key in RESOURCE_KEYS:
        delta_key = f"{resource_key}_delta_first_last"
        deltas = np.asarray([float(item.get(delta_key, 0.0)) for item in repeated_records], dtype=float)
        dynamic_records = [item for item in repeated_records if int(item.get("final_is_dynamic", 0)) == 1]
        static_records = [item for item in repeated_records if int(item.get("final_is_dynamic", 0)) == 0]
        dynamic_mean = (
            float(np.mean([float(item.get(delta_key, 0.0)) for item in dynamic_records]))
            if dynamic_records
            else 0.0
        )
        static_mean = (
            float(np.mean([float(item.get(delta_key, 0.0)) for item in static_records]))
            if static_records
            else 0.0
        )
        resource_progression[resource_key] = {
            "mean_delta_first_last": float(deltas.mean()),
            "mean_abs_delta_first_last": float(np.mean(np.abs(deltas))),
            "dynamic_mean_delta_first_last": dynamic_mean,
            "static_mean_delta_first_last": static_mean,
            "dynamic_gap": float(dynamic_mean - static_mean),
        }
        dynamic_gap_candidates.append(
            {
                "resource": resource_key,
                "dynamic_gap": float(dynamic_mean - static_mean),
                "dynamic_mean_delta_first_last": dynamic_mean,
                "static_mean_delta_first_last": static_mean,
            }
        )
    dynamic_gap_candidates.sort(key=lambda item: abs(float(item["dynamic_gap"])), reverse=True)
    return {
        "repeated_unique_settlements": len(repeated_records),
        "resource_progression": resource_progression,
        "top_dynamic_gaps": dynamic_gap_candidates,
    }


def _value_range(records: list[dict[str, Any]], key: str) -> dict[str, float]:
    if not records:
        return {"min": 0.0, "mean": 0.0, "max": 0.0}
    values = np.asarray([float(item.get(key, 0.0)) for item in records], dtype=float)
    return {
        "min": float(values.min()),
        "mean": float(values.mean()),
        "max": float(values.max()),
    }


def _load_round_detail(*, root: Path, round_id: str, cache_prefix: str) -> dict[str, Any]:
    for path in (
        root / round_id / "public" / "round_detail.json",
        root / cache_prefix / "rounds" / round_id / "public" / "round_detail.json",
    ):
        if path.exists():
            return json.loads(path.read_text())
    raise FileNotFoundError(f"Missing round_detail.json for round {round_id}.")


def _load_analysis(*, root: Path, round_id: str, seed_index: int, cache_prefix: str) -> dict[str, Any]:
    for path in (
        root / cache_prefix / "rounds" / round_id / "team" / "analysis" / f"seed_{seed_index}.json",
        root / round_id / "team" / "analysis" / f"seed_{seed_index}.json",
    ):
        if path.exists():
            return json.loads(path.read_text())
    raise FileNotFoundError(f"Missing analysis for round {round_id} seed {seed_index}.")


def _unwrap_simulation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    response = payload.get("response")
    if isinstance(response, dict):
        return response
    return payload


def _query_index_from_path(path: Path) -> int:
    stem = path.stem
    if stem.startswith("query_"):
        try:
            return int(stem.split("_", 1)[1])
        except ValueError:
            return 0
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze observed settlement resources against cached ground truth.")
    parser.add_argument("--out-dir", default="artifacts", help="Root artifact directory.")
    parser.add_argument("--cache-prefix", default="history", help="History cache directory under --out-dir.")
    parser.add_argument("--output", default=None, help="Optional explicit output path.")
    parser.add_argument(
        "--round-id",
        action="append",
        dest="round_ids",
        default=None,
        help="Restrict analysis to one or more round ids.",
    )
    args = parser.parse_args()
    report = analyze_resource_dynamics(
        root=args.out_dir,
        cache_prefix=args.cache_prefix,
        output_path=args.output,
        include_round_ids=set(args.round_ids or []) or None,
    )
    print(json.dumps(report.get("coverage", {}), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

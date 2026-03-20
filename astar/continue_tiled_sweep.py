from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from artifacts import ArtifactStore
from astar_client import AstarClient
from baseline import apply_probability_floor, blend_observations
from config import (
    DEFAULT_AINM_BASE_URL,
    DEFAULT_HISTORY_CACHE_PREFIX,
    DEFAULT_OBSERVATION_PRIOR_STRENGTH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PREDICTION_FLOOR,
    DEFAULT_VIEWPORT_SIZE,
    AstarSettings,
)
from history_cache import summarize_history_cache
from observation_strategy import ViewportRequest, build_seed_tiled_sweep_requests
from reporting import build_run_report
from resume_round import load_cached_simulations
from sklearn_model import build_round_predictions_from_model, load_model_artifact, train_random_forest_from_history
from validation import validate_prediction_array


def parse_args() -> argparse.Namespace:
    secrets = AstarSettings.from_env()
    parser = argparse.ArgumentParser(description="Continue a tiled full-map sweep on an active round using remaining budget.")
    parser.add_argument("--round-id", required=True, help="Active round ID.")
    parser.add_argument("--token", default=secrets.access_token, help="AINM access_token JWT.")
    parser.add_argument("--base-url", default=DEFAULT_AINM_BASE_URL, help="API base URL.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR), help="Artifact root containing the round.")
    parser.add_argument("--viewport-size", type=int, default=DEFAULT_VIEWPORT_SIZE, help="Viewport size used for tiling.")
    parser.add_argument("--max-queries", type=int, help="Optional explicit cap on additional queries to spend.")
    parser.add_argument("--floor", type=float, default=DEFAULT_PREDICTION_FLOOR, help="Prediction floor.")
    parser.add_argument("--prior-strength", type=float, default=DEFAULT_OBSERVATION_PRIOR_STRENGTH, help="Observation prior strength.")
    parser.add_argument("--history-cache-prefix", default=DEFAULT_HISTORY_CACHE_PREFIX, help="Relative cache directory inside --out-dir.")
    parser.add_argument("--model-path", help="Optional explicit sklearn model path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.token:
        raise SystemExit("--token or AINM_ACCESS_TOKEN is required.")

    client = AstarClient(token=args.token, base_url=args.base_url)
    artifact_store = ArtifactStore(root=args.out_dir)
    round_root = Path(args.round_id)

    rounds = client.get_rounds()
    round_detail = client.get_round_detail(args.round_id)
    budget_before = client.get_budget()
    if not budget_before.get("active"):
        raise SystemExit(f"Round {args.round_id} is not active.")

    observations_by_seed = load_cached_simulations(root=Path(args.out_dir), round_id=args.round_id)
    planned_requests = plan_additional_sweep_requests(
        round_detail=round_detail,
        observations_by_seed=observations_by_seed,
        viewport_size=args.viewport_size,
        remaining_budget=remaining_budget(budget_before, args.max_queries),
    )
    if not planned_requests:
        print("No additional tiled sweep requests are needed.")
        return

    plan_payload = {
        str(seed_index): [request.to_payload(args.round_id) for request in requests]
        for seed_index, requests in planned_requests.items()
        if requests
    }
    artifact_store.write_json(round_root / "team" / "continue_tiled_sweep_plan.json", plan_payload)

    for seed_index, requests in planned_requests.items():
        existing_count = len(observations_by_seed.get(seed_index, []))
        observations_by_seed.setdefault(seed_index, [])
        for offset, request in enumerate(requests):
            payload = request.to_payload(args.round_id)
            response = client.simulate(payload)
            observations_by_seed[seed_index].append(response)
            artifact_store.write_json(
                round_root / "team" / "simulations" / f"seed_{seed_index}" / f"query_{existing_count + offset:02d}.json",
                {"request": payload, "response": response},
            )
            print(
                f"seed {seed_index}: simulated viewport "
                f"({payload['viewport_x']},{payload['viewport_y']}) "
                f"{payload['viewport_w']}x{payload['viewport_h']}"
            )

    budget_after = client.get_budget()
    model_artifact = load_or_train_model(out_dir=args.out_dir, model_path=args.model_path, cache_prefix=args.history_cache_prefix)
    predictions = build_round_predictions_from_model(artifact=model_artifact, round_detail=round_detail, floor=args.floor)
    predictions = blend_predictions_with_observations(
        predictions=predictions,
        observations_by_seed=observations_by_seed,
        prior_strength=args.prior_strength,
        floor=args.floor,
        floor_distribution=model_artifact.floor_distribution,
    )

    for seed_index, prediction in enumerate(predictions):
        validate_prediction_array(
            prediction,
            expected_height=int(round_detail["map_height"]),
            expected_width=int(round_detail["map_width"]),
        )
        artifact_store.write_json(
            round_root / "predictions" / f"seed_{seed_index}.json",
            {"round_id": args.round_id, "seed_index": seed_index, "prediction": prediction.tolist()},
        )
        print(f"seed {seed_index}: wrote updated prediction")

    history_summary = summarize_history_cache(root=args.out_dir, cache_prefix=args.history_cache_prefix)
    report = build_run_report(
        round_id=args.round_id,
        round_detail=round_detail,
        rounds=rounds,
        predictions=predictions,
        simulate_enabled=True,
        submit_enabled=False,
        total_queries_requested=sum(len(items) for items in planned_requests.values()),
        viewport_size=args.viewport_size,
        floor=args.floor,
        prior_strength=args.prior_strength,
        query_plan_summary={
            "continue_tiled_sweep": True,
            "per_seed_queries_planned": {str(seed_index): len(items) for seed_index, items in planned_requests.items()},
            "total_queries_planned": sum(len(items) for items in planned_requests.values()),
        },
        history_summary=history_summary,
        history_prior_summary=None,
        prediction_model="sklearn",
        sklearn_training_summary=model_artifact.to_metadata(),
        sklearn_evaluation_summary=None,
        observation_plan=plan_payload,
        observations_by_seed=observations_by_seed,
        budget_before=budget_before,
        budget_after=budget_after,
    )
    artifact_store.write_json(round_root / "report_continue_tiled_sweep.json", report)


def remaining_budget(budget: dict[str, Any], max_queries: int | None) -> int:
    available = int(budget["queries_max"]) - int(budget["queries_used"])
    if max_queries is None:
        return max(0, available)
    return max(0, min(available, int(max_queries)))


def plan_additional_sweep_requests(
    *,
    round_detail: dict[str, Any],
    observations_by_seed: dict[int, list[dict[str, Any]]],
    viewport_size: int,
    remaining_budget: int,
) -> dict[int, list[ViewportRequest]]:
    plan: dict[int, list[ViewportRequest]] = {seed_index: [] for seed_index in range(int(round_detail["seeds_count"]))}
    if remaining_budget <= 0:
        return plan

    covered_cells_by_seed = current_covered_cells(observations_by_seed)
    candidates_by_seed = {
        seed_index: build_seed_tiled_sweep_requests(
            seed_index=seed_index,
            map_width=int(round_detail["map_width"]),
            map_height=int(round_detail["map_height"]),
            viewport_size=viewport_size,
        )
        for seed_index in range(int(round_detail["seeds_count"]))
    }
    total_cells = int(round_detail["map_width"]) * int(round_detail["map_height"])

    while remaining_budget > 0:
        best_score: tuple[int, int, int, int, int, int] | None = None
        best_request: ViewportRequest | None = None
        for seed_index, requests in candidates_by_seed.items():
            covered = covered_cells_by_seed.get(seed_index, set())
            deficit = total_cells - len(covered)
            if deficit <= 0:
                continue
            for request in requests:
                additional = uncovered_cell_count(request, covered)
                if additional <= 0:
                    continue
                score = (
                    additional,
                    deficit,
                    -seed_index,
                    -request.viewport_y,
                    -request.viewport_x,
                    request.viewport_w * request.viewport_h,
                )
                if best_score is None or score > best_score:
                    best_score = score
                    best_request = request

        if best_request is None:
            break

        seed_index = int(best_request.seed_index)
        plan[seed_index].append(best_request)
        covered_cells_by_seed.setdefault(seed_index, set()).update(iter_request_cells(best_request))
        remaining_budget -= 1
        if all_seed_cells_covered(round_detail, covered_cells_by_seed):
            break

    return plan


def current_covered_cells(observations_by_seed: dict[int, list[dict[str, Any]]]) -> dict[int, set[tuple[int, int]]]:
    covered: dict[int, set[tuple[int, int]]] = {}
    for seed_index, observations in observations_by_seed.items():
        seed_cells: set[tuple[int, int]] = set()
        for sample in observations:
            viewport = sample["viewport"]
            request = ViewportRequest(
                seed_index=seed_index,
                viewport_x=int(viewport["x"]),
                viewport_y=int(viewport["y"]),
                viewport_w=int(viewport["w"]),
                viewport_h=int(viewport["h"]),
            )
            seed_cells.update(iter_request_cells(request))
        covered[seed_index] = seed_cells
    return covered


def uncovered_cell_count(request: ViewportRequest, covered_cells: set[tuple[int, int]]) -> int:
    return sum(1 for cell in iter_request_cells(request) if cell not in covered_cells)


def iter_request_cells(request: ViewportRequest) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y in range(request.viewport_y, request.viewport_y + request.viewport_h)
        for x in range(request.viewport_x, request.viewport_x + request.viewport_w)
    ]


def all_seed_cells_covered(round_detail: dict[str, Any], covered_cells_by_seed: dict[int, set[tuple[int, int]]]) -> bool:
    target = int(round_detail["map_width"]) * int(round_detail["map_height"])
    return all(len(covered_cells_by_seed.get(seed_index, set())) >= target for seed_index in range(int(round_detail["seeds_count"])))


def load_or_train_model(out_dir: str, model_path: str | None, cache_prefix: str) -> Any:
    path = Path(model_path) if model_path else Path(out_dir) / "models" / "astar_random_forest.pkl"
    if path.exists():
        return load_model_artifact(path)
    artifact = train_random_forest_from_history(root=out_dir, cache_prefix=cache_prefix)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        import pickle

        pickle.dump(artifact, handle)
    return artifact


def blend_predictions_with_observations(
    *,
    predictions: list[Any],
    observations_by_seed: dict[int, list[dict[str, Any]]],
    prior_strength: float,
    floor: float,
    floor_distribution: Any,
) -> list[Any]:
    blended_predictions = []
    for seed_index, prediction in enumerate(predictions):
        observation_samples = observations_by_seed.get(seed_index, [])
        if observation_samples:
            prediction = blend_observations(prediction, observation_samples, prior_strength=prior_strength)
            prediction = apply_probability_floor(prediction, floor=floor, floor_distribution=floor_distribution)
        blended_predictions.append(prediction)
    return blended_predictions


if __name__ == "__main__":
    main()

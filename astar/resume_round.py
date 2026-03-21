from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from artifacts import ArtifactStore
from astar_client import AstarAPIError, AstarClient
from baseline import build_round_predictions
from config import (
    DEFAULT_AINM_BASE_URL,
    DEFAULT_HISTORY_CACHE_PREFIX,
    DEFAULT_HISTORY_PRIOR_STRENGTH,
    DEFAULT_OBSERVATION_PRIOR_STRENGTH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PREDICTION_FLOOR,
    DEFAULT_SUBMIT,
    DEFAULT_VIEWPORT_SIZE,
    AstarSettings,
)
from history_cache import summarize_history_cache
from history_priors import load_history_prior_model
from reporting import build_run_report
from validation import validate_prediction_array, validate_submission_payload


def parse_args() -> argparse.Namespace:
    secrets = AstarSettings.from_env()
    parser = argparse.ArgumentParser(description="Resume an interrupted round from cached simulation artifacts.")
    parser.add_argument("--round-id", required=True, help="Round ID to resume.")
    parser.add_argument("--token", default=secrets.access_token, help="AINM access_token JWT.")
    parser.add_argument("--base-url", default=DEFAULT_AINM_BASE_URL, help="API base URL.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR), help="Artifact root containing the interrupted round.")
    parser.add_argument("--history-cache-prefix", default=DEFAULT_HISTORY_CACHE_PREFIX, help="Relative cache directory inside --out-dir.")
    parser.add_argument("--submit", action=argparse.BooleanOptionalAction, default=DEFAULT_SUBMIT, help="Submit rebuilt predictions.")
    parser.add_argument("--floor", type=float, default=DEFAULT_PREDICTION_FLOOR, help="Minimum probability floor.")
    parser.add_argument("--prior-strength", type=float, default=DEFAULT_OBSERVATION_PRIOR_STRENGTH, help="Observation prior strength.")
    parser.add_argument(
        "--history-prior-strength",
        type=float,
        default=DEFAULT_HISTORY_PRIOR_STRENGTH,
        help="Pseudo-count strength used when blending cached empirical priors into the baseline.",
    )
    parser.add_argument("--viewport-size", type=int, default=DEFAULT_VIEWPORT_SIZE, help="Viewport size used in the interrupted run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = AstarClient(token=args.token, base_url=args.base_url)
    artifact_store = ArtifactStore(root=args.out_dir)
    round_root = Path(args.round_id)
    public_round_detail = Path(args.out_dir) / args.round_id / "public" / "round_detail.json"
    if not public_round_detail.exists():
        raise SystemExit(f"Missing local round detail: {public_round_detail}")

    rounds = client.get_rounds()
    round_detail = json.loads(public_round_detail.read_text())
    history_summary = summarize_history_cache(root=args.out_dir, cache_prefix=args.history_cache_prefix)
    history_prior_model = load_history_prior_model(root=args.out_dir, cache_prefix=args.history_cache_prefix)

    observations_by_seed = load_cached_simulations(root=Path(args.out_dir), round_id=args.round_id)
    budget_before = client.get_budget() if client.is_authenticated else None

    predictions = build_round_predictions(
        round_detail=round_detail,
        floor=args.floor,
        observations_by_seed=observations_by_seed,
        prior_strength=args.prior_strength,
        history_prior_model=history_prior_model,
        history_prior_strength=args.history_prior_strength,
    )

    for seed_index, prediction in enumerate(predictions):
        validate_prediction_array(
            prediction,
            expected_height=int(round_detail["map_height"]),
            expected_width=int(round_detail["map_width"]),
        )
        payload = {
            "round_id": args.round_id,
            "seed_index": seed_index,
            "prediction": prediction.tolist(),
        }
        artifact_store.write_json(round_root / "predictions" / f"seed_{seed_index}.json", payload)
        if args.submit:
            validate_submission_payload(
                payload,
                expected_round_id=args.round_id,
                expected_height=int(round_detail["map_height"]),
                expected_width=int(round_detail["map_width"]),
            )
            response = client.submit_prediction(payload)
            artifact_store.write_json(
                round_root / "team" / "submissions" / f"seed_{seed_index}.json",
                {"request": payload, "response": response, "request_meta": client.get_last_request_meta()},
            )
            print(f"submitted seed {seed_index}: {response}")
        else:
            print(f"rebuilt seed {seed_index}")

    budget_after = client.get_budget() if client.is_authenticated else None
    if args.submit:
        try:
            predictions_state = client.get_my_predictions(args.round_id)
            artifact_store.write_json(round_root / "team" / "my_predictions.json", predictions_state)
        except AstarAPIError as exc:
            print(f"warning: unable to fetch my_predictions after submit: {exc}")

    report = build_run_report(
        round_id=args.round_id,
        round_detail=round_detail,
        rounds=rounds,
        predictions=predictions,
        simulate_enabled=bool(observations_by_seed),
        submit_enabled=args.submit,
        total_queries_requested=sum(len(items) for items in observations_by_seed.values()),
        viewport_size=args.viewport_size,
        floor=args.floor,
        prior_strength=args.prior_strength,
        query_plan_summary={
            "resume_mode": True,
            "cached_observation_counts": {str(seed_index): len(items) for seed_index, items in observations_by_seed.items()},
        },
        history_summary=history_summary,
        history_prior_summary=history_prior_model.to_summary() if history_prior_model is not None else None,
        observation_plan=None,
        observations_by_seed=observations_by_seed,
        budget_before=budget_before,
        budget_after=budget_after,
        request_metrics=client.get_request_metrics_summary(),
    )
    artifact_store.write_json(round_root / "report_resume.json", report)


def load_cached_simulations(root: Path, round_id: str) -> dict[int, list[dict[str, Any]]]:
    observations_by_seed: dict[int, list[dict[str, Any]]] = {}
    sim_root = root / round_id / "team" / "simulations"
    if not sim_root.exists():
        return observations_by_seed
    for seed_dir in sorted(sim_root.glob("seed_*")):
        seed_index = int(seed_dir.name.split("_")[1])
        observations_by_seed[seed_index] = []
        for query_path in sorted(seed_dir.glob("query_*.json")):
            payload = json.loads(query_path.read_text())
            observations_by_seed[seed_index].append(payload["response"])
    return observations_by_seed


if __name__ == "__main__":
    main()

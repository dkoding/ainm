from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from artifacts import ArtifactStore
from astar_client import AstarAPIError, AstarClient
from baseline import build_round_predictions
from config import (
    DEFAULT_AINM_BASE_URL,
    DEFAULT_GCS_ARTIFACTS_PREFIX,
    DEFAULT_HISTORY_CACHE_PREFIX,
    DEFAULT_OBSERVATION_PRIOR_STRENGTH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PREDICTION_FLOOR,
    DEFAULT_QUERIES_PER_SEED,
    DEFAULT_SIMULATE,
    DEFAULT_SUBMIT,
    DEFAULT_VIEWPORT_SIZE,
    AstarSettings,
)
from history_cache import summarize_history_cache, sync_history_cache
from observation_strategy import build_round_viewport_plan


def parse_args() -> argparse.Namespace:
    secrets = AstarSettings.from_env()

    parser = argparse.ArgumentParser(description="Run the Astar Island scaffold for one round.")
    parser.add_argument("--token", default=secrets.access_token, help="AINM access_token JWT.")
    parser.add_argument("--base-url", default=DEFAULT_AINM_BASE_URL, help="API base URL.")
    parser.add_argument("--round-id", help="Specific round ID. Defaults to the active round.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR), help="Where to write artifacts.")
    parser.add_argument(
        "--submit",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_SUBMIT,
        help="Whether to POST prediction tensors for all seeds.",
    )
    parser.add_argument(
        "--simulate",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_SIMULATE,
        help="Whether to spend simulate queries before building predictions.",
    )
    parser.add_argument(
        "--queries-per-seed",
        type=int,
        default=DEFAULT_QUERIES_PER_SEED,
        help="How many simulation queries to spend per seed when --simulate is enabled.",
    )
    parser.add_argument(
        "--viewport-size",
        type=int,
        default=DEFAULT_VIEWPORT_SIZE,
        help="Viewport width and height for the simple observation plan. Must be in [5, 15].",
    )
    parser.add_argument(
        "--floor",
        type=float,
        default=DEFAULT_PREDICTION_FLOOR,
        help="Minimum probability floor applied before renormalization.",
    )
    parser.add_argument(
        "--prior-strength",
        type=float,
        default=DEFAULT_OBSERVATION_PRIOR_STRENGTH,
        help="Pseudo-count strength of the prior before simulation observations are blended in.",
    )
    parser.add_argument("--gcs-bucket", help="Optional GCS bucket for artifact upload.")
    parser.add_argument("--gcs-prefix", default=DEFAULT_GCS_ARTIFACTS_PREFIX, help="Optional GCS prefix for artifact upload.")
    parser.add_argument(
        "--sync-history",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Refresh cached completed-round history before running the current round.",
    )
    parser.add_argument(
        "--history-round-limit",
        type=int,
        help="Optional limit on how many completed rounds to refresh when --sync-history is enabled.",
    )
    parser.add_argument(
        "--history-cache-prefix",
        default=DEFAULT_HISTORY_CACHE_PREFIX,
        help="Relative cache directory inside --out-dir for completed-round history.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 5 <= args.viewport_size <= 15:
        raise SystemExit("--viewport-size must be between 5 and 15.")

    client = AstarClient(token=args.token, base_url=args.base_url)
    artifact_store = ArtifactStore(root=args.out_dir, gcs_bucket=args.gcs_bucket, gcs_prefix=args.gcs_prefix)

    if args.sync_history:
        history_summary = sync_history_cache(
            client=client,
            artifact_store=artifact_store,
            cache_prefix=args.history_cache_prefix,
            round_limit=args.history_round_limit,
            sync_analysis=client.is_authenticated,
        )
        print(
            "history cache: "
            f"{history_summary['completed_rounds_cached']} completed rounds, "
            f"{history_summary['analysis_cached_seeds']} cached analysis seeds"
        )
    else:
        history_summary = summarize_history_cache(root=args.out_dir, cache_prefix=args.history_cache_prefix)
        if history_summary:
            print(
                "history cache: loaded "
                f"{history_summary['completed_rounds_cached']} completed rounds and "
                f"{history_summary['analysis_cached_seeds']} analysis seeds "
                f"from {history_summary['cache_path']}"
            )

    rounds = client.get_rounds()
    round_id = args.round_id or find_active_round_id(rounds)
    round_detail = client.get_round_detail(round_id)

    seeds_count = int(round_detail["seeds_count"])
    if args.simulate and args.queries_per_seed * seeds_count > 50:
        raise SystemExit(
            f"Simulation plan would spend {args.queries_per_seed * seeds_count} queries; the documented limit is 50."
        )

    round_root = Path(round_id)
    artifact_store.write_json(round_root / "public" / "rounds.json", rounds)
    artifact_store.write_json(round_root / "public" / "round_detail.json", round_detail)
    artifact_store.write_json(round_root / "public" / "leaderboard.json", client.get_leaderboard())

    maybe_write_team_state(client, artifact_store, round_root, round_id)

    observations_by_seed: dict[int, list[dict[str, Any]]] = {}
    if args.simulate:
        if not args.token:
            raise SystemExit("Missing token. --simulate requires --token or AINM_ACCESS_TOKEN.")
        observation_plan = build_round_viewport_plan(
            round_detail=round_detail,
            queries_per_seed=args.queries_per_seed,
            viewport_size=args.viewport_size,
        )
        artifact_store.write_json(
            round_root / "team" / "observation_plan.json",
            {str(seed_index): [request.to_payload(round_id) for request in requests] for seed_index, requests in observation_plan.items()},
        )
        for seed_index, requests in observation_plan.items():
            observations_by_seed[seed_index] = []
            for query_index, request in enumerate(requests):
                payload = request.to_payload(round_id)
                response = client.simulate(payload)
                observations_by_seed[seed_index].append(response)
                artifact_store.write_json(
                    round_root / "team" / "simulations" / f"seed_{seed_index}" / f"query_{query_index:02d}.json",
                    {"request": payload, "response": response},
                )
                print(
                    f"seed {seed_index}: simulated viewport "
                    f"({payload['viewport_x']},{payload['viewport_y']}) "
                    f"{payload['viewport_w']}x{payload['viewport_h']}"
                )
        maybe_write_team_state(client, artifact_store, round_root, round_id, suffix="after_simulation")

    predictions = build_round_predictions(
        round_detail=round_detail,
        floor=args.floor,
        observations_by_seed=observations_by_seed,
        prior_strength=args.prior_strength,
    )

    for seed_index, prediction in enumerate(predictions):
        payload = {
            "round_id": round_id,
            "seed_index": seed_index,
            "prediction": prediction.tolist(),
        }
        output_path = artifact_store.write_json(round_root / "predictions" / f"seed_{seed_index}.json", payload)
        print(f"seed {seed_index}: wrote {output_path}")
        if args.submit:
            if not args.token:
                raise SystemExit("Missing token. --submit requires --token or AINM_ACCESS_TOKEN.")
            response = client.submit_prediction(payload)
            artifact_store.write_json(round_root / "team" / "submissions" / f"seed_{seed_index}.json", response)
            print(f"seed {seed_index}: submit response {response}")

    if args.submit:
        try:
            predictions_state = client.get_my_predictions(round_id)
            artifact_store.write_json(round_root / "team" / "my_predictions.json", predictions_state)
        except AstarAPIError as exc:
            print(f"warning: unable to fetch my_predictions after submit: {exc}")


def maybe_write_team_state(
    client: AstarClient,
    artifact_store: ArtifactStore,
    round_root: Path,
    round_id: str,
    suffix: str = "initial",
) -> None:
    if not client.is_authenticated:
        return
    try:
        artifact_store.write_json(round_root / "team" / f"budget_{suffix}.json", client.get_budget())
        artifact_store.write_json(round_root / "team" / f"my_rounds_{suffix}.json", client.get_my_rounds())
    except AstarAPIError as exc:
        print(f"warning: unable to fetch authenticated team state: {exc}")
    try:
        artifact_store.write_json(round_root / "team" / f"my_predictions_{suffix}.json", client.get_my_predictions(round_id))
    except AstarAPIError:
        # No submission yet is fine.
        pass


def find_active_round_id(rounds: list[dict[str, Any]]) -> str:
    for round_item in rounds:
        if round_item.get("status") == "active":
            return str(round_item["id"])
    if rounds:
        latest_round = max(rounds, key=lambda item: (item.get("event_date", ""), int(item.get("round_number", 0))))
        raise SystemExit(
            "No active round found. "
            f"Pass --round-id explicitly, for example --round-id {latest_round['id']} "
            f"(latest round status: {latest_round.get('status')})."
        )
    raise SystemExit("No active round found and /rounds returned no data.")


if __name__ == "__main__":
    main()

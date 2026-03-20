from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from artifacts import ArtifactStore
from astar_client import AstarAPIError, AstarClient
from baseline import build_round_predictions
from config import AstarSettings
from observation_strategy import build_round_viewport_plan


def parse_args() -> argparse.Namespace:
    defaults = AstarSettings.from_env()

    parser = argparse.ArgumentParser(description="Run the Astar Island scaffold for one round.")
    parser.add_argument("--token", default=defaults.access_token, help="AINM access_token JWT.")
    parser.add_argument("--base-url", default=defaults.base_url, help="API base URL.")
    parser.add_argument("--round-id", default=defaults.round_id, help="Specific round ID. Defaults to the active round.")
    parser.add_argument("--out-dir", default=str(defaults.output_dir), help="Where to write artifacts.")
    parser.add_argument(
        "--submit",
        action=argparse.BooleanOptionalAction,
        default=defaults.submit,
        help="Whether to POST prediction tensors for all seeds.",
    )
    parser.add_argument(
        "--simulate",
        action=argparse.BooleanOptionalAction,
        default=defaults.simulate,
        help="Whether to spend simulate queries before building predictions.",
    )
    parser.add_argument(
        "--queries-per-seed",
        type=int,
        default=defaults.queries_per_seed,
        help="How many simulation queries to spend per seed when --simulate is enabled.",
    )
    parser.add_argument(
        "--viewport-size",
        type=int,
        default=defaults.viewport_size,
        help="Viewport width and height for the simple observation plan. Must be in [5, 15].",
    )
    parser.add_argument(
        "--floor",
        type=float,
        default=defaults.prediction_floor,
        help="Minimum probability floor applied before renormalization.",
    )
    parser.add_argument(
        "--prior-strength",
        type=float,
        default=defaults.observation_prior_strength,
        help="Pseudo-count strength of the prior before simulation observations are blended in.",
    )
    parser.add_argument("--gcs-bucket", default=defaults.gcs_artifacts_bucket, help="Optional GCS bucket for artifact upload.")
    parser.add_argument("--gcs-prefix", default=defaults.gcs_artifacts_prefix, help="Optional GCS prefix for artifact upload.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 5 <= args.viewport_size <= 15:
        raise SystemExit("--viewport-size must be between 5 and 15.")

    client = AstarClient(token=args.token, base_url=args.base_url)
    artifact_store = ArtifactStore(root=args.out_dir, gcs_bucket=args.gcs_bucket, gcs_prefix=args.gcs_prefix)

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
    raise SystemExit("No active round found.")


if __name__ == "__main__":
    main()

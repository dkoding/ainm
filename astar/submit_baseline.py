from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from astar_client import AstarClient
from baseline import build_round_predictions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit the Astar Island baseline.")
    parser.add_argument("--token", default=os.getenv("AINM_ACCESS_TOKEN"), help="AINM access_token JWT.")
    parser.add_argument("--base-url", default="https://api.ainm.no", help="API base URL.")
    parser.add_argument("--round-id", help="Specific round ID. Defaults to the active round.")
    parser.add_argument("--out-dir", default="artifacts", help="Where to write prediction JSON dumps.")
    parser.add_argument("--submit", action="store_true", help="Actually POST the predictions.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.token:
        raise SystemExit("Missing token. Pass --token or set AINM_ACCESS_TOKEN.")

    client = AstarClient(token=args.token, base_url=args.base_url)
    round_id = args.round_id or find_active_round_id(client)
    round_detail = client.get_round_detail(round_id)
    predictions = build_round_predictions(round_detail)

    out_dir = Path(args.out_dir) / round_id
    out_dir.mkdir(parents=True, exist_ok=True)

    for seed_index, prediction in enumerate(predictions):
        payload = {
            "round_id": round_id,
            "seed_index": seed_index,
            "prediction": prediction.tolist(),
        }
        output_path = out_dir / f"seed_{seed_index}.json"
        output_path.write_text(json.dumps(payload, separators=(",", ":")))

        if args.submit:
            response = client.submit_prediction(payload)
            print(f"seed {seed_index}: {response}")
        else:
            print(f"seed {seed_index}: wrote {output_path}")


def find_active_round_id(client: AstarClient) -> str:
    rounds = client.get_rounds()
    for round_item in rounds:
        if round_item.get("status") == "active":
            return str(round_item["id"])
    raise SystemExit("No active round found.")


if __name__ == "__main__":
    main()

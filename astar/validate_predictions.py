from __future__ import annotations

import argparse
import json
from pathlib import Path

from astar_client import AstarClient
from config import DEFAULT_AINM_BASE_URL, DEFAULT_OUTPUT_DIR
from validation import validate_prediction_array, validate_round_detail_response


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate locally written prediction payloads.")
    parser.add_argument("--round-id", required=True, help="Round ID for the prediction files.")
    parser.add_argument("--root", default=str(DEFAULT_OUTPUT_DIR), help="Artifact root containing predictions.")
    parser.add_argument("--base-url", default=DEFAULT_AINM_BASE_URL, help="API base URL for pulling round detail if needed.")
    parser.add_argument("--use-live-round-detail", action=argparse.BooleanOptionalAction, default=False, help="Fetch round detail from the API instead of local artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root)
    round_root = root / args.round_id
    if args.use_live_round_detail:
        round_detail = AstarClient(base_url=args.base_url).get_round_detail(args.round_id)
    else:
        round_detail_path = round_root / "public" / "round_detail.json"
        if not round_detail_path.exists():
            raise SystemExit(f"Missing local round detail: {round_detail_path}")
        round_detail = json.loads(round_detail_path.read_text())
        validate_round_detail_response(round_detail)

    height = int(round_detail["map_height"])
    width = int(round_detail["map_width"])
    seeds_count = int(round_detail["seeds_count"])
    for seed_index in range(seeds_count):
        prediction_path = round_root / "predictions" / f"seed_{seed_index}.json"
        if not prediction_path.exists():
            raise SystemExit(f"Missing prediction file: {prediction_path}")
        payload = json.loads(prediction_path.read_text())
        validate_prediction_array(payload["prediction"], expected_height=height, expected_width=width)
        print(f"validated {prediction_path}")


if __name__ == "__main__":
    main()

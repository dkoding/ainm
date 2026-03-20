from __future__ import annotations

import argparse
import json
from pathlib import Path

from config import DEFAULT_HISTORY_CACHE_PREFIX, DEFAULT_OUTPUT_DIR
from evaluate_history import evaluate_history_cache


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grid-search baseline hyperparameters on cached completed rounds.")
    parser.add_argument("--root", default=str(DEFAULT_OUTPUT_DIR), help="Artifact root containing the history cache.")
    parser.add_argument("--cache-prefix", default=DEFAULT_HISTORY_CACHE_PREFIX, help="Relative cache directory inside --root.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR / DEFAULT_HISTORY_CACHE_PREFIX / "tuning.json"),
        help="Where to write the tuning report.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    floors = [0.005, 0.01, 0.02]
    strengths = [0.5, 1.0, 2.0, 4.0]
    results = []
    best = None
    for floor in floors:
        for strength in strengths:
            report = evaluate_history_cache(
                root=args.root,
                cache_prefix=args.cache_prefix,
                floor=floor,
                history_prior_strength=strength,
                leave_one_round_out=True,
            )
            score = report["summary"]["mean_round_score"]
            item = {"floor": floor, "history_prior_strength": strength, "mean_round_score": score}
            results.append(item)
            if best is None or score > best["mean_round_score"]:
                best = item

    output = {"best": best, "results": results}
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True))
    print(output_path)
    print(json.dumps(best, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

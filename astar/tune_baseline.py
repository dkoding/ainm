from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path

from config import DEFAULT_HISTORY_CACHE_PREFIX, DEFAULT_OUTPUT_DIR
from evaluate_history import evaluate_history_cache
from history_cache import load_history_index


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
    output = tune_baseline_from_history(root=args.root, cache_prefix=args.cache_prefix)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True))
    print(output_path)
    print(json.dumps(output["best"], indent=2, sort_keys=True))


def tune_baseline_from_history(
    root: str | Path = DEFAULT_OUTPUT_DIR,
    cache_prefix: str = DEFAULT_HISTORY_CACHE_PREFIX,
    floors: list[float] | None = None,
    history_prior_strengths: list[float] | None = None,
) -> dict:
    root_path = Path(root)
    index = load_history_index(root=root_path, cache_prefix=cache_prefix)
    history_round_ids = [str(item["round_id"]) for item in index.get("rounds", [])] if index else []
    floors = floors or [0.005, 0.01, 0.02]
    history_prior_strengths = history_prior_strengths or [0.5, 1.0, 2.0, 4.0]
    results = []
    best = None
    for floor in floors:
        for strength in history_prior_strengths:
            report = evaluate_history_cache(
                root=root_path,
                cache_prefix=cache_prefix,
                floor=floor,
                history_prior_strength=strength,
                leave_one_round_out=True,
            )
            score = report["summary"]["mean_round_score"]
            item = {"floor": floor, "history_prior_strength": strength, "mean_round_score": score}
            results.append(item)
            if best is None or score > best["mean_round_score"]:
                best = item
    signature = hashlib.sha256(
        json.dumps(
            {
                "version": 1,
                "history_round_ids": history_round_ids,
                "floors": floors,
                "history_prior_strengths": history_prior_strengths,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "signature": signature,
        "history_round_ids": history_round_ids,
        "best": best,
        "results": results,
    }


if __name__ == "__main__":
    main()

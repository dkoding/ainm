from __future__ import annotations

import argparse

from config import DEFAULT_HISTORY_CACHE_PREFIX, DEFAULT_OUTPUT_DIR
from history_dataset import write_history_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a JSONL training dataset from cached Astar history.")
    parser.add_argument("--root", default=str(DEFAULT_OUTPUT_DIR), help="Artifact root containing the history cache.")
    parser.add_argument("--cache-prefix", default=DEFAULT_HISTORY_CACHE_PREFIX, help="Relative cache directory inside --root.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR / DEFAULT_HISTORY_CACHE_PREFIX / "datasets" / "cell_examples.jsonl"),
        help="Where to write the dataset JSONL file.",
    )
    parser.add_argument("--neighborhood-radius", type=int, default=1, help="Neighborhood radius for local cell features.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = write_history_dataset(
        root=args.root,
        output_path=args.output,
        cache_prefix=args.cache_prefix,
        neighborhood_radius=args.neighborhood_radius,
    )
    print(summary)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config import DEFAULT_HISTORY_CACHE_PREFIX, DEFAULT_OUTPUT_DIR
from sklearn_model import save_model_artifact, train_random_forest_from_history


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a local sklearn model from cached Astar history.")
    parser.add_argument("--root", default=str(DEFAULT_OUTPUT_DIR), help="Artifact root containing the history cache.")
    parser.add_argument("--cache-prefix", default=DEFAULT_HISTORY_CACHE_PREFIX, help="Relative cache directory inside --root.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR / "models" / "astar_random_forest.pkl"),
        help="Where to write the trained model artifact.",
    )
    parser.add_argument("--neighborhood-radius", type=int, default=1, help="Neighborhood radius used to build local cell features.")
    parser.add_argument("--n-estimators", type=int, default=300, help="Number of trees in the random forest.")
    parser.add_argument("--min-samples-leaf", type=int, default=5, help="Minimum samples per leaf.")
    parser.add_argument("--random-state", type=int, default=0, help="Random seed for reproducible training.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    artifact = train_random_forest_from_history(
        root=args.root,
        cache_prefix=args.cache_prefix,
        neighborhood_radius=args.neighborhood_radius,
        n_estimators=args.n_estimators,
        min_samples_leaf=args.min_samples_leaf,
        random_state=args.random_state,
    )
    paths = save_model_artifact(artifact, args.output)
    print(paths["model_path"])
    print(paths["metadata_path"])
    print(json.dumps(artifact.to_metadata(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

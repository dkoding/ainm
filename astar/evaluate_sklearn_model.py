from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from config import DEFAULT_HISTORY_CACHE_PREFIX, DEFAULT_OUTPUT_DIR, DEFAULT_PREDICTION_FLOOR
from history_cache import load_history_index
from scoring import round_score, seed_score
from sklearn_model import build_round_predictions_from_model, train_random_forest_from_history


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the local sklearn model against cached completed rounds.")
    parser.add_argument("--root", default=str(DEFAULT_OUTPUT_DIR), help="Artifact root containing the history cache.")
    parser.add_argument("--cache-prefix", default=DEFAULT_HISTORY_CACHE_PREFIX, help="Relative cache directory inside --root.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR / DEFAULT_HISTORY_CACHE_PREFIX / "sklearn_evaluation.json"),
        help="Where to write the evaluation report.",
    )
    parser.add_argument("--floor", type=float, default=DEFAULT_PREDICTION_FLOOR, help="Prediction floor applied to model outputs.")
    parser.add_argument("--neighborhood-radius", type=int, default=1, help="Neighborhood radius used to build local cell features.")
    parser.add_argument("--n-estimators", type=int, default=300, help="Number of trees in the random forest.")
    parser.add_argument("--min-samples-leaf", type=int, default=5, help="Minimum samples per leaf.")
    parser.add_argument("--random-state", type=int, default=0, help="Random seed for reproducible training.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = evaluate_sklearn_history(
        root=args.root,
        cache_prefix=args.cache_prefix,
        floor=args.floor,
        neighborhood_radius=args.neighborhood_radius,
        n_estimators=args.n_estimators,
        min_samples_leaf=args.min_samples_leaf,
        random_state=args.random_state,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(output_path)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))


def evaluate_sklearn_history(
    root: str | Path = DEFAULT_OUTPUT_DIR,
    cache_prefix: str = DEFAULT_HISTORY_CACHE_PREFIX,
    floor: float = DEFAULT_PREDICTION_FLOOR,
    neighborhood_radius: int = 1,
    n_estimators: int = 300,
    min_samples_leaf: int = 5,
    random_state: int = 0,
) -> dict[str, Any]:
    root_path = Path(root)
    index = load_history_index(root=root_path, cache_prefix=cache_prefix)
    if not index:
        raise SystemExit(f"No history cache found under {root_path / cache_prefix}.")

    rounds_report: list[dict[str, Any]] = []
    all_seed_scores: list[float] = []

    for round_entry in index.get("rounds", []):
        round_id = str(round_entry["round_id"])
        round_detail_path = root_path / cache_prefix / "rounds" / round_id / "public" / "round_detail.json"
        round_detail = json.loads(round_detail_path.read_text())
        artifact = train_random_forest_from_history(
            root=root_path,
            cache_prefix=cache_prefix,
            neighborhood_radius=neighborhood_radius,
            exclude_round_ids={round_id},
            n_estimators=n_estimators,
            min_samples_leaf=min_samples_leaf,
            random_state=random_state,
        )
        predictions = build_round_predictions_from_model(artifact=artifact, round_detail=round_detail, floor=floor)

        seed_reports: list[dict[str, Any]] = []
        for seed_index in round_entry.get("analysis_cached_seeds", []):
            analysis_path = root_path / cache_prefix / "rounds" / round_id / "team" / "analysis" / f"seed_{int(seed_index)}.json"
            analysis = json.loads(analysis_path.read_text())
            score = seed_score(analysis["ground_truth"], predictions[int(seed_index)])
            seed_reports.append({"seed_index": int(seed_index), "score": score})
            all_seed_scores.append(score)

        rounds_report.append(
            {
                "round_id": round_id,
                "round_number": round_entry.get("round_number"),
                "training_summary": artifact.training_summary,
                "seed_reports": seed_reports,
                "round_score": round_score([item["score"] for item in seed_reports]),
            }
        )

    summary = {
        "completed_rounds_evaluated": len(rounds_report),
        "seed_scores_evaluated": len(all_seed_scores),
        "mean_seed_score": float(sum(all_seed_scores) / len(all_seed_scores)) if all_seed_scores else 0.0,
        "mean_round_score": float(sum(item["round_score"] for item in rounds_report) / len(rounds_report)) if rounds_report else 0.0,
        "floor": floor,
        "neighborhood_radius": neighborhood_radius,
        "n_estimators": n_estimators,
        "min_samples_leaf": min_samples_leaf,
        "random_state": random_state,
    }
    return {"summary": summary, "rounds": rounds_report}


if __name__ == "__main__":
    main()

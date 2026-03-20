from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from artifacts import ArtifactStore
from astar_client import AstarClient
from config import DEFAULT_AINM_BASE_URL, DEFAULT_OUTPUT_DIR, AstarSettings
from scoring import seed_score


def parse_args() -> argparse.Namespace:
    secrets = AstarSettings.from_env()
    parser = argparse.ArgumentParser(description="Fetch post-round analysis and write a review summary.")
    parser.add_argument("--round-id", required=True, help="Completed round ID to review.")
    parser.add_argument("--token", default=secrets.access_token, help="AINM access_token JWT.")
    parser.add_argument("--base-url", default=DEFAULT_AINM_BASE_URL, help="API base URL.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR), help="Artifact root for review outputs.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.token:
        raise SystemExit("--token or AINM_ACCESS_TOKEN is required for post-round review.")
    client = AstarClient(token=args.token, base_url=args.base_url)
    artifact_store = ArtifactStore(root=args.out_dir)

    analyses = []
    seed_scores: list[float] = []
    for seed_index in range(5):
        analysis = client.get_analysis(args.round_id, seed_index)
        artifact_store.write_json(Path(args.round_id) / "team" / "analysis" / f"seed_{seed_index}.json", analysis)
        score = seed_score(analysis["ground_truth"], analysis["prediction"]) if analysis.get("prediction") is not None else 0.0
        seed_scores.append(score)
        analyses.append({"seed_index": seed_index, "score": score, **extract_seed_lessons(analysis)})

    review = {
        "round_id": args.round_id,
        "seed_reports": analyses,
        "mean_seed_score": float(sum(seed_scores) / len(seed_scores)),
        "lessons": summarize_lessons(analyses),
    }
    output_path = artifact_store.write_json(Path(args.round_id) / "team" / "post_round_review.json", review)
    print(output_path)


def extract_seed_lessons(analysis: dict[str, Any]) -> dict[str, Any]:
    ground_truth = np.asarray(analysis["ground_truth"], dtype=float)
    prediction = np.asarray(analysis["prediction"], dtype=float) if analysis.get("prediction") is not None else np.zeros_like(ground_truth)
    abs_error = np.abs(ground_truth - prediction).sum(axis=-1)
    hardest_index = np.unravel_index(int(np.argmax(abs_error)), abs_error.shape)
    y, x = int(hardest_index[0]), int(hardest_index[1])
    return {
        "largest_error_cell": {"x": x, "y": y, "abs_error": float(abs_error[y, x])},
        "ground_truth_argmax_counts": _argmax_counts(ground_truth),
        "prediction_argmax_counts": _argmax_counts(prediction),
    }


def summarize_lessons(seed_reports: list[dict[str, Any]]) -> list[str]:
    lessons: list[str] = []
    if any(report["score"] < 50 for report in seed_reports):
        lessons.append("At least one seed scored below 50 in offline replay; inspect the largest-error cells first.")
    if any(report["ground_truth_argmax_counts"].get("ruin", 0) > report["prediction_argmax_counts"].get("ruin", 0) for report in seed_reports):
        lessons.append("The model tends to under-predict ruin-heavy outcomes on some seeds.")
    if any(report["ground_truth_argmax_counts"].get("port", 0) > report["prediction_argmax_counts"].get("port", 0) for report in seed_reports):
        lessons.append("Coastal and trade-related cells still need better port calibration.")
    if not lessons:
        lessons.append("No obvious single failure mode dominated the replay; continue tuning priors and query planning.")
    return lessons


def _argmax_counts(tensor: np.ndarray) -> dict[str, int]:
    argmax = tensor.argmax(axis=-1)
    labels = ["empty", "settlement", "port", "ruin", "forest", "mountain"]
    return {label: int((argmax == idx).sum()) for idx, label in enumerate(labels)}


if __name__ == "__main__":
    main()

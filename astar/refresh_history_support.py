from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from artifacts import ArtifactStore
from astar_client import AstarClient
from config import (
    DEFAULT_AINM_BASE_URL,
    DEFAULT_HISTORY_CACHE_PREFIX,
    DEFAULT_HISTORY_PRIOR_STRENGTH,
    DEFAULT_NEIGHBORHOOD_RADIUS,
    DEFAULT_OBSERVATION_PRIOR_STRENGTH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PREDICTION_FLOOR,
    DEFAULT_SKLEARN_MIN_SAMPLES_LEAF,
    DEFAULT_SKLEARN_N_ESTIMATORS,
    DEFAULT_SKLEARN_RANDOM_STATE,
    DEFAULT_TOTAL_QUERIES,
    DEFAULT_VIEWPORT_SIZE,
    AstarSettings,
)
from evaluate_sklearn_model import evaluate_sklearn_history
from history_cache import history_round_ids_with_analysis, sync_history_cache
from prediction_variants import evaluate_prediction_variants
from sklearn_model import save_model_artifact, train_random_forest_from_history
from tune_baseline import tune_baseline_from_history


def parse_args() -> argparse.Namespace:
    secrets = AstarSettings.from_env()
    parser = argparse.ArgumentParser(description="Refresh cached history-dependent support artifacts between rounds.")
    parser.add_argument("--token", default=secrets.access_token, help="AINM access_token JWT.")
    parser.add_argument("--base-url", default=DEFAULT_AINM_BASE_URL, help="API base URL.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR), help="Artifact root.")
    parser.add_argument("--cache-prefix", default=DEFAULT_HISTORY_CACHE_PREFIX, help="Relative history cache path.")
    parser.add_argument("--floor", type=float, default=DEFAULT_PREDICTION_FLOOR, help="Fallback prediction floor.")
    parser.add_argument(
        "--prior-strength",
        type=float,
        default=DEFAULT_OBSERVATION_PRIOR_STRENGTH,
        help="Observation prior strength used for offline variant replay.",
    )
    parser.add_argument(
        "--history-prior-strength",
        type=float,
        default=DEFAULT_HISTORY_PRIOR_STRENGTH,
        help="Fallback history-prior strength when no tuning report is available.",
    )
    parser.add_argument(
        "--neighborhood-radius",
        type=int,
        default=DEFAULT_NEIGHBORHOOD_RADIUS,
        help="Neighborhood radius used for sklearn feature extraction.",
    )
    parser.add_argument(
        "--n-estimators",
        type=int,
        default=DEFAULT_SKLEARN_N_ESTIMATORS,
        help="Number of trees for the sklearn random forest.",
    )
    parser.add_argument(
        "--min-samples-leaf",
        type=int,
        default=DEFAULT_SKLEARN_MIN_SAMPLES_LEAF,
        help="Minimum samples per leaf for the sklearn random forest.",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=DEFAULT_SKLEARN_RANDOM_STATE,
        help="Random seed for deterministic retraining.",
    )
    parser.add_argument(
        "--simulate-queries",
        type=int,
        default=DEFAULT_TOTAL_QUERIES,
        help="Synthetic or replayed query count used for offline variant evaluation.",
    )
    parser.add_argument(
        "--viewport-size",
        type=int,
        default=DEFAULT_VIEWPORT_SIZE,
        help="Viewport size used for offline replay evaluation.",
    )
    parser.add_argument(
        "--variant-selection",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refresh offline prediction variant ranking.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.token:
        raise SystemExit("--token or AINM_ACCESS_TOKEN is required for refresh_history_support.")
    summary = refresh_history_support(args=args)
    print(json.dumps(summary, indent=2, sort_keys=True))


def refresh_history_support(args: argparse.Namespace) -> dict[str, Any]:
    client = AstarClient(token=args.token, base_url=args.base_url)
    artifact_store = ArtifactStore(root=args.out_dir)
    history_summary = sync_history_cache(
        client=client,
        artifact_store=artifact_store,
        cache_prefix=args.cache_prefix,
        sync_analysis=client.is_authenticated,
    )
    analysis_round_ids = history_round_ids_with_analysis(history_summary)
    output_root = Path(args.out_dir) / args.cache_prefix
    output_root.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "history_summary": {
            "completed_rounds_cached": int(history_summary.get("completed_rounds_cached", 0)),
            "analysis_cached_seeds": int(history_summary.get("analysis_cached_seeds", 0)),
            "analysis_round_ids": analysis_round_ids,
        }
    }

    if not analysis_round_ids:
        output_path = output_root / "support_refresh.json"
        output_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
        return summary

    tuning = tune_baseline_from_history(root=args.out_dir, cache_prefix=args.cache_prefix)
    tuning_path = output_root / "tuning.json"
    tuning_path.write_text(json.dumps(tuning, indent=2, sort_keys=True))
    best_tuning = tuning.get("best") or {}
    floor = float(best_tuning.get("floor", args.floor))
    history_prior_strength = float(best_tuning.get("history_prior_strength", args.history_prior_strength))
    summary["tuning"] = {
        "path": str(tuning_path),
        "best": best_tuning,
    }

    model_path = Path(args.out_dir) / "models" / "astar_random_forest.pkl"
    artifact = train_random_forest_from_history(
        root=args.out_dir,
        cache_prefix=args.cache_prefix,
        neighborhood_radius=args.neighborhood_radius,
        n_estimators=args.n_estimators,
        min_samples_leaf=args.min_samples_leaf,
        random_state=args.random_state,
    )
    model_paths = save_model_artifact(artifact, model_path)
    summary["sklearn_training"] = {
        **artifact.to_metadata(),
        **model_paths,
    }

    sklearn_evaluation = evaluate_sklearn_history(
        root=args.out_dir,
        cache_prefix=args.cache_prefix,
        floor=floor,
        neighborhood_radius=args.neighborhood_radius,
        n_estimators=args.n_estimators,
        min_samples_leaf=args.min_samples_leaf,
        random_state=args.random_state,
    )
    sklearn_evaluation_path = output_root / "sklearn_evaluation.json"
    sklearn_evaluation_path.write_text(json.dumps(sklearn_evaluation, indent=2, sort_keys=True))
    summary["sklearn_evaluation"] = {
        "path": str(sklearn_evaluation_path),
        "summary": sklearn_evaluation.get("summary", {}),
    }

    if args.variant_selection:
        variant_selection = evaluate_prediction_variants(
            root=args.out_dir,
            cache_prefix=args.cache_prefix,
            floor=floor,
            prior_strength=args.prior_strength,
            history_prior_strength=history_prior_strength,
            neighborhood_radius=args.neighborhood_radius,
            n_estimators=args.n_estimators,
            min_samples_leaf=args.min_samples_leaf,
            random_state=args.random_state,
            simulate_queries=args.simulate_queries,
            viewport_size=args.viewport_size,
        )
        variant_selection_path = output_root / "variant_selection.json"
        variant_selection_path.write_text(json.dumps(variant_selection, indent=2, sort_keys=True))
        summary["variant_selection"] = {
            "path": str(variant_selection_path),
            "summary": variant_selection.get("summary", {}),
        }

    output_path = output_root / "support_refresh.json"
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
    return summary


if __name__ == "__main__":
    main()

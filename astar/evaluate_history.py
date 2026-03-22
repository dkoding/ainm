from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from baseline import build_round_predictions
from config import DEFAULT_HISTORY_CACHE_PREFIX, DEFAULT_OUTPUT_DIR, DEFAULT_PREDICTION_FLOOR
from history_cache import history_round_entries_with_analysis, load_history_index
from history_priors import build_history_prior_model
from scoring import round_score, seed_score


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the baseline against cached completed rounds.")
    parser.add_argument("--root", default=str(DEFAULT_OUTPUT_DIR), help="Artifact root containing the history cache.")
    parser.add_argument("--cache-prefix", default=DEFAULT_HISTORY_CACHE_PREFIX, help="Relative cache directory inside --root.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR / DEFAULT_HISTORY_CACHE_PREFIX / "evaluation.json"),
        help="Where to write the evaluation report.",
    )
    parser.add_argument("--floor", type=float, default=DEFAULT_PREDICTION_FLOOR, help="Prediction floor for evaluation runs.")
    parser.add_argument(
        "--history-prior-strength",
        type=float,
        default=2.0,
        help="Strength used when blending cached empirical priors into evaluated predictions.",
    )
    parser.add_argument(
        "--no-leave-one-round-out",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use all cached rounds to build history priors, including the evaluated round.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = evaluate_history_cache(
        root=args.root,
        cache_prefix=args.cache_prefix,
        floor=args.floor,
        history_prior_strength=args.history_prior_strength,
        leave_one_round_out=not args.no_leave_one_round_out,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(output_path)
    print(json.dumps(report["summary"], indent=2, sort_keys=True))


def evaluate_history_cache(
    root: str | Path,
    cache_prefix: str = DEFAULT_HISTORY_CACHE_PREFIX,
    floor: float = DEFAULT_PREDICTION_FLOOR,
    history_prior_strength: float = 2.0,
    leave_one_round_out: bool = True,
) -> dict[str, Any]:
    root_path = Path(root)
    index = load_history_index(root=root_path, cache_prefix=cache_prefix)
    if not index:
        raise SystemExit(f"No history cache found under {root_path / cache_prefix}.")

    round_entries = history_round_entries_with_analysis(index)
    rounds_report: list[dict[str, Any]] = []
    all_seed_scores: list[float] = []

    for round_entry in round_entries:
        round_id = str(round_entry["round_id"])
        round_detail_path = root_path / cache_prefix / "rounds" / round_id / "public" / "round_detail.json"
        round_detail = json.loads(round_detail_path.read_text())
        exclude = {round_id} if leave_one_round_out else None
        history_prior_model = build_history_prior_model(root=root_path, cache_prefix=cache_prefix, exclude_round_ids=exclude)

        predictions = build_round_predictions(
            round_detail=round_detail,
            floor=floor,
            history_prior_model=history_prior_model,
            history_prior_strength=history_prior_strength,
        )

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
                "seed_reports": seed_reports,
                "round_score": round_score([item["score"] for item in seed_reports]),
            }
        )

    summary = {
        "completed_rounds_evaluated": len(rounds_report),
        "seed_scores_evaluated": len(all_seed_scores),
        "mean_seed_score": float(sum(all_seed_scores) / len(all_seed_scores)) if all_seed_scores else 0.0,
        "mean_round_score": float(sum(item["round_score"] for item in rounds_report) / len(rounds_report)) if rounds_report else 0.0,
        "leave_one_round_out": leave_one_round_out,
        "history_prior_strength": history_prior_strength,
        "floor": floor,
    }
    return {"summary": summary, "rounds": rounds_report}


if __name__ == "__main__":
    main()

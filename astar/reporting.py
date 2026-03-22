from __future__ import annotations

import platform
import subprocess
from datetime import datetime, timezone
from typing import Any

import numpy as np


CLASS_NAMES = {
    0: "empty",
    1: "settlement",
    2: "port",
    3: "ruin",
    4: "forest",
    5: "mountain",
}


def build_run_report(
    *,
    round_id: str,
    round_detail: dict[str, Any],
    rounds: list[dict[str, Any]],
    predictions: list[np.ndarray],
    simulate_enabled: bool,
    submit_enabled: bool,
    total_queries_requested: int,
    viewport_size: int,
    floor: float,
    prior_strength: float,
    query_plan_summary: dict[str, Any] | None,
    history_summary: dict[str, Any] | None,
    history_prior_summary: dict[str, Any] | None,
    prediction_model: str | None = None,
    submission_strategy: str | None = None,
    submission_stages: list[dict[str, Any]] | None = None,
    sklearn_training_summary: dict[str, Any] | None = None,
    sklearn_evaluation_summary: dict[str, Any] | None = None,
    strategy_evaluation_summary: dict[str, Any] | None = None,
    strategy_feedback_summary: dict[str, Any] | None = None,
    live_variant_summary: dict[str, Any] | None = None,
    regime_summary: dict[str, Any] | None = None,
    tuning_summary: dict[str, Any] | None = None,
    guardrail_summary: dict[str, Any] | None = None,
    observation_plan: dict[str, list[dict[str, Any]]] | None = None,
    observations_by_seed: dict[int, list[dict[str, Any]]] | None = None,
    budget_before: dict[str, Any] | None = None,
    budget_after: dict[str, Any] | None = None,
    request_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_round = next((item for item in rounds if str(item.get("id")) == round_id), {})
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "round_id": round_id,
        "round_number": round_detail.get("round_number", active_round.get("round_number")),
        "round_status": round_detail.get("status", active_round.get("status")),
        "map_width": round_detail.get("map_width"),
        "map_height": round_detail.get("map_height"),
        "seeds_count": round_detail.get("seeds_count"),
        "simulate_enabled": simulate_enabled,
        "submit_enabled": submit_enabled,
        "total_queries_requested": total_queries_requested,
        "viewport_size": viewport_size,
        "prediction_floor": floor,
        "observation_prior_strength": prior_strength,
        "query_plan_summary": query_plan_summary,
        "history_cache": history_summary,
        "history_priors": history_prior_summary,
        "prediction_model": prediction_model,
        "submission_strategy": submission_strategy,
        "submission_stages": submission_stages or [],
        "sklearn_training": sklearn_training_summary,
        "sklearn_evaluation": sklearn_evaluation_summary,
        "strategy_evaluation": strategy_evaluation_summary,
        "strategy_feedback": strategy_feedback_summary,
        "live_variant_ranking": live_variant_summary,
        "regime_summary": regime_summary,
        "tuning_summary": tuning_summary,
        "guardrail_summary": guardrail_summary,
        "budget_before": budget_before,
        "budget_after": budget_after,
        "request_metrics": request_metrics,
        "observation_plan": observation_plan,
        "runtime": {
            "python_version": platform.python_version(),
            "git_commit": _git_commit(),
        },
        "seed_reports": [],
    }

    observations_by_seed = observations_by_seed or {}
    for seed_index, prediction in enumerate(predictions):
        argmax = prediction.argmax(axis=-1)
        mean_confidence = float(prediction.max(axis=-1).mean())
        mean_entropy = float((-prediction * np.log(np.clip(prediction, 1e-12, 1.0))).sum(axis=-1).mean())
        class_counts = {CLASS_NAMES[class_index]: int((argmax == class_index).sum()) for class_index in range(prediction.shape[-1])}
        seed_report = {
            "seed_index": seed_index,
            "mean_confidence": mean_confidence,
            "mean_entropy": mean_entropy,
            "argmax_class_counts": class_counts,
            "observation_count": len(observations_by_seed.get(seed_index, [])),
        }
        report["seed_reports"].append(seed_report)

    return report


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return None

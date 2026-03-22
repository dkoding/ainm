from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from artifacts import ArtifactStore
from astar_client import AstarAPIError, AstarClient
from config import (
    DEFAULT_AINM_BASE_URL,
    DEFAULT_GCS_ARTIFACTS_PREFIX,
    DEFAULT_HISTORY_CACHE_PREFIX,
    DEFAULT_HISTORY_PRIOR_STRENGTH,
    DEFAULT_NEIGHBORHOOD_RADIUS,
    DEFAULT_OBSERVATION_PRIOR_STRENGTH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PREDICTION_FLOOR,
    DEFAULT_SIMULATE,
    DEFAULT_STAGED_SUBMIT,
    DEFAULT_SKLEARN_MIN_SAMPLES_LEAF,
    DEFAULT_SKLEARN_N_ESTIMATORS,
    DEFAULT_SKLEARN_RANDOM_STATE,
    DEFAULT_SUBMIT,
    DEFAULT_SYNC_HISTORY,
    DEFAULT_TOTAL_QUERIES,
    DEFAULT_VIEWPORT_SIZE,
    AstarSettings,
)
from evaluate_sklearn_model import evaluate_sklearn_history
from history_cache import history_round_ids_with_analysis, load_history_index, summarize_history_cache, sync_history_cache
from history_priors import infer_regime_history_prior_model, load_history_prior_model
from observation_strategy import ViewportRequest, select_next_viewport_request
from prediction_variants import (
    build_prediction_variants,
    evaluate_prediction_variants,
    score_prediction_variants_for_live_round,
    strategy_signature,
)
from reporting import build_run_report
from sklearn_model import (
    load_model_artifact,
    save_model_artifact,
    train_random_forest_from_history,
)
from tune_baseline import tune_baseline_from_history
from validation import validate_prediction_array, validate_submission_payload


def parse_args() -> argparse.Namespace:
    secrets = AstarSettings.from_env()

    parser = argparse.ArgumentParser(description="Run the Astar Island scaffold for one round.")
    parser.add_argument("--token", default=secrets.access_token, help="AINM access_token JWT.")
    parser.add_argument("--base-url", default=DEFAULT_AINM_BASE_URL, help="API base URL.")
    parser.add_argument("--round-id", help="Specific round ID. Defaults to the active round.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR), help="Where to write artifacts.")
    parser.add_argument(
        "--submit",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_SUBMIT,
        help="Whether to POST prediction tensors for all seeds.",
    )
    parser.add_argument(
        "--simulate",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_SIMULATE,
        help="Whether to spend simulate queries before building predictions.",
    )
    parser.add_argument(
        "--staged-submit",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_STAGED_SUBMIT,
        help="When submitting after simulation, submit an early safe tensor first and overwrite it with the final tensor later.",
    )
    parser.add_argument(
        "--total-queries",
        type=int,
        default=DEFAULT_TOTAL_QUERIES,
        help="How many simulation queries to spend for the entire round when --simulate is enabled.",
    )
    parser.add_argument(
        "--queries-per-seed",
        type=int,
        help="Deprecated compatibility flag. If set, total budget becomes queries_per_seed * seeds_count.",
    )
    parser.add_argument(
        "--viewport-size",
        type=int,
        default=DEFAULT_VIEWPORT_SIZE,
        help="Viewport width and height for the simple observation plan. Must be in [5, 15].",
    )
    parser.add_argument(
        "--floor",
        type=float,
        default=DEFAULT_PREDICTION_FLOOR,
        help="Minimum probability floor applied before renormalization.",
    )
    parser.add_argument(
        "--prior-strength",
        type=float,
        default=DEFAULT_OBSERVATION_PRIOR_STRENGTH,
        help="Pseudo-count strength of the prior before simulation observations are blended in.",
    )
    parser.add_argument("--gcs-bucket", help="Optional GCS bucket for artifact upload.")
    parser.add_argument("--gcs-prefix", default=DEFAULT_GCS_ARTIFACTS_PREFIX, help="Optional GCS prefix for artifact upload.")
    parser.add_argument(
        "--sync-history",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_SYNC_HISTORY,
        help="Refresh cached completed-round history before running the current round.",
    )
    parser.add_argument(
        "--history-cache-prefix",
        default=DEFAULT_HISTORY_CACHE_PREFIX,
        help="Relative cache directory inside --out-dir for completed-round history.",
    )
    parser.add_argument(
        "--use-history-priors",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Blend cached completed-round analysis data into the baseline prior when available.",
    )
    parser.add_argument(
        "--history-prior-strength",
        type=float,
        default=DEFAULT_HISTORY_PRIOR_STRENGTH,
        help="Pseudo-count strength used when blending cached empirical priors into the baseline.",
    )
    parser.add_argument(
        "--prediction-model",
        choices=("auto", "baseline", "sklearn"),
        default="auto",
        help="Prediction engine to use after history sync. `auto` prefers the trained sklearn model when available.",
    )
    parser.add_argument(
        "--retrain-sklearn",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Retrain the local sklearn model from completed-round history before predicting the current round.",
    )
    parser.add_argument(
        "--evaluate-sklearn",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run leave-one-round-out evaluation after retraining the sklearn model.",
    )
    parser.add_argument(
        "--sklearn-model-path",
        help="Optional explicit path for the trained sklearn model artifact. Defaults under --out-dir/models/.",
    )
    parser.add_argument(
        "--sklearn-evaluation-output",
        help="Optional explicit path for the sklearn evaluation report. Defaults under --out-dir/history/.",
    )
    parser.add_argument(
        "--neighborhood-radius",
        type=int,
        default=DEFAULT_NEIGHBORHOOD_RADIUS,
        help="Neighborhood radius used for local sklearn feature extraction.",
    )
    parser.add_argument(
        "--sklearn-n-estimators",
        type=int,
        default=DEFAULT_SKLEARN_N_ESTIMATORS,
        help="Number of trees for the local sklearn random-forest regressor.",
    )
    parser.add_argument(
        "--sklearn-min-samples-leaf",
        type=int,
        default=DEFAULT_SKLEARN_MIN_SAMPLES_LEAF,
        help="Minimum samples per leaf for the local sklearn random-forest regressor.",
    )
    parser.add_argument(
        "--sklearn-random-state",
        type=int,
        default=DEFAULT_SKLEARN_RANDOM_STATE,
        help="Random seed for the local sklearn random-forest regressor.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 5 <= args.viewport_size <= 15:
        raise SystemExit("--viewport-size must be between 5 and 15.")

    client = AstarClient(token=args.token, base_url=args.base_url)
    artifact_store = ArtifactStore(root=args.out_dir, gcs_bucket=args.gcs_bucket, gcs_prefix=args.gcs_prefix)
    sklearn_model_path = resolve_sklearn_model_path(args)
    sklearn_evaluation_output = resolve_sklearn_evaluation_output(args)
    strategy_evaluation_output = Path(args.out_dir) / args.history_cache_prefix / "variant_selection.json"

    if args.sync_history:
        history_summary = sync_history_cache(
            client=client,
            artifact_store=artifact_store,
            cache_prefix=args.history_cache_prefix,
            sync_analysis=client.is_authenticated,
        )
        print(
            "history cache: "
            f"{history_summary['completed_rounds_cached']} completed rounds, "
            f"{history_summary['analysis_cached_seeds']} cached analysis seeds"
        )
    else:
        history_summary = summarize_history_cache(root=args.out_dir, cache_prefix=args.history_cache_prefix)
        if history_summary:
            print(
                "history cache: loaded "
                f"{history_summary['completed_rounds_cached']} completed rounds and "
                f"{history_summary['analysis_cached_seeds']} analysis seeds "
                f"from {history_summary['cache_path']}"
            )

    rounds = client.get_rounds()
    round_id = args.round_id or find_active_round_id(rounds)
    round_detail = client.get_round_detail(round_id)
    is_active_round = str(round_detail.get("status") or "").lower() == "active"
    exclude_history_round_ids = {round_id} if not is_active_round else None
    seeds_count = int(round_detail["seeds_count"])
    total_queries = resolve_total_queries(args, seeds_count)
    if args.simulate and total_queries > 50:
        raise SystemExit(
            f"Simulation plan would spend {total_queries} queries; the documented limit is 50 for the whole round."
        )
    tuning_summary = maybe_resolve_tuned_baseline_settings(
        args=args,
        history_summary=history_summary,
        is_active_round=is_active_round,
    )

    sklearn_artifact = None
    sklearn_training_summary = None
    sklearn_evaluation_summary = None
    prediction_model_used = "baseline"
    if args.prediction_model in {"auto", "sklearn"}:
        sklearn_artifact, sklearn_training_summary, sklearn_evaluation_summary = maybe_prepare_sklearn_model(
            args=args,
            sklearn_model_path=sklearn_model_path,
            sklearn_evaluation_output=sklearn_evaluation_output,
            history_summary=history_summary,
            exclude_round_ids=exclude_history_round_ids,
            is_active_round=is_active_round,
        )
        if sklearn_artifact is not None:
            prediction_model_used = "sklearn"
        elif args.prediction_model == "sklearn":
            raise SystemExit("Unable to prepare the sklearn prediction model.")

    history_prior_model = None
    if args.use_history_priors:
        history_prior_model = load_history_prior_model(
            root=args.out_dir,
            cache_prefix=args.history_cache_prefix,
            exclude_round_ids=exclude_history_round_ids,
        )
        if history_prior_model is not None:
            print(
                "history priors: loaded "
                f"{history_prior_model.rounds_used} rounds, "
                f"{history_prior_model.seeds_used} seeds, "
                f"{history_prior_model.cells_used} cells"
            )
        elif history_summary:
            print("history priors: cache present but no usable analysis records were found")

    strategy_evaluation_summary = None
    strategy_feedback_summary = None
    if args.prediction_model == "auto" and sklearn_artifact is not None:
        strategy_evaluation_summary = load_cached_strategy_evaluation(
            strategy_evaluation_output=strategy_evaluation_output,
            history_summary=history_summary,
            floor=args.floor,
            prior_strength=args.prior_strength,
            history_prior_strength=args.history_prior_strength,
            neighborhood_radius=args.neighborhood_radius,
            n_estimators=args.sklearn_n_estimators,
            min_samples_leaf=args.sklearn_min_samples_leaf,
            random_state=args.sklearn_random_state,
            simulate_queries=total_queries,
            viewport_size=args.viewport_size,
        )
        if strategy_evaluation_summary is None:
            if is_active_round:
                stale_cached = load_any_cached_strategy_evaluation(strategy_evaluation_output=strategy_evaluation_output)
                if stale_cached is not None:
                    strategy_evaluation_summary = stale_cached
                    print(
                        "variant selection: reused stale cached results for active round "
                        f"from {strategy_evaluation_output}"
                    )
                else:
                    print("variant selection: skipped expensive offline replay for active round; using fallback ordering")
            else:
                strategy_evaluation_summary = evaluate_prediction_variants(
                    root=args.out_dir,
                    cache_prefix=args.history_cache_prefix,
                    floor=args.floor,
                    prior_strength=args.prior_strength,
                    history_prior_strength=args.history_prior_strength,
                    neighborhood_radius=args.neighborhood_radius,
                    n_estimators=args.sklearn_n_estimators,
                    min_samples_leaf=args.sklearn_min_samples_leaf,
                    random_state=args.sklearn_random_state,
                    simulate_queries=total_queries,
                    viewport_size=args.viewport_size,
                )
                strategy_evaluation_output.parent.mkdir(parents=True, exist_ok=True)
                strategy_evaluation_output.write_text(json.dumps(strategy_evaluation_summary, indent=2, sort_keys=True))
        else:
            print(f"variant selection: loaded cached results from {strategy_evaluation_output}")
        best_variant = strategy_evaluation_summary["summary"].get("best_variant")
        if best_variant:
            print(
                "variant selection: chose "
                f"{best_variant} with mean round score "
                f"{strategy_evaluation_summary['summary']['best_variant_mean_round_score']:.3f}"
            )
        strategy_feedback_summary = load_strategy_feedback_summary(root=Path(args.out_dir))

    round_root = Path(round_id)
    artifact_store.write_json(round_root / "public" / "rounds.json", rounds)
    artifact_store.write_json(round_root / "public" / "round_detail.json", round_detail)
    artifact_store.write_json(round_root / "public" / "leaderboard.json", client.get_leaderboard())

    maybe_write_team_state(client, artifact_store, round_root, round_id)
    if args.submit and not args.token:
        raise SystemExit("Missing token. --submit requires --token or AINM_ACCESS_TOKEN.")
    preexisting_predictions = []
    if client.is_authenticated:
        try:
            preexisting_predictions = client.get_my_predictions(round_id)
        except AstarAPIError:
            preexisting_predictions = []

    observations_by_seed: dict[int, list[dict[str, Any]]] = {}
    observation_plan_payload: dict[str, list[dict[str, Any]]] | None = None
    query_plan_summary: dict[str, Any] | None = None
    budget_before = None
    budget_after = None
    if client.is_authenticated:
        try:
            budget_before = client.get_budget()
        except AstarAPIError:
            budget_before = None

    initial_prediction_variants = build_prediction_variants(
        round_detail=round_detail,
        floor=args.floor,
        observations_by_seed={},
        prior_strength=args.prior_strength,
        history_prior_model=history_prior_model if args.use_history_priors else None,
        history_prior_strength=args.history_prior_strength,
        sklearn_artifact=sklearn_artifact,
    )
    initial_selected_variant = select_prediction_variant(
        requested_model=args.prediction_model,
        strategy_evaluation_summary=strategy_evaluation_summary,
        strategy_feedback_summary=strategy_feedback_summary,
        prediction_variants=initial_prediction_variants,
    )
    initial_predictions = initial_prediction_variants[initial_selected_variant]
    submission_stages: list[dict[str, Any]] = []

    if should_stage_initial_submit(
        submit_enabled=args.submit,
        simulate_enabled=args.simulate,
        staged_submit_enabled=args.staged_submit,
        existing_predictions_count=len(preexisting_predictions),
    ):
        initial_stage = write_predictions_and_optionally_submit(
            artifact_store=artifact_store,
            client=client,
            round_root=round_root,
            round_id=round_id,
            round_detail=round_detail,
            predictions=initial_predictions,
            output_dirname="predictions_initial",
            submission_dirname="submissions_initial",
            write_server_state_name="my_predictions_after_initial_submit.json",
            submit_enabled=True,
        )
        initial_stage["stage"] = "initial_safe_submit"
        initial_stage["prediction_model"] = initial_selected_variant
        submission_stages.append(initial_stage)
        maybe_write_team_state(client, artifact_store, round_root, round_id, suffix="after_initial_submit")
    else:
        submission_stages.append(
            {
                "stage": "initial_safe_submit",
                "submitted": False,
                "prediction_model": initial_selected_variant,
                "reason": initial_stage_skip_reason(
                    submit_enabled=args.submit,
                    simulate_enabled=args.simulate,
                    staged_submit_enabled=args.staged_submit,
                    existing_predictions_count=len(preexisting_predictions),
                ),
                "existing_predictions_count": len(preexisting_predictions),
            }
        )

    if args.simulate:
        if not args.token:
            raise SystemExit("Missing token. --simulate requires --token or AINM_ACCESS_TOKEN.")
        planned_requests: dict[int, list[ViewportRequest]] = {seed_index: [] for seed_index in range(seeds_count)}
        observation_plan_payload = {str(seed_index): [] for seed_index in range(seeds_count)}
        plan_trace: list[dict[str, Any]] = []
        per_seed_query_index = {seed_index: 0 for seed_index in range(seeds_count)}
        for seed_index in range(seeds_count):
            observations_by_seed[seed_index] = []

        for _query_index in range(total_queries):
            planning_history_prior_model = history_prior_model
            if planning_history_prior_model is not None and any(observations_by_seed.values()):
                planning_history_prior_model, _ = infer_regime_history_prior_model(
                    history_prior_model=planning_history_prior_model,
                    round_detail=round_detail,
                    observations_by_seed=observations_by_seed,
                )
            selection = select_next_viewport_request(
                round_detail=round_detail,
                viewport_size=args.viewport_size,
                observations_by_seed=observations_by_seed,
                already_selected=planned_requests,
                history_prior_model=planning_history_prior_model,
                history_prior_strength=args.history_prior_strength,
                prior_strength=args.prior_strength,
                floor=args.floor,
            )
            if selection is None:
                break
            request = selection["request"]
            planned_requests[request.seed_index].append(request)
            payload = request.to_payload(round_id)
            observation_plan_payload[str(request.seed_index)].append(payload)
            trace_item = {
                "query_index": len(plan_trace),
                "seed_index": request.seed_index,
                "viewport_x": request.viewport_x,
                "viewport_y": request.viewport_y,
                "viewport_w": request.viewport_w,
                "viewport_h": request.viewport_h,
                "phase": selection["phase"],
                "score": float(selection["score"]),
                "score_components": selection["score_components"],
            }
            plan_trace.append(trace_item)
            response = client.simulate(payload)
            observations_by_seed[request.seed_index].append(response)
            artifact_store.write_json(
                round_root / "team" / "simulations" / f"seed_{request.seed_index}" / f"query_{per_seed_query_index[request.seed_index]:02d}.json",
                {"request": payload, "response": response, "request_meta": client.get_last_request_meta(), "plan_meta": trace_item},
            )
            per_seed_query_index[request.seed_index] += 1
            print(
                f"seed {request.seed_index}: simulated viewport "
                f"({payload['viewport_x']},{payload['viewport_y']}) "
                f"{payload['viewport_w']}x{payload['viewport_h']} "
                f"[{selection['phase']}]"
            )
        artifact_store.write_json(round_root / "team" / "observation_plan.json", observation_plan_payload)
        query_plan_summary = {
            "planner": "adaptive_information_gain_v3_triggered",
            "total_queries_requested": total_queries,
            "total_queries_planned": sum(len(requests) for requests in planned_requests.values()),
            "per_seed_queries_planned": {str(seed_index): len(requests) for seed_index, requests in planned_requests.items()},
            "phase_counts": {
                "explore": sum(1 for item in plan_trace if item["phase"] == "explore"),
                "exploit": sum(1 for item in plan_trace if item["phase"] == "exploit"),
            },
            "plan_trace": plan_trace,
        }
        artifact_store.write_json(round_root / "team" / "observation_plan_summary.json", query_plan_summary)
        maybe_write_team_state(client, artifact_store, round_root, round_id, suffix="after_simulation")
        try:
            budget_after = client.get_budget()
        except AstarAPIError:
            budget_after = None

    regime_history_prior_model = history_prior_model
    regime_summary = None
    if history_prior_model is not None:
        regime_history_prior_model, regime_summary = infer_regime_history_prior_model(
            history_prior_model=history_prior_model,
            round_detail=round_detail,
            observations_by_seed=observations_by_seed,
        )

    prediction_variants = build_prediction_variants(
        round_detail=round_detail,
        floor=args.floor,
        observations_by_seed=observations_by_seed,
        prior_strength=args.prior_strength,
        history_prior_model=regime_history_prior_model if args.use_history_priors else None,
        history_prior_strength=args.history_prior_strength,
        sklearn_artifact=sklearn_artifact,
    )
    live_variant_summary = score_prediction_variants_for_live_round(
        round_detail=round_detail,
        prediction_variants=prediction_variants,
        observations_by_seed=observations_by_seed,
        strategy_evaluation_summary=strategy_evaluation_summary,
    )
    selected_variant = select_prediction_variant(
        requested_model=args.prediction_model,
        strategy_evaluation_summary=strategy_evaluation_summary,
        strategy_feedback_summary=strategy_feedback_summary,
        prediction_variants=prediction_variants,
        live_variant_summary=live_variant_summary,
    )
    predictions = prediction_variants[selected_variant]
    guardrail_summary = None
    guardrail_anchor_variant = select_guardrail_anchor_variant(
        requested_model=args.prediction_model,
        strategy_evaluation_summary=strategy_evaluation_summary,
        strategy_feedback_summary=strategy_feedback_summary,
        prediction_variants=prediction_variants,
        selected_variant=selected_variant,
        live_variant_summary=live_variant_summary,
    )
    if guardrail_anchor_variant is not None:
        predictions, guardrail_summary = apply_prediction_mass_guardrails(
            predictions=predictions,
            anchor_predictions=prediction_variants[guardrail_anchor_variant],
            observed_summary=(live_variant_summary or {}).get("observed_summary"),
            selected_variant=selected_variant,
            anchor_variant=guardrail_anchor_variant,
        )
    prediction_model_used = selected_variant

    if regime_history_prior_model is not None:
        artifact_store.write_json(round_root / "history" / "prior_summary.json", regime_history_prior_model.to_summary())
    if regime_summary is not None:
        artifact_store.write_json(round_root / "history" / "regime_summary.json", regime_summary)
    if strategy_evaluation_summary is not None:
        artifact_store.write_json(round_root / "history" / "variant_selection.json", strategy_evaluation_summary)

    report = build_run_report(
        round_id=round_id,
        round_detail=round_detail,
        rounds=rounds,
        predictions=predictions,
        simulate_enabled=args.simulate,
        submit_enabled=args.submit,
        total_queries_requested=total_queries,
        viewport_size=args.viewport_size,
        floor=args.floor,
        prior_strength=args.prior_strength,
        query_plan_summary=query_plan_summary,
        history_summary=history_summary,
        history_prior_summary=regime_history_prior_model.to_summary() if regime_history_prior_model is not None else None,
        prediction_model=prediction_model_used,
        submission_strategy="staged_overwrite" if args.submit and args.simulate and args.staged_submit else "single_final",
        submission_stages=submission_stages,
        sklearn_training_summary=sklearn_training_summary,
        sklearn_evaluation_summary=sklearn_evaluation_summary,
        strategy_evaluation_summary=strategy_evaluation_summary,
        strategy_feedback_summary=strategy_feedback_summary,
        live_variant_summary=live_variant_summary,
        regime_summary=regime_summary,
        tuning_summary=tuning_summary,
        guardrail_summary=guardrail_summary,
        observation_plan=observation_plan_payload,
        observations_by_seed=observations_by_seed,
        budget_before=budget_before,
        budget_after=budget_after,
        request_metrics=client.get_request_metrics_summary(),
    )
    artifact_store.write_json(round_root / "report.json", report)

    final_stage = write_predictions_and_optionally_submit(
        artifact_store=artifact_store,
        client=client,
        round_root=round_root,
        round_id=round_id,
        round_detail=round_detail,
        predictions=predictions,
        output_dirname="predictions",
        submission_dirname="submissions",
        write_server_state_name="my_predictions.json",
        submit_enabled=args.submit,
    )
    final_stage["stage"] = "final_submit"
    final_stage["prediction_model"] = prediction_model_used
    submission_stages.append(final_stage)
    report["submission_stages"] = submission_stages
    artifact_store.write_json(round_root / "report.json", report)


def maybe_write_team_state(
    client: AstarClient,
    artifact_store: ArtifactStore,
    round_root: Path,
    round_id: str,
    suffix: str = "initial",
) -> None:
    if not client.is_authenticated:
        return
    try:
        artifact_store.write_json(round_root / "team" / f"budget_{suffix}.json", client.get_budget())
        artifact_store.write_json(round_root / "team" / f"my_rounds_{suffix}.json", client.get_my_rounds())
    except AstarAPIError as exc:
        print(f"warning: unable to fetch authenticated team state: {exc}")
    try:
        artifact_store.write_json(round_root / "team" / f"my_predictions_{suffix}.json", client.get_my_predictions(round_id))
    except AstarAPIError:
        # No submission yet is fine.
        pass


def find_active_round_id(rounds: list[dict[str, Any]]) -> str:
    for round_item in rounds:
        if round_item.get("status") == "active":
            return str(round_item["id"])
    if rounds:
        latest_round = max(rounds, key=lambda item: (item.get("event_date", ""), int(item.get("round_number", 0))))
        raise SystemExit(
            "No active round found. "
            f"Pass --round-id explicitly, for example --round-id {latest_round['id']} "
            f"(latest round status: {latest_round.get('status')})."
        )
    raise SystemExit("No active round found and /rounds returned no data.")


def should_stage_initial_submit(
    *,
    submit_enabled: bool,
    simulate_enabled: bool,
    staged_submit_enabled: bool,
    existing_predictions_count: int,
) -> bool:
    return (
        submit_enabled
        and simulate_enabled
        and staged_submit_enabled
        and int(existing_predictions_count) <= 0
    )


def initial_stage_skip_reason(
    *,
    submit_enabled: bool,
    simulate_enabled: bool,
    staged_submit_enabled: bool,
    existing_predictions_count: int,
) -> str:
    if not submit_enabled:
        return "submit_disabled"
    if not simulate_enabled:
        return "simulate_disabled"
    if not staged_submit_enabled:
        return "staged_submit_disabled"
    if int(existing_predictions_count) > 0:
        return "preexisting_server_predictions"
    return "not_applicable"


def write_predictions_and_optionally_submit(
    *,
    artifact_store: ArtifactStore,
    client: AstarClient,
    round_root: Path,
    round_id: str,
    round_detail: dict[str, Any],
    predictions: list[Any],
    output_dirname: str,
    submission_dirname: str,
    write_server_state_name: str,
    submit_enabled: bool,
) -> dict[str, Any]:
    written_predictions = 0
    submitted_predictions = 0
    for seed_index, prediction in enumerate(predictions):
        validate_prediction_array(
            prediction,
            expected_height=int(round_detail["map_height"]),
            expected_width=int(round_detail["map_width"]),
        )
        payload = {
            "round_id": round_id,
            "seed_index": seed_index,
            "prediction": prediction.tolist(),
        }
        output_path = artifact_store.write_json(round_root / output_dirname / f"seed_{seed_index}.json", payload)
        written_predictions += 1
        print(f"seed {seed_index}: wrote {output_path}")
        if not submit_enabled:
            continue
        validate_submission_payload(
            payload,
            expected_round_id=round_id,
            expected_height=int(round_detail["map_height"]),
            expected_width=int(round_detail["map_width"]),
        )
        response = client.submit_prediction(payload)
        artifact_store.write_json(
            round_root / "team" / submission_dirname / f"seed_{seed_index}.json",
            {"request": payload, "response": response, "request_meta": client.get_last_request_meta()},
        )
        submitted_predictions += 1
        print(f"seed {seed_index}: submit response {response}")
    if submit_enabled:
        try:
            predictions_state = client.get_my_predictions(round_id)
            artifact_store.write_json(round_root / "team" / write_server_state_name, predictions_state)
        except AstarAPIError as exc:
            print(f"warning: unable to fetch {write_server_state_name} after submit: {exc}")
    return {
        "submitted": bool(submit_enabled),
        "predictions_written": written_predictions,
        "predictions_submitted": submitted_predictions,
        "output_dirname": output_dirname,
        "submission_dirname": submission_dirname,
    }


def resolve_total_queries(args: argparse.Namespace, seeds_count: int) -> int:
    if args.queries_per_seed is not None:
        return int(args.queries_per_seed) * seeds_count
    return int(args.total_queries)


def resolve_sklearn_model_path(args: argparse.Namespace) -> Path:
    if args.sklearn_model_path:
        return Path(args.sklearn_model_path)
    return Path(args.out_dir) / "models" / "astar_random_forest.pkl"


def resolve_sklearn_evaluation_output(args: argparse.Namespace) -> Path:
    if args.sklearn_evaluation_output:
        return Path(args.sklearn_evaluation_output)
    return Path(args.out_dir) / args.history_cache_prefix / "sklearn_evaluation.json"


def maybe_prepare_sklearn_model(
    *,
    args: argparse.Namespace,
    sklearn_model_path: Path,
    sklearn_evaluation_output: Path,
    history_summary: dict[str, Any] | None,
    exclude_round_ids: set[str] | None,
    is_active_round: bool,
) -> tuple[Any | None, dict[str, Any] | None, dict[str, Any] | None]:
    analysis_seeds = int(history_summary.get("analysis_cached_seeds", 0)) if history_summary else 0
    if analysis_seeds <= 0:
        if args.prediction_model == "sklearn":
            raise SystemExit("No completed-round /analysis cache is available for sklearn training.")
        return None, None, None

    expected_history_round_ids = load_expected_history_round_ids(
        root=args.out_dir,
        cache_prefix=args.history_cache_prefix,
        exclude_round_ids=exclude_round_ids,
    )
    cached_training_summary = load_cached_training_summary(sklearn_model_path=sklearn_model_path)
    cached_model_current = cached_training_summary is not None and cached_training_summary_matches_history(
        cached_training_summary=cached_training_summary,
        expected_history_round_ids=expected_history_round_ids,
        neighborhood_radius=args.neighborhood_radius,
        n_estimators=args.sklearn_n_estimators,
        min_samples_leaf=args.sklearn_min_samples_leaf,
        random_state=args.sklearn_random_state,
    )
    cached_evaluation = load_cached_sklearn_evaluation(
        sklearn_evaluation_output=sklearn_evaluation_output,
        expected_history_round_ids=expected_history_round_ids,
        neighborhood_radius=args.neighborhood_radius,
        n_estimators=args.sklearn_n_estimators,
        min_samples_leaf=args.sklearn_min_samples_leaf,
        random_state=args.sklearn_random_state,
    )

    try:
        if cached_model_current:
            artifact = load_model_artifact(sklearn_model_path)
            training_summary = dict(cached_training_summary or artifact.to_metadata())
            training_summary["model_path"] = str(sklearn_model_path)
            training_summary["metadata_path"] = str(sklearn_model_path.with_name(f"{sklearn_model_path.stem}.metadata.json"))
            print(f"sklearn model: loaded current cached model from {sklearn_model_path}")
            if args.evaluate_sklearn and cached_evaluation is not None:
                print(
                    "sklearn evaluation: loaded cached report "
                    f"covering {cached_evaluation['summary']['completed_rounds_evaluated']} completed rounds"
                )
            elif args.evaluate_sklearn and is_active_round:
                print("sklearn evaluation: skipped live offline reevaluation for active round")
            return artifact, training_summary, cached_evaluation

        if args.retrain_sklearn or not sklearn_model_path.exists():
            artifact = train_random_forest_from_history(
                root=args.out_dir,
                cache_prefix=args.history_cache_prefix,
                neighborhood_radius=args.neighborhood_radius,
                exclude_round_ids=exclude_round_ids,
                n_estimators=args.sklearn_n_estimators,
                min_samples_leaf=args.sklearn_min_samples_leaf,
                random_state=args.sklearn_random_state,
            )
            model_paths = save_model_artifact(artifact, sklearn_model_path)
            training_summary = artifact.to_metadata()
            training_summary["model_path"] = model_paths["model_path"]
            training_summary["metadata_path"] = model_paths["metadata_path"]
            print(
                "sklearn model: trained "
                f"{training_summary['records_used']} records across {training_summary['rounds_used']} completed rounds"
            )
            if args.evaluate_sklearn:
                if is_active_round:
                    print("sklearn evaluation: skipped live offline reevaluation for active round")
                    return artifact, training_summary, cached_evaluation
                evaluation = evaluate_sklearn_history(
                    root=args.out_dir,
                    cache_prefix=args.history_cache_prefix,
                    floor=args.floor,
                    neighborhood_radius=args.neighborhood_radius,
                    n_estimators=args.sklearn_n_estimators,
                    min_samples_leaf=args.sklearn_min_samples_leaf,
                    random_state=args.sklearn_random_state,
                )
                sklearn_evaluation_output.parent.mkdir(parents=True, exist_ok=True)
                sklearn_evaluation_output.write_text(json.dumps(evaluation, indent=2, sort_keys=True))
                print(
                    "sklearn evaluation: "
                    f"mean round score {evaluation['summary']['mean_round_score']:.3f} "
                    f"over {evaluation['summary']['completed_rounds_evaluated']} completed rounds"
                )
                return artifact, training_summary, evaluation
            return artifact, training_summary, None

        artifact = load_model_artifact(sklearn_model_path)
        training_summary = artifact.to_metadata()
        training_summary["model_path"] = str(sklearn_model_path)
        training_summary["metadata_path"] = str(sklearn_model_path.with_name(f"{sklearn_model_path.stem}.metadata.json"))
        print(f"sklearn model: loaded {sklearn_model_path}")
        evaluation = cached_evaluation
        if args.evaluate_sklearn and evaluation is not None:
            print(
                "sklearn evaluation: loaded cached report "
                f"covering {evaluation['summary']['completed_rounds_evaluated']} completed rounds"
            )
        return artifact, training_summary, evaluation
    except SystemExit:
        if args.prediction_model == "sklearn":
            raise
        print("warning: sklearn model unavailable; falling back to baseline predictions")
        return None, None, None


def load_expected_history_round_ids(
    *,
    root: str | Path,
    cache_prefix: str,
    exclude_round_ids: set[str] | None,
) -> list[str]:
    index = load_history_index(root=root, cache_prefix=cache_prefix) or {}
    return history_round_ids_with_analysis(index, exclude_round_ids=exclude_round_ids)


def load_cached_training_summary(*, sklearn_model_path: Path) -> dict[str, Any] | None:
    metadata_path = sklearn_model_path.with_name(f"{sklearn_model_path.stem}.metadata.json")
    if not metadata_path.exists():
        return None
    try:
        return json.loads(metadata_path.read_text())
    except json.JSONDecodeError:
        return None


def cached_training_summary_matches_history(
    *,
    cached_training_summary: dict[str, Any],
    expected_history_round_ids: list[str],
    neighborhood_radius: int,
    n_estimators: int,
    min_samples_leaf: int,
    random_state: int,
) -> bool:
    cached_round_ids = [str(item) for item in cached_training_summary.get("round_ids", [])]
    if len(cached_round_ids) != len(expected_history_round_ids):
        return False
    if set(cached_round_ids) != set(expected_history_round_ids):
        return False
    if int(cached_training_summary.get("neighborhood_radius", -1)) != int(neighborhood_radius):
        return False
    if int(cached_training_summary.get("n_estimators", -1)) != int(n_estimators):
        return False
    if int(cached_training_summary.get("min_samples_leaf", -1)) != int(min_samples_leaf):
        return False
    if int(cached_training_summary.get("random_state", -1)) != int(random_state):
        return False
    return True


def load_cached_sklearn_evaluation(
    *,
    sklearn_evaluation_output: Path,
    expected_history_round_ids: list[str],
    neighborhood_radius: int,
    n_estimators: int,
    min_samples_leaf: int,
    random_state: int,
) -> dict[str, Any] | None:
    if not sklearn_evaluation_output.exists():
        return None
    try:
        cached = json.loads(sklearn_evaluation_output.read_text())
    except json.JSONDecodeError:
        return None
    cached_round_ids = [str(item.get("round_id")) for item in cached.get("rounds", [])]
    summary = cached.get("summary", {})
    if len(cached_round_ids) != len(expected_history_round_ids):
        return None
    if set(cached_round_ids) != set(expected_history_round_ids):
        return None
    if int(summary.get("neighborhood_radius", -1)) != int(neighborhood_radius):
        return None
    if int(summary.get("n_estimators", -1)) != int(n_estimators):
        return None
    if int(summary.get("min_samples_leaf", -1)) != int(min_samples_leaf):
        return None
    if int(summary.get("random_state", -1)) != int(random_state):
        return None
    return cached


def maybe_resolve_tuned_baseline_settings(
    *,
    args: argparse.Namespace,
    history_summary: dict[str, Any] | None,
    is_active_round: bool,
) -> dict[str, Any] | None:
    if history_summary is None or int(history_summary.get("analysis_cached_seeds", 0) or 0) <= 0:
        return None
    if args.floor != DEFAULT_PREDICTION_FLOOR or args.history_prior_strength != DEFAULT_HISTORY_PRIOR_STRENGTH:
        return {
            "applied": False,
            "reason": "explicit_cli_override",
            "floor": float(args.floor),
            "history_prior_strength": float(args.history_prior_strength),
        }
    tuning_output = Path(args.out_dir) / args.history_cache_prefix / "tuning.json"
    cached = load_cached_tuning_report(tuning_output=tuning_output, history_summary=history_summary)
    cache_status = "current_cache"
    if cached is None:
        if is_active_round:
            cached = load_any_cached_tuning_report(tuning_output=tuning_output)
            if cached is not None:
                cache_status = "stale_cache_active_round"
            else:
                return {
                    "applied": False,
                    "reason": "skipped_for_active_round",
                    "floor": float(args.floor),
                    "history_prior_strength": float(args.history_prior_strength),
                }
        else:
            cached = tune_baseline_from_history(root=args.out_dir, cache_prefix=args.history_cache_prefix)
            tuning_output.parent.mkdir(parents=True, exist_ok=True)
            tuning_output.write_text(json.dumps(cached, indent=2, sort_keys=True))
            cache_status = "recomputed"
    best = cached.get("best") or {}
    if "floor" in best:
        args.floor = float(best["floor"])
    if "history_prior_strength" in best:
        args.history_prior_strength = float(best["history_prior_strength"])
    return {
        "applied": True,
        "floor": float(args.floor),
        "history_prior_strength": float(args.history_prior_strength),
        "tuning_report": str(tuning_output),
        "cache_status": cache_status,
        "best": best,
    }


def select_prediction_variant(
    *,
    requested_model: str,
    strategy_evaluation_summary: dict[str, Any] | None,
    strategy_feedback_summary: dict[str, Any] | None,
    prediction_variants: dict[str, list[Any]],
    live_variant_summary: dict[str, Any] | None = None,
) -> str:
    if requested_model == "sklearn" and "sklearn" in prediction_variants:
        return "sklearn"
    if requested_model == "baseline":
        for variant_name in ("baseline_history", "baseline_static"):
            if variant_name in prediction_variants:
                return variant_name
        raise SystemExit("Baseline prediction variant was requested but is unavailable.")

    blocked_variants = set((strategy_feedback_summary or {}).get("blocked_variants", []))
    offline_ranked_variants = ranked_available_variants(
        strategy_evaluation_summary=strategy_evaluation_summary,
        prediction_variants=prediction_variants,
        blocked_variants=blocked_variants,
    )
    ambiguous_fallback = select_ambiguous_live_fallback(
        prediction_variants=prediction_variants,
        blocked_variants=blocked_variants,
        offline_ranked_variants=offline_ranked_variants,
    )

    if live_variant_summary is not None:
        low_activity_variant = select_low_activity_live_variant(
            live_variant_summary=live_variant_summary,
            prediction_variants=prediction_variants,
            blocked_variants=blocked_variants,
        )
        moderate_sparse_variant = select_moderately_sparse_live_variant(
            live_variant_summary=live_variant_summary,
            prediction_variants=prediction_variants,
            blocked_variants=blocked_variants,
        )
        live_ranked_variants = [
            item
            for item in live_variant_summary.get("variants", [])
            if str(item.get("variant")) not in blocked_variants and str(item.get("variant")) in prediction_variants
        ]
        if live_ranked_variants:
            top_variant = str(live_ranked_variants[0].get("variant"))
            top_score = float(live_ranked_variants[0].get("live_score", 0.0))
            top_activity_gap = float(live_ranked_variants[0].get("activity_gap", 0.0))
            if low_activity_variant is not None and low_activity_variant in prediction_variants:
                low_activity_report = next(
                    (item for item in live_ranked_variants if str(item.get("variant")) == low_activity_variant),
                    None,
                )
                if low_activity_report is not None:
                    low_activity_score = float(low_activity_report.get("live_score", 0.0))
                    if (top_score - low_activity_score) <= 0.03:
                        return low_activity_variant
            if moderate_sparse_variant is not None and _is_aggressive_live_variant(top_variant):
                moderate_sparse_report = next(
                    (item for item in live_ranked_variants if str(item.get("variant")) == moderate_sparse_variant),
                    None,
                )
                if moderate_sparse_report is not None:
                    moderate_sparse_score = float(moderate_sparse_report.get("live_score", 0.0))
                    moderate_sparse_gap = float(moderate_sparse_report.get("activity_gap", 0.0))
                    if (top_score - moderate_sparse_score) <= 0.08 and moderate_sparse_gap <= (top_activity_gap - 0.02):
                        return moderate_sparse_variant
            if ambiguous_fallback is None or top_variant == ambiguous_fallback:
                return top_variant
            fallback_report = next(
                (item for item in live_ranked_variants if str(item.get("variant")) == ambiguous_fallback),
                None,
            )
            if fallback_report is None:
                return top_variant
            second_score = float(live_ranked_variants[1].get("live_score", 0.0)) if len(live_ranked_variants) > 1 else float("-inf")
            fallback_score = float(fallback_report.get("live_score", 0.0))
            top_match = float(live_ranked_variants[0].get("observation_match", 0.0))
            fallback_match = float(fallback_report.get("observation_match", 0.0))
            fallback_activity_gap = float(fallback_report.get("activity_gap", 0.0))
            margin_to_second = top_score - second_score if second_score != float("-inf") else top_score
            margin_to_fallback = top_score - fallback_score
            if top_variant == "sklearn":
                raw_override_allowed = (
                    margin_to_second >= 0.06
                    and margin_to_fallback >= 0.10
                    and (top_match - fallback_match) >= 0.05
                    and top_activity_gap <= (fallback_activity_gap - 0.02)
                )
                if not raw_override_allowed:
                    return ambiguous_fallback
                return top_variant
            if margin_to_second < 0.03 and margin_to_fallback < 0.04:
                return ambiguous_fallback
            return top_variant

    if offline_ranked_variants:
        return offline_ranked_variants[0]

    for fallback in ("sklearn_learned_post_observation", "sklearn_observation_context", "ensemble_observation_context_50", "ensemble_sklearn_50", "sklearn", "baseline_history", "baseline_static"):
        if fallback in prediction_variants:
            return fallback
    raise SystemExit("No prediction variants were built.")


def ranked_available_variants(
    *,
    strategy_evaluation_summary: dict[str, Any] | None,
    prediction_variants: dict[str, list[Any]],
    blocked_variants: set[str],
) -> list[str]:
    ranked: list[str] = []
    if strategy_evaluation_summary is not None:
        for variant_item in sorted(
            strategy_evaluation_summary.get("summary", {}).get("variants", []),
            key=lambda item: float(item.get("mean_round_score", 0.0)),
            reverse=True,
        ):
            variant_name = str(variant_item.get("variant"))
            if variant_name in blocked_variants or variant_name not in prediction_variants or variant_name in ranked:
                continue
            ranked.append(variant_name)
    for fallback in (
        "sklearn_learned_post_observation",
        "sklearn_observation_context",
        "ensemble_observation_context_50",
        "sklearn_global_post_observation",
        "ensemble_global_post_observation_50",
        "sklearn",
        "ensemble_sklearn_75",
        "ensemble_sklearn_50",
        "baseline_history_observation_context",
        "baseline_history_global_post_observation",
        "baseline_history",
        "baseline_static",
    ):
        if fallback in blocked_variants or fallback not in prediction_variants or fallback in ranked:
            continue
        ranked.append(fallback)
    return ranked


def select_ambiguous_live_fallback(
    *,
    prediction_variants: dict[str, list[Any]],
    blocked_variants: set[str],
    offline_ranked_variants: list[str],
) -> str | None:
    for preferred in (
        "sklearn_learned_post_observation",
        "sklearn_observation_context",
        "ensemble_observation_context_50",
        "sklearn_global_post_observation",
        "ensemble_global_post_observation_50",
    ):
        if preferred in prediction_variants and preferred not in blocked_variants:
            return preferred
    return offline_ranked_variants[0] if offline_ranked_variants else None


def select_low_activity_live_variant(
    *,
    live_variant_summary: dict[str, Any],
    prediction_variants: dict[str, list[Any]],
    blocked_variants: set[str],
) -> str | None:
    observed_summary = live_variant_summary.get("observed_summary", {}) or {}
    class_probs = observed_summary.get("class_probs", []) or []
    if len(class_probs) < 4:
        return None
    observed_dynamic_mass = float(class_probs[1] + class_probs[2] + class_probs[3])
    if observed_dynamic_mass > 0.04:
        return None

    preferred_candidates = (
        "baseline_history_observation_context",
        "baseline_history_global_post_observation",
        "ensemble_observation_context_50",
        "sklearn_observation_context",
    )
    live_reports = {
        str(item.get("variant")): item
        for item in live_variant_summary.get("variants", [])
        if str(item.get("variant")) in prediction_variants and str(item.get("variant")) not in blocked_variants
    }
    ranked_candidates: list[tuple[float, float, float, str]] = []
    for variant_name in preferred_candidates:
        if variant_name not in live_reports:
            continue
        report = live_reports[variant_name]
        class_mass = aggregate_prediction_class_mass(prediction_variants[variant_name])
        dynamic_mass = float(class_mass[1] + class_mass[2] + class_mass[3])
        ranked_candidates.append(
            (
                float(report.get("live_score", 0.0)),
                -dynamic_mass,
                float(report.get("offline_mean_round_score", 0.0)),
                variant_name,
            )
        )
    if not ranked_candidates:
        return None
    ranked_candidates.sort(reverse=True)
    best_live = ranked_candidates[0][0]
    eligible = [item for item in ranked_candidates if (best_live - item[0]) <= 0.015]
    eligible.sort(key=lambda item: (-item[1], -item[2], -item[0]))
    return eligible[0][3]


def select_moderately_sparse_live_variant(
    *,
    live_variant_summary: dict[str, Any],
    prediction_variants: dict[str, list[Any]],
    blocked_variants: set[str],
) -> str | None:
    observed_summary = live_variant_summary.get("observed_summary", {}) or {}
    class_probs = observed_summary.get("class_probs", []) or []
    if len(class_probs) < 4:
        return None
    observed_dynamic_mass = float(class_probs[1] + class_probs[2] + class_probs[3])
    development_signal = float(observed_summary.get("development_signal", 0.0))
    trade_signal = float(max(observed_summary.get("trade_signal", 0.0), observed_summary.get("port_signal", 0.0)))
    harshness_signal = float(observed_summary.get("harshness_signal", 0.0))
    if observed_dynamic_mass <= 0.04 or observed_dynamic_mass > 0.08:
        return None
    if development_signal > 0.09 or trade_signal > 0.05 or harshness_signal < 0.35:
        return None

    preferred_candidates = (
        "ensemble_observation_context_50",
        "ensemble_global_post_observation_50",
        "sklearn_global_post_observation",
        "sklearn_observation_context",
        "baseline_history_observation_context",
        "baseline_history_global_post_observation",
    )
    live_reports = {
        str(item.get("variant")): item
        for item in live_variant_summary.get("variants", [])
        if str(item.get("variant")) in prediction_variants and str(item.get("variant")) not in blocked_variants
    }
    candidate_reports = [live_reports[variant_name] for variant_name in preferred_candidates if variant_name in live_reports]
    if not candidate_reports:
        return None

    min_activity_gap = min(float(item.get("activity_gap", 0.0)) for item in candidate_reports)
    best_live_score = max(float(item.get("live_score", 0.0)) for item in candidate_reports)
    eligible_reports = [
        item
        for item in candidate_reports
        if float(item.get("activity_gap", 0.0)) <= (min_activity_gap + 0.01)
        and float(item.get("live_score", 0.0)) >= (best_live_score - 0.02)
    ]
    if not eligible_reports:
        eligible_reports = candidate_reports
    eligible_reports.sort(
        key=lambda item: (
            float(item.get("offline_mean_round_score", 0.0)),
            float(item.get("live_score", 0.0)),
            -float(item.get("activity_gap", 0.0)),
        ),
        reverse=True,
    )
    return str(eligible_reports[0].get("variant"))


def _is_aggressive_live_variant(variant_name: str) -> bool:
    return variant_name in {
        "sklearn",
        "sklearn_rare_class_lift",
        "ensemble_sklearn_25",
        "ensemble_sklearn_50",
        "ensemble_sklearn_75",
    }


def select_guardrail_anchor_variant(
    *,
    requested_model: str,
    strategy_evaluation_summary: dict[str, Any] | None,
    strategy_feedback_summary: dict[str, Any] | None,
    prediction_variants: dict[str, list[Any]],
    selected_variant: str,
    live_variant_summary: dict[str, Any] | None = None,
) -> str | None:
    if requested_model != "auto":
        return None
    blocked_variants = set((strategy_feedback_summary or {}).get("blocked_variants", []))
    if live_variant_summary is not None and _is_aggressive_live_variant(selected_variant):
        low_activity_anchor = select_low_activity_live_variant(
            live_variant_summary=live_variant_summary,
            prediction_variants=prediction_variants,
            blocked_variants=blocked_variants,
        )
        if low_activity_anchor is not None and low_activity_anchor != selected_variant:
            return low_activity_anchor
        moderate_sparse_anchor = select_moderately_sparse_live_variant(
            live_variant_summary=live_variant_summary,
            prediction_variants=prediction_variants,
            blocked_variants=blocked_variants,
        )
        if moderate_sparse_anchor is not None and moderate_sparse_anchor != selected_variant:
            return moderate_sparse_anchor
    offline_ranked_variants = ranked_available_variants(
        strategy_evaluation_summary=strategy_evaluation_summary,
        prediction_variants=prediction_variants,
        blocked_variants=blocked_variants,
    )
    fallback = select_ambiguous_live_fallback(
        prediction_variants=prediction_variants,
        blocked_variants=blocked_variants,
        offline_ranked_variants=offline_ranked_variants,
    )
    if fallback is None or fallback == selected_variant:
        return None
    return fallback


def aggregate_prediction_class_mass(predictions: list[np.ndarray]) -> np.ndarray:
    totals = np.zeros(6, dtype=float)
    total_cells = 0
    for prediction in predictions:
        totals += np.asarray(prediction, dtype=float).sum(axis=(0, 1))
        total_cells += int(prediction.shape[0] * prediction.shape[1])
    if total_cells <= 0:
        return totals
    return totals / float(total_cells)


def apply_prediction_mass_guardrails(
    *,
    predictions: list[np.ndarray],
    anchor_predictions: list[np.ndarray],
    observed_summary: dict[str, Any] | None,
    selected_variant: str,
    anchor_variant: str,
) -> tuple[list[np.ndarray], dict[str, Any] | None]:
    if len(predictions) != len(anchor_predictions):
        return predictions, None
    selected_mass = aggregate_prediction_class_mass(predictions)
    anchor_mass = aggregate_prediction_class_mass(anchor_predictions)
    observed_summary = observed_summary or {}
    development = float(np.clip(observed_summary.get("development_signal", 0.0), 0.0, 1.0))
    trade = float(np.clip(max(observed_summary.get("trade_signal", 0.0), observed_summary.get("port_signal", 0.0)), 0.0, 1.0))
    conflict = float(np.clip(observed_summary.get("conflict_signal", 0.0), 0.0, 1.0))
    harshness = float(np.clip(observed_summary.get("harshness_signal", 0.0), 0.0, 1.0))

    max_allowed = np.array(selected_mass, copy=True)
    max_allowed[1] = max(anchor_mass[1] * (1.45 + 0.25 * development), anchor_mass[1] + 0.04 + 0.04 * development)
    max_allowed[2] = max(anchor_mass[2] * (1.60 + 0.40 * trade), anchor_mass[2] + 0.004 + 0.025 * trade)
    max_allowed[3] = max(anchor_mass[3] * (1.60 + 0.30 * max(conflict, harshness)), anchor_mass[3] + 0.004 + 0.02 * max(conflict, harshness))
    min_empty = max(0.20, anchor_mass[0] - (0.05 + 0.05 * development + 0.03 * trade))

    alpha = 1.0
    constraints: list[dict[str, float | int]] = []
    for class_index in (1, 2, 3):
        if selected_mass[class_index] <= max_allowed[class_index] or selected_mass[class_index] <= anchor_mass[class_index]:
            continue
        denom = selected_mass[class_index] - anchor_mass[class_index]
        if denom <= 0:
            continue
        bound = float((max_allowed[class_index] - anchor_mass[class_index]) / denom)
        alpha = min(alpha, bound)
        constraints.append(
            {
                "class_index": class_index,
                "selected_mass": float(selected_mass[class_index]),
                "anchor_mass": float(anchor_mass[class_index]),
                "max_allowed_mass": float(max_allowed[class_index]),
                "alpha_bound": float(bound),
            }
        )
    if selected_mass[0] < min_empty and selected_mass[0] < anchor_mass[0]:
        denom = anchor_mass[0] - selected_mass[0]
        if denom > 0:
            bound = float((anchor_mass[0] - min_empty) / denom)
            alpha = min(alpha, bound)
            constraints.append(
                {
                    "class_index": 0,
                    "selected_mass": float(selected_mass[0]),
                    "anchor_mass": float(anchor_mass[0]),
                    "min_allowed_mass": float(min_empty),
                    "alpha_bound": float(bound),
                }
            )
    alpha = float(np.clip(alpha, 0.0, 1.0))
    if alpha >= 0.999 or not constraints:
        return predictions, None

    guarded_predictions: list[np.ndarray] = []
    for prediction, anchor in zip(predictions, anchor_predictions, strict=True):
        tensor = (np.asarray(prediction, dtype=float) * alpha) + (np.asarray(anchor, dtype=float) * (1.0 - alpha))
        tensor = np.clip(tensor, 1e-12, None)
        tensor /= tensor.sum(axis=-1, keepdims=True)
        guarded_predictions.append(tensor)
    final_mass = aggregate_prediction_class_mass(guarded_predictions)
    return guarded_predictions, {
        "applied": True,
        "selected_variant": selected_variant,
        "anchor_variant": anchor_variant,
        "blend_alpha": alpha,
        "selected_class_mass": selected_mass.tolist(),
        "anchor_class_mass": anchor_mass.tolist(),
        "final_class_mass": final_mass.tolist(),
        "constraints": constraints,
    }


def load_cached_strategy_evaluation(
    *,
    strategy_evaluation_output: Path,
    history_summary: dict[str, Any] | None,
    floor: float,
    prior_strength: float,
    history_prior_strength: float,
    neighborhood_radius: int,
    n_estimators: int,
    min_samples_leaf: int,
    random_state: int,
    simulate_queries: int,
    viewport_size: int,
) -> dict[str, Any] | None:
    if history_summary is None or not strategy_evaluation_output.exists():
        return None
    try:
        cached = json.loads(strategy_evaluation_output.read_text())
    except json.JSONDecodeError:
        return None
    summary = cached.get("summary", {})
    cached_round_ids = list(summary.get("history_round_ids", []))
    current_round_ids = history_round_ids_with_analysis(history_summary)
    if cached_round_ids != current_round_ids:
        return None
    expected_signature = strategy_signature(
        history_round_ids=current_round_ids,
        floor=floor,
        prior_strength=prior_strength,
        history_prior_strength=history_prior_strength,
        neighborhood_radius=neighborhood_radius,
        n_estimators=n_estimators,
        min_samples_leaf=min_samples_leaf,
        random_state=random_state,
        simulate_queries=simulate_queries,
        viewport_size=viewport_size,
    )
    if summary.get("strategy_signature") != expected_signature:
        return None
    return cached


def load_any_cached_strategy_evaluation(
    *,
    strategy_evaluation_output: Path,
) -> dict[str, Any] | None:
    if not strategy_evaluation_output.exists():
        return None
    try:
        return json.loads(strategy_evaluation_output.read_text())
    except json.JSONDecodeError:
        return None


def load_cached_tuning_report(
    *,
    tuning_output: Path,
    history_summary: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if history_summary is None or not tuning_output.exists():
        return None
    try:
        cached = json.loads(tuning_output.read_text())
    except json.JSONDecodeError:
        return None
    cached_round_ids = list(cached.get("history_round_ids", []))
    current_round_ids = history_round_ids_with_analysis(history_summary)
    if cached_round_ids != current_round_ids:
        return None
    return cached


def load_any_cached_tuning_report(*, tuning_output: Path) -> dict[str, Any] | None:
    if not tuning_output.exists():
        return None
    try:
        return json.loads(tuning_output.read_text())
    except json.JSONDecodeError:
        return None


def load_strategy_feedback_summary(*, root: Path, max_rounds: int = 5) -> dict[str, Any]:
    feedback_items = []
    for feedback_path in sorted(root.glob("*/team/score_feedback.json")):
        try:
            payload = json.loads(feedback_path.read_text())
        except json.JSONDecodeError:
            continue
        feedback_items.append(payload)
    feedback_items = sorted(feedback_items, key=lambda item: str(item.get("round_id")), reverse=True)[:max_rounds]
    regressions_by_variant: dict[str, int] = {}
    for item in feedback_items:
        variant = item.get("selected_variant")
        if not variant:
            continue
        if item.get("regression_flags"):
            regressions_by_variant[str(variant)] = regressions_by_variant.get(str(variant), 0) + 1
    blocked_variants = sorted([variant for variant, count in regressions_by_variant.items() if count >= 2])
    return {
        "recent_rounds_considered": len(feedback_items),
        "regressions_by_variant": regressions_by_variant,
        "blocked_variants": blocked_variants,
    }


if __name__ == "__main__":
    main()

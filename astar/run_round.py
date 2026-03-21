from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

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
from history_cache import load_history_index, summarize_history_cache, sync_history_cache
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

    tuning_summary = maybe_resolve_tuned_baseline_settings(args=args, history_summary=history_summary)

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
            "planner": "adaptive_information_gain_v2",
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
    round_ids = []
    excluded = {str(item) for item in (exclude_round_ids or set())}
    for round_entry in index.get("rounds", []):
        round_id = str(round_entry["round_id"])
        if round_id in excluded:
            continue
        round_ids.append(round_id)
    return round_ids


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
    if cached is None:
        cached = tune_baseline_from_history(root=args.out_dir, cache_prefix=args.history_cache_prefix)
        tuning_output.parent.mkdir(parents=True, exist_ok=True)
        tuning_output.write_text(json.dumps(cached, indent=2, sort_keys=True))
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
    if live_variant_summary is not None:
        for variant_item in live_variant_summary.get("variants", []):
            variant_name = str(variant_item.get("variant"))
            if variant_name in blocked_variants:
                continue
            if variant_name in prediction_variants:
                return variant_name

    if strategy_evaluation_summary is not None:
        ranked_variants = sorted(
            strategy_evaluation_summary.get("summary", {}).get("variants", []),
            key=lambda item: float(item.get("mean_round_score", 0.0)),
            reverse=True,
        )
        for variant_item in ranked_variants:
            variant_name = str(variant_item.get("variant"))
            if variant_name in blocked_variants:
                continue
            if variant_name in prediction_variants:
                return variant_name

    for fallback in ("ensemble_sklearn_50", "sklearn", "baseline_history", "baseline_static"):
        if fallback in prediction_variants:
            return fallback
    raise SystemExit("No prediction variants were built.")


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
    current_round_ids = [str(item["round_id"]) for item in history_summary.get("rounds", [])]
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
    current_round_ids = [str(item["round_id"]) for item in history_summary.get("rounds", [])]
    if cached_round_ids != current_round_ids:
        return None
    return cached


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

# Astar Island Master Task List

This file is the working checklist for completing the Astar assignment end to end. Keep it aligned with the local reference docs and update statuses as implementation progresses.

## 1. Core References

Read these first and keep them open while working:

- [README.md](README.md): current scaffold, local commands, deployment entrypoints, and the intended day-to-day workflow.
- [ANALYSIS.md](ANALYSIS.md): task interpretation, scoring implications, modeling roadmap, and the distinction between solved scaffolding and unsolved modeling work.
- [API.md](API.md): endpoint contracts, payload shapes, class mapping, budget semantics, and practical API usage pattern.
- [COMPONENTS.md](COMPONENTS.md): recommended GCP architecture, component tradeoffs, and Python library guidance.
- [RUNBOOK.md](RUNBOOK.md): round-day operating procedure, recovery flow, and local-versus-cloud guidance.

The most important cross-checks:

- Use [ANALYSIS.md](ANALYSIS.md) sections 5-9 to decide what the solver still needs.
- Use [API.md](API.md) sections 5-12 to validate every payload, query, and submission assumption.
- Use [COMPONENTS.md](COMPONENTS.md) sections 1-5 to avoid building duplicate infrastructure on GCP.
- Use [README.md](README.md) whenever local usage or deployment instructions change.

## 2. Definition Of Done

The Astar assignment is only meaningfully complete when all of the following are true:

- The solver can fetch the active round, collect evidence, build five valid `H x W x 6` prediction tensors, and submit them safely.
- The solver uses the 50-query budget intentionally rather than only emitting static priors.
- The prediction pipeline is calibrated for entropy-weighted KL scoring and never emits zero probabilities.
- Historical post-round data from `/analysis` is captured and reused for learning.
- The workflow can run both locally and on GCP without secret sprawl or manual babysitting.
- Artifacts, logs, and submission state are preserved well enough to debug bad rounds and improve the next one.

## 3. Current Scaffold Status

These are already present and should usually be extended rather than rewritten:

- [x] Documented scaffold and usage guide in [README.md](README.md).
- [x] Task analysis in [ANALYSIS.md](ANALYSIS.md).
- [x] API reference in [API.md](API.md).
- [x] GCP/component analysis in [COMPONENTS.md](COMPONENTS.md).
- [x] Public and authenticated API wrapper in `astar_client.py`.
- [x] Safe baseline prior plus observation blending in `baseline.py`.
- [x] Budget-aware viewport planner in `observation_strategy.py`.
- [x] Round runner and artifact writer in `run_round.py` and `artifacts.py`.
- [x] Completed-round history cache sync in `history_cache.py` and `sync_history_cache.py`.
- [x] Offline scorer, evaluation CLI, history dataset builder, and local sklearn training path.
- [x] Loop runner that watches for new rounds, records official scores, and triggers the per-round pipeline automatically.
- [x] Resume workflow for interrupted runs in `resume_round.py`.
- [x] Opinionated Cloud Run Job deployment script in `deploy_cloud_run_job.sh`.

These are not complete yet and are the real remaining work:

- [x] Strong query-planning logic.
- [ ] High-quality probabilistic model beyond heuristics.
- [x] Historical training and evaluation loop from `/analysis`.
- [x] Reliable tests, validation, and regression checks.
- [ ] Scheduled/operational GCP workflow around the current job deployment.
- [x] Competition-day runbook and fallback procedures.

## 4. Access And Environment Tasks

Reference: [README.md](README.md), [API.md](API.md) sections 2-4, [COMPONENTS.md](COMPONENTS.md) sections 3.1-3.6.

- [ ] Confirm the team has a valid `access_token` from `app.ainm.no`.
- [x] Keep the token only in `astar/.env` locally and inject it as a runtime env var if Cloud Run is used.
- [ ] Create and activate a local virtual environment and install `requirements.txt`.
- [x] Run a public dry run with `python3 run_round.py --no-simulate --no-submit`.
- [x] Run an authenticated smoke test against `budget`, `my-rounds`, and optionally `my-predictions` to verify token scope.
- [x] Decide the canonical local artifact directory and retention policy for round outputs.
- [ ] Decide whether GCS artifact upload is required now or can remain optional.
- [x] Document any machine-specific setup changes back into [README.md](README.md).

## 5. API Correctness And Runtime Hardening Tasks

Reference: [API.md](API.md) sections 4-12, [ANALYSIS.md](ANALYSIS.md) sections 7-8.

- [x] Validate that every client method matches the documented request and response shape, including type assumptions around `round_id`, `seed_index`, viewport coordinates, and prediction tensor dimensions.
- [x] Add explicit payload validation before `simulate` and `submit` calls.
- [x] Add explicit response validation for round detail, simulation output, budget state, and analysis payloads.
- [x] Add clear retry and timeout policy for network calls so transient failures do not waste a round.
- [x] Add better error messages for no active round, exhausted budget, unauthorized token, malformed submission, and closed round submission attempts.
- [ ] Ensure submission tensors always apply the probability floor and renormalization exactly once.
- [x] Add a local validation command or function that checks shape, class count, and per-cell probability sums before submission.
- [x] Persist the exact request payload used for every simulation and submission artifact.
- [x] Add lightweight run metadata such as timestamp, git commit, and config settings to artifacts for reproducibility.

## 6. Public Data Ingestion And Artifact Tasks

Reference: [ANALYSIS.md](ANALYSIS.md) sections 3, 5.1, and 7; [API.md](API.md) sections 4, 9, and 10.

- [x] Snapshot `GET /rounds` and `GET /rounds/{round_id}` for every run.
- [x] Snapshot leaderboard state for every run where public data is collected.
- [x] Snapshot team state before and after simulation, including budget and current predictions.
- [x] Define and document the expected artifact layout for one round so later training code can rely on it.
- [x] Add a pass that fetches `/my-predictions/{round_id}` after submission and stores the authoritative server-side state.
- [x] Add a post-round ingestion command that fetches `/analysis/{round_id}/{seed_index}` for all five seeds as soon as it becomes available.
- [x] Normalize and store post-round analysis outputs into a stable dataset format for learning.
- [x] Make the default round runner retrain and re-evaluate on newly synced completed rounds before predicting the current active round.
- [x] Decide whether artifacts should remain JSON-only or whether training datasets should also be materialized as parquet/csv.
Decision: JSON and JSONL are the default now; parquet remains optional for later larger-scale analysis.

## 7. Query Planning Tasks

Reference: [ANALYSIS.md](ANALYSIS.md) sections 3.3, 4, 5.2, and 6; [API.md](API.md) sections 6-7.

- [x] Replace the current heuristic viewport planner with a budgeted policy that treats the 50 simulations as a shared round-level resource.
- [x] Split query planning into exploration and exploitation phases.
- [x] Change the default exploration policy to a tiled full-map sweep before using repeated samples.
- [ ] Use the fact that hidden parameters are shared across all five seeds when allocating the first part of the budget.
- [ ] Identify which observable patterns are most informative about round-wide parameters such as growth, conflict, ruin generation, or terrain transitions.
- [x] Add support for repeated sampling of the same viewport when stochastic uncertainty is itself informative.
- [ ] Add support for revisiting a seed based on what earlier queries revealed on other seeds.
- [x] Score candidate viewports by expected information gain rather than only by settlement density.
- [ ] Track marginal value per query so the runner can stop spending budget when additional samples are not worth it.
- [x] Add guardrails so the plan never exceeds the documented budget of 50 queries total.
- [x] Persist the planned budget allocation and the realized budget allocation separately for later analysis.

## 8. Observation Accumulation And Feature Tasks

Reference: [ANALYSIS.md](ANALYSIS.md) sections 5.3-5.4 and 9; [API.md](API.md) sections 5 and 7.

- [ ] Design a stable in-memory representation for simulation evidence across repeated samples.
- [ ] Aggregate observed class counts per cell and per time horizon rather than overwriting with the latest sample.
- [x] Store uncertainty summaries for cells that were observed multiple times with different outcomes.
- [x] Build round-level summary features from simulation outputs, not just per-cell counts.
- [x] Build seed-level summary features that describe coastlines, initial settlements, mountain barriers, forest density, and expansion corridors.
- [x] Derive features that capture neighborhood structure and likely interaction fronts between settlements.
- [x] Keep a clean mapping from raw terrain codes to submission classes so training and inference use the same conventions.
- [x] Add dataset serialization utilities so observations can be reused in offline experiments without rerunning API calls.

## 9. Baseline Improvement Tasks

Reference: [ANALYSIS.md](ANALYSIS.md) sections 2, 4, 6.1, and 6.2; [API.md](API.md) section 11.

- [ ] Audit the current prior in `baseline.py` against the actual mechanics and identify where it is overconfident or structurally wrong.
- [ ] Improve the prior for static terrain classes such as mountains and forests where public initial state is already informative.
- [ ] Improve treatment of coastlines, ports, and settlement neighborhoods so the prior better reflects plausible development paths.
- [ ] Distinguish between high-confidence static cells and high-entropy frontier cells.
- [x] Add a first history-informed prior layer using cached completed-round analysis data.
- [x] Tune the probability floor and prior strength using historical rounds instead of fixed intuition.
- [ ] Add class-specific smoothing so impossible-looking but still nonzero outcomes are handled safely for KL scoring.
- [ ] Compare pure-prior predictions against observation-informed predictions to quantify whether simulation budget is actually helping.

## 10. Learned Model Tasks

Reference: [ANALYSIS.md](ANALYSIS.md) sections 5.4 and 6.3-6.4; [COMPONENTS.md](COMPONENTS.md) section 4.

- [x] Build a historical training dataset from completed rounds and their `/analysis` outputs.
- [x] Define the prediction target clearly: final class probabilities per cell for the six submission classes.
- [x] Start with simple models that are easy to debug, such as logistic regression or tree-based class models over engineered features.
- [ ] Add calibration on top of raw model outputs because the metric rewards calibrated probabilities rather than hard labels.
- [ ] Evaluate whether separate models are needed for static terrain, dynamic frontier cells, and settlement-adjacent cells.
- [x] Add round-level latent parameter inference, either explicitly or through shared round features used across all seeds.
- [x] Experiment with ensembling prior-based, observation-based, and learned predictions.
- [ ] Keep inference cheap enough for Cloud Run Jobs unless profiling proves the need for heavier compute.
- [x] Record every experiment against historical rounds with reproducible configs and scores.

## 11. Historical Evaluation And Testing Tasks

Reference: [ANALYSIS.md](ANALYSIS.md) sections 6 and 9; [API.md](API.md) sections 9, 11, and 12.

- [x] Implement an offline scorer that matches the documented entropy-weighted KL behavior closely enough for model selection.
- [x] Build a repeatable evaluation loop over completed rounds.
- [x] Separate validation by round so leakage across the five seeds of the same round does not give false confidence.
- [x] Add unit tests for class mapping, tensor shape, floor application, and normalization.
- [x] Add tests for budget accounting and query-plan size.
- [ ] Add tests for artifact writing and optional GCS upload behavior.
- [ ] Add integration tests for public endpoints using a fixed historical round.
- [ ] Add mocked integration tests for authenticated endpoints if live token usage is too risky for CI.
- [x] Add a pre-submit validation script that fails fast on malformed predictions.

## 12. GCP Infrastructure Tasks

Reference: [COMPONENTS.md](COMPONENTS.md) sections 1-5 and [README.md](README.md).

These are optional automation tasks for Astar. Local execution remains the default and sufficient path.

- [ ] Enable and verify the required GCP services for the project being used by the team.
- [x] Decide the deployed secret path.
Decision: do not use Secret Manager in this repo; inject `AINM_ACCESS_TOKEN` as a Cloud Run runtime env var if Cloud Run is used.
- [ ] Decide whether the current `deploy_cloud_run_job.sh` path remains sufficient or should move to a more explicit IaC setup later.
- [ ] Build and deploy the Cloud Run Job successfully in the target project and region.
- [ ] Execute the job manually and verify that artifacts are produced as expected.
- [ ] Decide whether to attach a GCS bucket for persistent artifact storage from Cloud Run executions.
- [ ] If persistent artifacts are needed, create the bucket, set IAM correctly, and run a write/read smoke test.
- [ ] Add Cloud Scheduler only if there is a defined schedule for polling, analysis ingestion, or repeated submissions.
- [ ] Add Cloud Logging integration if stdout logs alone are not enough for debugging.
- [ ] Add BigQuery only when historical experiment tracking or artifact analysis becomes large enough to justify it.
- [ ] Do not introduce Pub/Sub, Vertex AI, or Compute Engine into the critical path unless a clear bottleneck justifies it.

## 13. Python Library Adoption Tasks

Reference: [COMPONENTS.md](COMPONENTS.md) section 4 and `requirements.txt`.

- [ ] Keep the minimal runtime set small for the live round runner.
- [ ] Add `pydantic` or equivalent only if schema validation is implemented.
- [ ] Add `tenacity` or equivalent only if retry logic is implemented.
- [ ] Add `pandas` and `pyarrow` only when historical dataset analysis becomes substantial.
- [ ] Add `scikit-learn`, `xgboost`, or `lightgbm` only when the historical training pipeline is ready to use them.
- [ ] Add `google-cloud-secret-manager` only if token retrieval is moved into Python rather than deployment-time env injection.
- [ ] Add `google-cloud-logging` only if structured cloud logging is adopted.
- [ ] Avoid adding overlapping libraries that duplicate existing functionality without a concrete need.

## 14. Competition Operations Tasks

Reference: [ANALYSIS.md](ANALYSIS.md) sections 7 and 9; [API.md](API.md) section 12; [COMPONENTS.md](COMPONENTS.md) sections 3.1-3.6.

- [x] Write a round-day runbook for the exact command sequence to use locally and on GCP.
- [x] Define when to do a public dry run, when to spend simulation budget, and when to submit.
- [x] Define whether the team will submit once near the deadline or multiple improving submissions during the round.
Decision: default to one inspected final submission, with resumable recovery if an earlier run is interrupted.
- [x] Add a simple checklist for verifying budget remaining, round status, and prediction validity before final submit.
- [x] Decide how to handle the case where there is no active round but preparation scripts are still running.
- [x] Decide how to recover if a simulation call fails mid-budget.
- [x] Decide how to recover if a submission succeeds for some seeds and fails for others.
- [x] Track leaderboard movement after submissions when that information is useful.
- [x] After each round closes, fetch analysis data, score the run retrospectively, and log lessons learned into the next modeling iteration.

## 15. Documentation Maintenance Tasks

Reference: all local `.md` files in this directory.

- [x] Update [README.md](README.md) whenever local commands, deployment steps, or secret handling change.
- [x] Update [API.md](API.md) if the organizer API behavior differs from what the code actually observes.
- [x] Update [ANALYSIS.md](ANALYSIS.md) when modeling assumptions change or a roadmap phase is completed.
- [x] Update [COMPONENTS.md](COMPONENTS.md) if the chosen GCP stack changes or a previously optional component becomes required.
- [x] Keep this file synchronized with the real state of the scaffold so it remains a useful project board rather than stale documentation.

## 16. Recommended Execution Order

Use this order unless a round deadline forces a narrower scope:

1. Finish access, API validation, and pre-submit safety checks.
2. Strengthen artifact capture and post-round analysis ingestion.
3. Replace the heuristic query planner with a budget-aware information-gain planner.
4. Build the historical dataset and offline scorer.
5. Improve the baseline using historical tuning before attempting more complex models.
6. Add learned models and calibration.
7. Harden Cloud Run execution and optional Scheduler or GCS integration.
8. Write and rehearse the competition-day runbook.

## 17. Short-Term Priorities

If work needs to start immediately, the highest-value next tasks are:

- [x] Implement post-round `/analysis` ingestion for all seeds.
- [x] Add offline scoring and historical evaluation.
- [x] Replace the current viewport heuristic with a real cross-seed budget allocation strategy.
- [ ] Tune baseline floor and prior strength on historical data.
- [x] Add pre-submit validation and better runtime error handling.
- [ ] Run the full workflow once on Cloud Run Job with real secrets and inspect the artifacts.

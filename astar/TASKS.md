# Astar Island Master Task List

This file is the working checklist for completing the Astar assignment end to end. Keep it aligned with the local reference docs and update statuses as implementation progresses.

## 1. Core References

Read these first and keep them open while working:

- [README.md](README.md): current scaffold, local commands, deployment entrypoints, and the intended day-to-day workflow.
- [ANALYSIS.md](ANALYSIS.md): task interpretation, scoring implications, modeling roadmap, and the distinction between solved scaffolding and unsolved modeling work.
- [API.md](API.md): endpoint contracts, payload shapes, class mapping, budget semantics, and practical API usage pattern.
- [COMPONENTS.md](COMPONENTS.md): recommended GCP architecture, component tradeoffs, and Python library guidance.

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
- [x] Heuristic viewport planner in `observation_strategy.py`.
- [x] Round runner and artifact writer in `run_round.py` and `artifacts.py`.
- [x] Opinionated Cloud Run Job deployment script in `deploy_cloud_run_job.sh`.

These are not complete yet and are the real remaining work:

- [ ] Strong query-planning logic.
- [ ] High-quality probabilistic model beyond heuristics.
- [ ] Historical training and evaluation loop from `/analysis`.
- [ ] Reliable tests, validation, and regression checks.
- [ ] Scheduled/operational GCP workflow around the current job deployment.
- [ ] Competition-day runbook and fallback procedures.

## 4. Access And Environment Tasks

Reference: [README.md](README.md), [API.md](API.md) sections 2-4, [COMPONENTS.md](COMPONENTS.md) sections 3.1-3.6.

- [ ] Confirm the team has a valid `access_token` from `app.ainm.no`.
- [ ] Keep the token only in `astar/.env` locally and in GCP Secret Manager under `astar-access-token` when deployed.
- [ ] Create and activate a local virtual environment and install `requirements.txt`.
- [ ] Run a public dry run with `python3 run_round.py --no-simulate --no-submit`.
- [ ] Run an authenticated smoke test against `budget`, `my-rounds`, and optionally `my-predictions` to verify token scope.
- [ ] Decide the canonical local artifact directory and retention policy for round outputs.
- [ ] Decide whether GCS artifact upload is required now or can remain optional.
- [ ] Document any machine-specific setup changes back into [README.md](README.md).

## 5. API Correctness And Runtime Hardening Tasks

Reference: [API.md](API.md) sections 4-12, [ANALYSIS.md](ANALYSIS.md) sections 7-8.

- [ ] Validate that every client method matches the documented request and response shape, including type assumptions around `round_id`, `seed_index`, viewport coordinates, and prediction tensor dimensions.
- [ ] Add explicit payload validation before `simulate` and `submit` calls.
- [ ] Add explicit response validation for round detail, simulation output, budget state, and analysis payloads.
- [ ] Add clear retry and timeout policy for network calls so transient failures do not waste a round.
- [ ] Add better error messages for no active round, exhausted budget, unauthorized token, malformed submission, and closed round submission attempts.
- [ ] Ensure submission tensors always apply the probability floor and renormalization exactly once.
- [ ] Add a local validation command or function that checks shape, class count, and per-cell probability sums before submission.
- [ ] Persist the exact request payload used for every simulation and submission artifact.
- [ ] Add lightweight run metadata such as timestamp, git commit, and config settings to artifacts for reproducibility.

## 6. Public Data Ingestion And Artifact Tasks

Reference: [ANALYSIS.md](ANALYSIS.md) sections 3, 5.1, and 7; [API.md](API.md) sections 4, 9, and 10.

- [ ] Snapshot `GET /rounds` and `GET /rounds/{round_id}` for every run.
- [ ] Snapshot leaderboard state for every run where public data is collected.
- [ ] Snapshot team state before and after simulation, including budget and current predictions.
- [ ] Define and document the expected artifact layout for one round so later training code can rely on it.
- [ ] Add a pass that fetches `/my-predictions/{round_id}` after submission and stores the authoritative server-side state.
- [ ] Add a post-round ingestion command that fetches `/analysis/{round_id}/{seed_index}` for all five seeds as soon as it becomes available.
- [ ] Normalize and store post-round analysis outputs into a stable dataset format for learning.
- [ ] Decide whether artifacts should remain JSON-only or whether training datasets should also be materialized as parquet/csv.

## 7. Query Planning Tasks

Reference: [ANALYSIS.md](ANALYSIS.md) sections 3.3, 4, 5.2, and 6; [API.md](API.md) sections 6-7.

- [ ] Replace the current heuristic viewport planner with a budgeted policy that treats the 50 simulations as a shared round-level resource.
- [ ] Split query planning into exploration and exploitation phases.
- [ ] Use the fact that hidden parameters are shared across all five seeds when allocating the first part of the budget.
- [ ] Identify which observable patterns are most informative about round-wide parameters such as growth, conflict, ruin generation, or terrain transitions.
- [ ] Add support for repeated sampling of the same viewport when stochastic uncertainty is itself informative.
- [ ] Add support for revisiting a seed based on what earlier queries revealed on other seeds.
- [ ] Score candidate viewports by expected information gain rather than only by settlement density.
- [ ] Track marginal value per query so the runner can stop spending budget when additional samples are not worth it.
- [ ] Add guardrails so the plan never exceeds the documented budget of 50 queries total.
- [ ] Persist the planned budget allocation and the realized budget allocation separately for later analysis.

## 8. Observation Accumulation And Feature Tasks

Reference: [ANALYSIS.md](ANALYSIS.md) sections 5.3-5.4 and 9; [API.md](API.md) sections 5 and 7.

- [ ] Design a stable in-memory representation for simulation evidence across repeated samples.
- [ ] Aggregate observed class counts per cell and per time horizon rather than overwriting with the latest sample.
- [ ] Store uncertainty summaries for cells that were observed multiple times with different outcomes.
- [ ] Build round-level summary features from simulation outputs, not just per-cell counts.
- [ ] Build seed-level summary features that describe coastlines, initial settlements, mountain barriers, forest density, and expansion corridors.
- [ ] Derive features that capture neighborhood structure and likely interaction fronts between settlements.
- [ ] Keep a clean mapping from raw terrain codes to submission classes so training and inference use the same conventions.
- [ ] Add dataset serialization utilities so observations can be reused in offline experiments without rerunning API calls.

## 9. Baseline Improvement Tasks

Reference: [ANALYSIS.md](ANALYSIS.md) sections 2, 4, 6.1, and 6.2; [API.md](API.md) section 11.

- [ ] Audit the current prior in `baseline.py` against the actual mechanics and identify where it is overconfident or structurally wrong.
- [ ] Improve the prior for static terrain classes such as mountains and forests where public initial state is already informative.
- [ ] Improve treatment of coastlines, ports, and settlement neighborhoods so the prior better reflects plausible development paths.
- [ ] Distinguish between high-confidence static cells and high-entropy frontier cells.
- [ ] Tune the probability floor and prior strength using historical rounds instead of fixed intuition.
- [ ] Add class-specific smoothing so impossible-looking but still nonzero outcomes are handled safely for KL scoring.
- [ ] Compare pure-prior predictions against observation-informed predictions to quantify whether simulation budget is actually helping.

## 10. Learned Model Tasks

Reference: [ANALYSIS.md](ANALYSIS.md) sections 5.4 and 6.3-6.4; [COMPONENTS.md](COMPONENTS.md) section 4.

- [ ] Build a historical training dataset from completed rounds and their `/analysis` outputs.
- [ ] Define the prediction target clearly: final class probabilities per cell for the six submission classes.
- [ ] Start with simple models that are easy to debug, such as logistic regression or tree-based class models over engineered features.
- [ ] Add calibration on top of raw model outputs because the metric rewards calibrated probabilities rather than hard labels.
- [ ] Evaluate whether separate models are needed for static terrain, dynamic frontier cells, and settlement-adjacent cells.
- [ ] Add round-level latent parameter inference, either explicitly or through shared round features used across all seeds.
- [ ] Experiment with ensembling prior-based, observation-based, and learned predictions.
- [ ] Keep inference cheap enough for Cloud Run Jobs unless profiling proves the need for heavier compute.
- [ ] Record every experiment against historical rounds with reproducible configs and scores.

## 11. Historical Evaluation And Testing Tasks

Reference: [ANALYSIS.md](ANALYSIS.md) sections 6 and 9; [API.md](API.md) sections 9, 11, and 12.

- [ ] Implement an offline scorer that matches the documented entropy-weighted KL behavior closely enough for model selection.
- [ ] Build a repeatable evaluation loop over completed rounds.
- [ ] Separate validation by round so leakage across the five seeds of the same round does not give false confidence.
- [ ] Add unit tests for class mapping, tensor shape, floor application, and normalization.
- [ ] Add tests for budget accounting and query-plan size.
- [ ] Add tests for artifact writing and optional GCS upload behavior.
- [ ] Add integration tests for public endpoints using a fixed historical round.
- [ ] Add mocked integration tests for authenticated endpoints if live token usage is too risky for CI.
- [ ] Add a pre-submit validation script that fails fast on malformed predictions.

## 12. GCP Infrastructure Tasks

Reference: [COMPONENTS.md](COMPONENTS.md) sections 1-5 and [README.md](README.md).

- [ ] Enable and verify the required GCP services for the project being used by the team.
- [ ] Create the Secret Manager secret `astar-access-token` and load the NM i AI token there.
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

- [ ] Write a round-day runbook for the exact command sequence to use locally and on GCP.
- [ ] Define when to do a public dry run, when to spend simulation budget, and when to submit.
- [ ] Define whether the team will submit once near the deadline or multiple improving submissions during the round.
- [ ] Add a simple checklist for verifying budget remaining, round status, and prediction validity before final submit.
- [ ] Decide how to handle the case where there is no active round but preparation scripts are still running.
- [ ] Decide how to recover if a simulation call fails mid-budget.
- [ ] Decide how to recover if a submission succeeds for some seeds and fails for others.
- [ ] Track leaderboard movement after submissions when that information is useful.
- [ ] After each round closes, fetch analysis data, score the run retrospectively, and log lessons learned into the next modeling iteration.

## 15. Documentation Maintenance Tasks

Reference: all local `.md` files in this directory.

- [ ] Update [README.md](README.md) whenever local commands, deployment steps, or secret handling change.
- [ ] Update [API.md](API.md) if the organizer API behavior differs from what the code actually observes.
- [ ] Update [ANALYSIS.md](ANALYSIS.md) when modeling assumptions change or a roadmap phase is completed.
- [ ] Update [COMPONENTS.md](COMPONENTS.md) if the chosen GCP stack changes or a previously optional component becomes required.
- [ ] Keep this file synchronized with the real state of the scaffold so it remains a useful project board rather than stale documentation.

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

- [ ] Implement post-round `/analysis` ingestion for all seeds.
- [ ] Add offline scoring and historical evaluation.
- [ ] Replace the current viewport heuristic with a real cross-seed budget allocation strategy.
- [ ] Tune baseline floor and prior strength on historical data.
- [ ] Add pre-submit validation and better runtime error handling.
- [ ] Run the full workflow once on Cloud Run Job with real secrets and inspect the artifacts.

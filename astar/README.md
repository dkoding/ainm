# Astar Island

This directory contains a documented and automation-ready scaffold for the Astar Island task.

The default round flow is:

1. sync completed-round history from the server
2. retrain and re-evaluate the local sklearn model on completed rounds only
3. build predictions for the current active round
4. optionally spend live simulate budget
5. validate and submit predictions for the current round

Completed rounds become training data. The active round does not enter training until it closes and `/analysis` is available.

What the docs require:

- Authenticate with your `access_token` JWT from `app.ainm.no`.
- Use `https://api.ainm.no/astar-island/...`.
- Query the active round and round details.
- Submit one `H x W x 6` probability tensor per seed.
- There are 5 seeds per round and 50 total simulation queries per round.
- Never assign `0.0` to any class; use a probability floor and renormalize.

What is included here:

- `ANALYSIS.md`: task-solving analysis and modeling implications.
- `API.md`: task-focused API reference.
- `COMPONENTS.md`: non-duplicative GCP stack analysis for Astar.
- `RUNBOOK.md`: local-first round procedure, submission safety rules, and recovery steps.
- `TASKS.md`: working project board for the remaining solver work.
- `astar_client.py`: public/team API wrapper for rounds, budget, simulate, submit, leaderboard, and post-round analysis.
- `baseline.py`: safe prior generator plus observation-informed posterior blending.
- `observation_strategy.py`: budget-aware viewport planner that does a tiled full-map sweep first and uses leftover budget for repeats.
- `history_cache.py`: completed-round cache sync and cache-loading helpers for `/analysis` data.
- `history_priors.py`: empirical prior builder that learns simple class distributions from cached completed rounds.
- `history_dataset.py`: JSONL dataset builder from cached completed-round analysis.
- `feature_engineering.py`: shared per-cell feature extraction used by dataset generation and local ML inference.
- `scoring.py`: offline entropy-weighted KL scorer matching the organizer docs.
- `sklearn_model.py`: local scikit-learn soft-target random-forest training and inference helpers over the cached history dataset.
- `reporting.py`: compact per-run reporting helper for prediction summaries and budget context.
- `build_history_dataset.py`: CLI entrypoint for dataset generation.
- `evaluate_history.py`: CLI entrypoint for offline evaluation on cached rounds.
- `train_sklearn_model.py`: CLI entrypoint for training a local random-forest regressor from cached history.
- `evaluate_sklearn_model.py`: CLI entrypoint for leave-one-round-out evaluation of the local sklearn model.
- `validate_predictions.py`: local prediction validator before submit.
- `resume_round.py`: rebuild and optionally submit predictions from cached simulation artifacts.
- `sync_history_cache.py`: CLI entrypoint for downloading and caching completed-round history.
- `run_round.py`: env-driven round runner for public sync, optional simulation, prediction writing, and optional submission.
- `round_loop.py`: long-running loop that watches for new rounds, records official team scores, runs post-round review, and auto-runs the per-round pipeline on each new active round.
- `submit_baseline.py`: compatibility wrapper around `run_round.py`.
- `artifacts.py`: local JSON artifact writer with optional GCS upload.
- `config.py`: `.env`-driven settings loader.
- `deploy_cloud_run_job.sh`: Cloud Run Job deployment script for automated Astar runs.

Install:

```bash
cd astar
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`scikit-learn` is now part of the main runtime requirements because the default round runner can retrain before prediction. `requirements-training.txt` remains as a minimal alias if you only want the ML dependency separately.

Configure local env:

```bash
cp .env.example .env
```

The intent is that `.env` only holds secrets. Stable runtime defaults are hard-coded in the scaffold, and non-secret overrides should normally be passed as CLI flags.

Public dry run without a token:

```bash
python3 run_round.py --no-simulate --no-submit
```

Skip the automatic history refresh explicitly if you only want a quick smoke test:

```bash
python3 run_round.py --no-sync-history --no-simulate --no-submit
```

Cache completed-round public history without a token:

```bash
python3 sync_history_cache.py --no-analysis
```

Cache completed-round `/analysis` payloads locally for later reuse:

```bash
python3 sync_history_cache.py --token "$AINM_ACCESS_TOKEN"
```

Build a JSONL training dataset from cached history:

```bash
python3 build_history_dataset.py
```

Evaluate the baseline offline on cached completed rounds:

```bash
python3 evaluate_history.py
```

Train a local scikit-learn model from cached history:

```bash
python3 train_sklearn_model.py
```

Evaluate the local scikit-learn model with leave-one-round-out scoring:

```bash
python3 evaluate_sklearn_model.py
```

If there is no active round, rerun with an explicit historical round:

```bash
python3 run_round.py --round-id "<round-id>" --no-simulate --no-submit
```

Run a small observation-informed round locally:

```bash
python3 run_round.py --token "$AINM_ACCESS_TOKEN" --simulate --total-queries 45 --no-submit
```

Run the current round and refresh the completed-round cache at startup:

```bash
python3 run_round.py --token "$AINM_ACCESS_TOKEN" --sync-history --simulate --total-queries 45 --no-submit
```

Run with cached-history priors enabled explicitly:

```bash
python3 run_round.py --token "$AINM_ACCESS_TOKEN" --sync-history --use-history-priors --history-prior-strength 2.0 --simulate --total-queries 45 --no-submit
```

Validate locally written prediction payloads before final submit:

```bash
python3 validate_predictions.py --round-id "<round-id>"
```

Submit the active round:

```bash
python3 run_round.py --token "$AINM_ACCESS_TOKEN" --simulate --total-queries 45 --submit
```

Force the baseline path instead of the retrained sklearn model:

```bash
python3 run_round.py --token "$AINM_ACCESS_TOKEN" --prediction-model baseline --simulate --total-queries 45 --submit
```

Resume an interrupted round from cached simulations without spending more query budget:

```bash
python3 resume_round.py --round-id "<round-id>" --submit
```

Run the looped watcher that handles new rounds automatically:

```bash
python3 round_loop.py --total-queries 45 --submit
```

Deploy as a Cloud Run Job:

```bash
./deploy_cloud_run_job.sh
```

The deployment script is intentionally opinionated. It hard-codes the job name, region, and runtime settings, and injects `AINM_ACCESS_TOKEN` from `astar/.env` as a runtime environment variable.

Notes:

- The task docs describe Astar as a direct API task. You submit tensors to the organizer API; you do not need to expose a public `/solve` endpoint for the core task flow.
- Local execution is the default operating mode. `Cloud Run Jobs` are optional automation, not a requirement for Astar.
- `GET /rounds` and `GET /rounds/{round_id}` are public. Budget, simulate, submit, and team analysis endpoints require a token.
- The docs expose `prediction_window_minutes`, `started_at`, and `closes_at` on rounds. In live data so far, new rounds have appeared on a `165` minute cadence, but the loop runner keys off the API timestamps instead of hard-coding that schedule.
- `--total-queries` is the correct budget control flag. The `50` query limit is for the whole round, not per seed.
- Completed-round cache data is written under `artifacts/history/...` by default, with `index.json` summarizing what has been synced.
- By default, `run_round.py` refreshes completed-round history first, retrains the local sklearn model on completed rounds only, re-evaluates it, and then predicts the active round.
- History sync now always pulls the full completed-round history. There is no round-limit flag in the default workflow anymore.
- The default live query policy is now a tiled sweep: cover each `40x40` map with `9` viewports (`15/15/10` by `15/15/10`) before spending leftover budget on repeat samples.
- The updated scaffold can spend simulator queries and blend observed outcomes back into the per-cell probability tensor.
- `sync_history_cache.py` can cache completed-round `/analysis` payloads locally so startup logic can reuse them without refetching every file first.
- When cached analysis exists, `run_round.py` can automatically build simple empirical priors from that history and blend them into the baseline.
- When cached analysis exists and `scikit-learn` is installed, `run_round.py` can retrain the local random-forest regressor before current-round inference. Training uses completed rounds only; the active round is never added to training before prediction.
- `round_loop.py` records official server round scores from `my_rounds`, runs post-round review when a round completes, and uses the newly completed rounds as training data for the next active round.
- Each run now writes `report.json` with round metadata, history-cache usage, seed-level confidence summaries, and argmax class counts.
- Offline evaluation and dataset generation now work from the cached history without requiring live API calls.
- A local scikit-learn random-forest regressor can now be trained directly on the cached history and learn the full six-class target probability vector without adding pandas or a hosted training service.
- If you use the optional Cloud Run Job path, inject `AINM_ACCESS_TOKEN` at deploy time from `astar/.env`; do not bake it into the image.
- The deployment script derives the active GCP project from `gcloud config` if `GOOGLE_CLOUD_PROJECT` is not exported.

## Artifact Layout

The default artifact root is `artifacts/`.

Important paths:

- `artifacts/history/index.json`: cache index for completed rounds
- `artifacts/history/rounds/<round_id>/public/round_detail.json`: cached round detail
- `artifacts/history/rounds/<round_id>/team/analysis/seed_<n>.json`: cached completed-round analysis
- `artifacts/history/datasets/cell_examples.jsonl`: training dataset built from cached history
- `artifacts/history/evaluation.json`: offline evaluation summary
- `artifacts/<round_id>/report.json`: current run report
- `artifacts/<round_id>/predictions/seed_<n>.json`: submission payloads
- `artifacts/<round_id>/team/submissions/seed_<n>.json`: submit request/response artifacts

## Verification

Use the project venv for verification commands:

```bash
python3 -m py_compile *.py
/tmp/astar-venv/bin/python -m unittest discover -s tests
```

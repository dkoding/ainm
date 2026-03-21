# Astar Round Runbook

This is the operational procedure for running Astar safely.

## 1. Default Operating Mode

Use local execution by default.

- The organizer does not call your server.
- Astar traffic is outbound only.
- `Cloud Run Jobs` are optional automation, not a requirement for submission.

Use Cloud Run Jobs only when you want unattended execution, a stable hosted runtime, or scheduled retries.
If you use Cloud Run Jobs in this repo, inject `AINM_ACCESS_TOKEN` as a runtime environment variable at deploy time. Do not bake it into the image.

The default runner now follows this order:

1. sync completed rounds
2. tune baseline floor and history-prior strength when default values are still in use
3. retrain on completed rounds only with entropy-aware sample weighting and held-out round calibration
4. compare prediction variants on completed rounds using replayed observations
5. if `--submit` and `--simulate` are enabled, place an early safe submission first
6. if simulation is enabled, spend live budget through the adaptive information-gain planner
7. infer round-regime weights from live observations and build observation-conditioned variants
8. predict the active round
9. overwrite the earlier safe submission with the final tensor after validation

The loop runner uses the API timestamps and statuses to decide when to wake up. Do not hard-code a round schedule in external cron unless you have to. The docs and live API expose `prediction_window_minutes`, `started_at`, and `closes_at`, and current rounds have used `165` minute windows.

## 2. Pre-Round Preparation

1. Activate the project venv and verify dependencies are installed.
2. Confirm `AINM_ACCESS_TOKEN` exists in `astar/.env`.
3. Refresh completed-round history:

```bash
python3 sync_history_cache.py --token "$AINM_ACCESS_TOKEN"
```

4. Rebuild the historical dataset:

```bash
python3 build_history_dataset.py
```

5. Re-run offline evaluation:

```bash
python3 evaluate_history.py
```

6. Check that `artifacts/history/evaluation.json` still looks sane before the round starts.

## 3. Safe Active-Round Workflow

1. Public dry run:

```bash
python3 run_round.py --no-simulate --no-submit
```

2. History-aware observation run without submission:

```bash
python3 run_round.py --token "$AINM_ACCESS_TOKEN" --sync-history --simulate --total-queries 50 --no-submit
```

3. Validate the prediction payloads before final submit:

```bash
python3 validate_predictions.py --round-id "<round-id>"
```

4. Final submit:

```bash
python3 run_round.py --token "$AINM_ACCESS_TOKEN" --sync-history --simulate --total-queries 50 --submit
```

If the server has moved from round 7 to round 8, the runner should first ingest round 7 `/analysis`, retrain, re-evaluate, place the early safe submit for round 8, and only then produce the stronger overwrite submission.

## 3.1 Loop Mode

Use the long-running watcher when you want the process to keep handling rounds automatically:

```bash
python3 round_loop.py --total-queries 50 --submit
```

Loop behavior:

1. poll `/rounds`, `/my-rounds`, and `/leaderboard`
2. record official server scores from `/my-rounds`
3. run post-round review for newly completed rounds with team submissions
4. when a new active round appears and no predictions are on the server yet, run `run_round.py`
5. when a partial submission state is detected, run `resume_round.py`
6. write `loop/events.jsonl`, `loop/heartbeat.json`, and `loop/loop.lock` so loop state is auditable and duplicate runners are easier to detect

If you want the watcher restarted automatically when it exits or stops heartbeating, run it through:

```bash
python3 supervise_round_loop.py -- --total-queries 50 --submit
```

## 4. Query Budget Policy

The Astar budget is `50` simulation queries for the whole round, not per seed.

Current default policy:

- use `--total-queries`, not `--queries-per-seed`
- default target is `50`: up to `45` unique tiled windows plus `5` repeat queries chosen from the highest-uncertainty windows
- the planner now includes a regime-disagreement term so early windows help distinguish shared round-wide hidden dynamics
- if you use a smaller budget such as `20`, let the planner use the adaptive information-gain policy rather than hard-coding a per-seed split
- in `auto` mode, let the runner compare completed-round variant scores and keep the best historical variant
- in `auto` mode, recent official regression feedback can now block a repeatedly underperforming variant and force fallback to the next-ranked candidate

Do not use `10 queries per seed` unless you explicitly intend to spend the entire round budget.

## 5. Reporting And Review

Every run should produce:

- `report.json`
- `predictions_initial/seed_*.json` when staged submit is used
- `predictions/seed_*.json`
- `team/observation_plan.json` when simulation is used
- `team/submissions_initial/seed_*.json` when staged submit is used
- `team/submissions/seed_*.json` when submission is used
- `team/my_predictions.json` after submit
- `loop/events.jsonl` and `loop/heartbeat.json` for long-running watcher mode

Review:

- `budget_before` and `budget_after`
- `query_plan_summary`
- `seed_reports[*].observation_count`
- `seed_reports[*].mean_confidence`
- `seed_reports[*].mean_entropy`

## 6. Recovery Procedures

### Interrupted simulation run

If a run stops after spending some simulation budget but before submission, do not restart with `--simulate`.

Resume from cached observations:

```bash
python3 resume_round.py --round-id "<round-id>" --submit
```

This rebuilds predictions from locally cached simulation responses and submits without spending additional simulation budget.

### Partial submission state

If some seeds were accepted and others were not:

1. inspect `team/submissions/`
2. fetch `my_predictions`
3. rerun `resume_round.py --round-id "<round-id>" --submit`

The organizer API keeps the latest submission per seed, so safe re-submission is better than leaving missing seeds.

### Early safe submit without final overwrite yet

If the process dies after the early safe submit but before the stronger overwrite is finished:

1. do not panic, because the round already has a nonzero fallback submission on the server
2. if cached simulations exist, rerun `resume_round.py --round-id "<round-id>" --submit`
3. otherwise rerun `run_round.py --round-id "<round-id>" --simulate --submit`

`round_loop.py` now detects this staged-only state and will try to continue to the final overwrite instead of treating the round as fully done.

### No active round

If `run_round.py` reports no active round:

- use `--round-id` with a completed round for dry runs
- do not try to submit
- use the time for cache refresh, evaluation, or tuning

## 7. Post-Round Workflow

As soon as the round becomes `completed`:

1. refresh history:

```bash
python3 sync_history_cache.py --token "$AINM_ACCESS_TOKEN"
```

2. rebuild the dataset:

```bash
python3 build_history_dataset.py
```

3. re-run offline evaluation:

```bash
python3 evaluate_history.py
```

4. compare the new round against the previous evaluation baseline
5. update `TASKS.md` if the modeling plan changed

If the organizer exposes `/analysis` during `scoring`, the history sync can now ingest that data before the final `completed` transition as well.

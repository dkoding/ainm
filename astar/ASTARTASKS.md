# Astar Delta Fix Task List

This file turns [DELTAS.md](DELTAS.md) into an executable implementation list.

References to keep open while working:

- [DELTAS.md](DELTAS.md)
- [README.md](README.md)
- [RUNBOOK.md](RUNBOOK.md)
- [ANALYSIS.md](ANALYSIS.md)
- [API.md](API.md)
- [TASKS.md](TASKS.md)

Definition of done for this pass:

- The runtime respects documented rate limits and records pacing decisions.
- The query planner is explicitly information-gain-driven and uses live evidence for repeat sampling.
- Strategy selection, caching, and round-regime inference are upgraded to match the intended live workflow better.
- Completed-round ingestion is fast enough to learn from `scoring` rounds when analysis is available.
- Official score feedback, loop observability, and recovery artifacts are strong enough to explain regressions.
- The new logic is covered by tests.
- Local docs are brought back in line with the actual implementation.

## 1. Runtime Safety And API Compliance

- [x] Add explicit pacing helpers for `POST /simulate` and `POST /submit` so the runtime respects the documented `5/s` and `2/s` rate limits.
Files:
`astar_client.py`, `run_round.py`, `resume_round.py`, tests

- [x] Record request pacing and retry/backoff metadata in artifacts and reports.
Files:
`astar_client.py`, `reporting.py`, tests

- [x] Make the raw verification workflow more robust when the wrong Python environment is active.
Files:
`README.md`, `RUNBOOK.md`, tests or helper logic as needed

## 2. Information-Gain Query Planning

- [x] Replace the static repeat-window policy with an explicit information-gain scorer that combines prior entropy, frontier structure, settlement/coast importance, and historical volatility.
Files:
`observation_strategy.py`, `baseline.py`, `history_priors.py`, tests

- [x] Use live observations from already-sampled windows to recompute value for the remaining budget.
Files:
`observation_strategy.py`, `run_round.py`, tests

- [x] Make cross-seed allocation responsive to shared round-level evidence instead of only balancing by seed count.
Files:
`observation_strategy.py`, `history_priors.py`, `run_round.py`, tests

## 3. Regime Inference And Prediction Selection

- [x] Expand round-regime inference beyond terrain/settlement priors by incorporating round-level observed summaries from simulation outputs, including settlement stats where available.
Files:
`history_priors.py`, `run_round.py`, tests

- [x] Upgrade variant selection so it evaluates candidate strategies in the same information regime as the live runner when observations exist.
Files:
`prediction_variants.py`, `run_round.py`, tests

- [x] Strengthen cached strategy-evaluation invalidation with a config/model signature instead of round IDs alone.
Files:
`prediction_variants.py`, `run_round.py`, tests

## 4. Learning Loop And Historical Ingestion

- [x] Extend history sync to ingest `scoring` rounds when `/analysis` is already available.
Files:
`history_cache.py`, tests, docs

- [x] Add automated baseline tuning for floor and prior strength and feed the tuned values back into live runs.
Files:
`tune_baseline.py`, `run_round.py`, `config.py`, tests

- [x] Add richer global and neighborhood features to the learned model so it is not purely local.
Files:
`feature_engineering.py`, `history_dataset.py`, `sklearn_model.py`, tests

## 5. Score Feedback And Observability

- [x] Turn official round scores into an explicit control signal: compare official results with offline expectations and surface regressions automatically.
Files:
`round_loop.py`, `post_round_review.py`, `reporting.py`, tests

- [x] Add a structured loop event log and heartbeat artifacts so round decisions can be reconstructed after the fact.
Files:
`round_loop.py`, tests, docs

- [x] Add lock/lease-style loop guardrails so the automation is safer to run continuously.
Files:
`round_loop.py`, docs, tests

## 6. Tests And Documentation

- [x] Add tests for `prediction_variants.py`, regime inference, loop active-round choice, loop missed-round reporting, loop event logging, and strategy-cache invalidation.
Files:
`tests/`

- [x] Update docs so the documented flow matches the real execution order and the new information-gain planner.
Files:
`README.md`, `RUNBOOK.md`, `ANALYSIS.md`, `TASKS.md`, possibly `API.md`

- [x] Update [DELTAS.md](DELTAS.md) at the end so only truly remaining or external issues stay open.
Files:
`DELTAS.md`

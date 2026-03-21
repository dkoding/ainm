# Score Improvement Task Board

This file turns [SCOREIMPROV.md](SCOREIMPROV.md) into an implementation plan. It is intentionally limited to tasks that can be completed in-repo now and that respect the official Astar rules and API behavior.

Primary references:

- [SCOREIMPROV.md](SCOREIMPROV.md)
- [README.md](README.md)
- [RUNBOOK.md](RUNBOOK.md)
- [ANALYSIS.md](ANALYSIS.md)
- [API.md](API.md)
- [artifacts/loop/team_round_scores.json](artifacts/loop/team_round_scores.json)
- [artifacts/history/variant_selection.json](artifacts/history/variant_selection.json)
- [artifacts/history/sklearn_evaluation.json](artifacts/history/sklearn_evaluation.json)

Rule guardrails from the official docs:

- Stay within `50` simulation queries total per round.
- Respect `POST /simulate` and `POST /submit` rate limits.
- Only use documented endpoints and payloads.
- Use submission overwrite only in the documented sense: later submissions replace earlier ones for the same seed.
- Never assume intermediate ground truth is available during an active round.

## Definition Of Done

This score-improvement pass is complete when:

- the runner can make an early safe submission and later overwrite it with a stronger final submission
- training is better aligned with entropy-weighted scoring
- calibration is no longer in-sample only
- live observations affect unsampled cells through a documented prediction path
- the planner explicitly values regime-discriminating windows
- tests and docs cover the new scoring workflow

## Prioritized Tasks

- [x] **Task 1: Staged Submit And Overwrite Workflow**
  - Why:
    The official docs allow overwriting submissions, and missing a seed gives zero. The runner should therefore submit a safe baseline early, then overwrite it after simulation and analysis.
  - Implementation:
    Add staged-submit support to [run_round.py](run_round.py) and [round_loop.py](round_loop.py). Persist both the early and final submission artifacts separately. Keep validation and rate-limit pacing intact.
  - Acceptance:
    A single run can produce two valid submission phases for the same round without exceeding rules or corrupting artifacts.

- [x] **Task 2: Entropy-Weighted Training And Dynamic-Cell Diagnostics**
  - Why:
    The official score is entropy-weighted KL. Training should spend more capacity on dynamic cells than on static cells.
  - Implementation:
    Add per-cell entropy-derived sample weights to the historical dataset and sklearn training path. Add summary metrics that distinguish all-cell fit from dynamic-cell fit.
  - Acceptance:
    Training metadata and evaluation outputs expose entropy-aware weighting and dynamic-cell diagnostics.

- [x] **Task 3: Held-Out Round Calibration**
  - Why:
    Current calibration is chosen on training predictions. That is weak and can easily stay at `1.0` without improving score.
  - Implementation:
    Replace in-sample temperature selection with held-out round calibration. Use completed rounds only and keep the active round excluded.
  - Acceptance:
    Model metadata records held-out calibration inputs and the selected temperature.

- [x] **Task 4: Mechanics-Rich Feature Expansion**
  - Why:
    Current features are still too local for a 50-year settlement/trade/conflict simulator.
  - Implementation:
    Expand [feature_engineering.py](feature_engineering.py) with additional coastline, connectivity, density, and barrier features that are derivable from the visible initial map and settlement layout.
  - Acceptance:
    The training pipeline uses the richer feature set and tests still pass.

- [x] **Task 5: Observation-Conditioned Global Prediction Variant**
  - Why:
    Live observations currently affect observed cells strongly, but they do not sufficiently update unsampled cells.
  - Implementation:
    Add a prediction variant that uses live observation summaries and spatial propagation to adjust the whole-map tensor, not only directly observed windows. Evaluate it alongside the existing variants.
  - Acceptance:
    Variant evaluation includes the new observation-conditioned path and the runner can select it automatically when it wins offline.

- [x] **Task 6: Regime-Discriminating Planner**
  - Why:
    Hidden parameters are shared across all 5 seeds, so early queries should help distinguish possible round regimes rather than only target local entropy.
  - Implementation:
    Extend [observation_strategy.py](observation_strategy.py) to score windows partly by how much historical round priors disagree on them. Record that term in the planning trace and summaries.
  - Acceptance:
    Query planning summaries expose regime-discrimination terms and tests cover the new behavior.

- [x] **Task 7: Docs, Reports, And Tests Sync**
  - Why:
    The score path has to stay debuggable. The docs and reports need to describe the new staged submit, entropy-aware training, live-conditioned variants, and regime-aware planner.
  - Implementation:
    Update [README.md](README.md), [RUNBOOK.md](RUNBOOK.md), [ANALYSIS.md](ANALYSIS.md), and relevant tests. Ensure round reports include the new fields needed for post-round analysis.
  - Acceptance:
    Docs match the code and the test suite covers the new behavior.

## Execution Order

1. Task 1: staged submit and overwrite
2. Task 2: entropy-weighted training and diagnostics
3. Task 3: held-out calibration
4. Task 4: richer mechanics-inspired features
5. Task 5: observation-conditioned global variant
6. Task 6: regime-discriminating planner
7. Task 7: docs, report fields, and tests

## Notes

- This board is deliberately implementation-oriented. It does not include open-ended research items that cannot be completed and verified now.
- If interrupted, restart at the first unchecked task and continue downward.

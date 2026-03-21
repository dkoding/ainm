# Astar Score Improvement Review

This file reviews current scoring performance, checks the current solver against the Astar docs and local implementation, and identifies the highest-value ways to improve score from here.

Primary references:

- [README.md](README.md)
- [RUNBOOK.md](RUNBOOK.md)
- [ANALYSIS.md](ANALYSIS.md)
- [API.md](API.md)
- [DELTAS.md](DELTAS.md)
- [artifacts/loop/team_round_scores.json](artifacts/loop/team_round_scores.json)
- [artifacts/history/variant_selection.json](artifacts/history/variant_selection.json)
- [artifacts/history/sklearn_evaluation.json](artifacts/history/sklearn_evaluation.json)
- [artifacts/d0a2c894-2162-4d49-86cf-435b9013f3b8/team/score_feedback.json](artifacts/d0a2c894-2162-4d49-86cf-435b9013f3b8/team/score_feedback.json)
- [artifacts/cc5442dd-bc5d-418b-911b-7eb960cb0390/report.json](artifacts/cc5442dd-bc5d-418b-911b-7eb960cb0390/report.json)

Official docs:

- Overview: https://app.ainm.no/docs/astar-island/overview
- Mechanics: https://app.ainm.no/docs/astar-island/mechanics
- Endpoints: https://app.ainm.no/docs/astar-island/endpoint
- Scoring: https://app.ainm.no/docs/astar-island/scoring
- Quickstart: https://app.ainm.no/docs/astar-island/quickstart

## Verdict

No, the score is not where it should be yet.

The current solver is credible and much safer than the original scaffold, but it is still leaving meaningful score on the table. The biggest problem is not raw plumbing anymore. The main gap is that the system is still only partially exploiting what the task actually rewards:

- the metric heavily weights dynamic, high-entropy cells
- hidden parameters are shared across all 5 seeds
- `simulate` reveals far more than just terrain labels
- resubmission is allowed, so reliability should be engineered into the round workflow

The strongest next gains are therefore not "more code around the edges". They are:

1. optimize training directly for entropy-weighted scoring
2. make live observations influence unsampled cells, not just observed cells
3. improve round-regime inference from shared cross-seed evidence
4. use the overwrite-friendly submission rule operationally

## Current State

Recent official scores from [artifacts/loop/team_round_scores.json](artifacts/loop/team_round_scores.json):

- round 8: `74.0911`
- round 10: `67.3492`
- round 11: `50.5976`
- round 12: `48.3709`
- round 13: `76.1008`
- round 14: `41.5742`
- round 15: active, score pending

Mean official score across scored rounds so far: about `57.83`.
Best official score so far: `76.10` on round 13.

Current model-selection evidence from [artifacts/history/variant_selection.json](artifacts/history/variant_selection.json):

- `ensemble_sklearn_50`: mean offline round score `62.75`
- `ensemble_sklearn_75`: `62.48`
- `ensemble_sklearn_25`: `61.85`
- `sklearn`: `59.41`
- `baseline_history`: `58.58`

Important consequence:

- the codebase has already moved beyond pure `sklearn`
- [artifacts/cc5442dd-bc5d-418b-911b-7eb960cb0390/report.json](artifacts/cc5442dd-bc5d-418b-911b-7eb960cb0390/report.json) shows round 15 is using `ensemble_sklearn_50`
- several weaker official rounds were produced before the current best-offline variant became the active default

## What The Docs Mean For Scoring

From the official scoring and endpoint docs:

- scoring is entropy-weighted KL, not accuracy
- static cells contribute very little
- zero probabilities are dangerous
- each round has 50 shared queries across 5 seeds
- hidden parameters are shared across all seeds in a round
- each `simulate` call is one stochastic sample, not ground truth
- resubmitting the same seed overwrites the earlier submission
- missing a seed gives a zero for that seed
- the leaderboard uses the best weighted round, and later rounds matter more

That changes the objective materially.

The solver should not primarily optimize:

- global average per-cell fit
- static terrain accuracy
- one-shot final submission behavior

It should optimize:

- calibrated probabilities on dynamic cells
- early identification of round-wide latent behavior
- reliable full-seed submission coverage
- low-risk improvement via overwrite submissions during the round

## What The Current Code Does Well

The current implementation has real strengths:

- [scoring.py](scoring.py) matches the documented entropy-weighted KL structure
- [run_round.py](run_round.py) syncs history, tunes baseline defaults, retrains locally, evaluates variants, simulates, predicts, validates, and submits
- [observation_strategy.py](observation_strategy.py) uses a budget-aware planner instead of per-seed query splitting
- [prediction_variants.py](prediction_variants.py) evaluates multiple variants and has now moved toward ensemble selection
- [history_priors.py](history_priors.py) uses shared-round regime weighting
- [round_loop.py](round_loop.py) feeds back official server scores and tracks regressions

Those are real improvements. The repo is not failing because of missing scaffolding anymore.

## Why Score Is Still Underperforming

### 1. The learned model is not optimized for the actual metric

Current training in [sklearn_model.py](sklearn_model.py) fits a `RandomForestRegressor` on all cells equally.

But the docs make clear that:

- high-entropy cells dominate score
- static cells are nearly ignored

That means the current training target is misaligned with the leaderboard objective. A model can improve average fit while barely improving score.

Symptoms:

- strong offline fit on easier rounds can coexist with weak official scores on hard rounds
- the model spends too much capacity learning ocean/mountain/mostly-static forest behavior that barely moves the metric

Highest-value fix:

- weight training examples by target entropy
- separately evaluate dynamic cells versus static cells
- consider separate model paths for static terrain, settlement-adjacent/frontier cells, and highly dynamic cells

Expected impact: high.

### 2. Live observations mostly affect observed cells, not the full map

Current behavior:

- [baseline.py](baseline.py) blends observed class counts into directly observed cells
- [history_priors.py](history_priors.py) uses live observations to reweight historical round priors
- [prediction_variants.py](prediction_variants.py) blends predictions and observed cells

What is missing:

- unsampled cells do not receive a strong learned update from live simulation evidence
- settlement stats from `simulate` are only used as coarse round summaries, not as structured predictive features for the rest of the map

This is the largest modeling gap.

The docs say `simulate` returns:

- `population`
- `food`
- `wealth`
- `defense`
- `has_port`
- `alive`
- `owner_id`

Those are direct clues about growth, conflict, trade, starvation, and regime behavior. Right now they are not driving the full-map posterior strongly enough.

Highest-value fix:

- build a second-stage post-observation model that takes round-level live features and updates all cells, not just observed ones
- feed observed settlement summaries into the learned model, not just into a heuristic regime reweighting step
- propagate evidence spatially from observed windows into nearby unobserved windows using learned local transition behavior

Expected impact: very high.

### 3. Regime inference exists, but it is still too shallow

[history_priors.py](history_priors.py) already tries to infer which historical rounds the current round resembles.

That is directionally correct, because the docs explicitly say hidden parameters are shared across all 5 seeds in a round.

However, the current regime model still mainly uses:

- observed class frequencies
- simple settlement summary aggregates
- a mixture over historical terrain/settlement priors

It does not yet infer the actual latent behavior axes implied by the mechanics page:

- growth intensity
- naval/trade strength
- conflict/aggression
- winter harshness/collapse rate
- ruin persistence versus forest reclamation/rebuild rate

Highest-value fix:

- explicitly model round-wide latent axes
- infer them from early cross-seed observations
- let those latent estimates affect both query planning and the final prediction tensor

Concrete examples from the docs:

- high `owner_id` fragmentation and higher `defense` likely signal more conflict
- more ports plus stronger wealth/food profiles likely signal trade-friendly dynamics
- low food and many dead settlements likely signal harsher winter/collapse dynamics

Expected impact: high.

### 4. The current feature set is still too local for a 50-year world simulation

[feature_engineering.py](feature_engineering.py) is better than the original scaffold, but it is still mostly local:

- radius-1 terrain counts
- distances to settlement/port/ocean/mountain
- coarse seed-level ratios

The mechanics doc describes longer-range dynamics:

- ports trading over distance
- longships extending raid range
- mountain chains shaping movement
- coastal topology and fjords mattering for naval behavior
- ruins being reclaimed or overtaken by forest over time

Current features are too weak to capture that.

Missing feature families:

- coastline geometry and sheltered-coast/fjord structure
- connected landmass/island identity
- settlement graph structure
- coastal network distance between ports
- mountain barrier and passability proxies
- local competition between nearby settlements
- ruin restoration propensity from nearby healthy settlements

Expected impact: high.

### 5. Calibration is implemented, but currently not convincing

[sklearn_model.py](sklearn_model.py) applies temperature calibration, but the current implementation chooses temperature from training predictions on the same training set.

Observed symptom in [artifacts/history/sklearn_evaluation.json](artifacts/history/sklearn_evaluation.json):

- the chosen temperature is repeatedly `1.0`

That suggests calibration is not actually improving the live predictor materially.

This is not surprising, because in-sample temperature selection is a weak calibration procedure. It mostly confirms the base model instead of correcting it.

Highest-value fix:

- calibrate on held-out rounds, not on the training fit
- allow class-conditional or entropy-bucket calibration, not only one global temperature
- compare calibration by score, not by intuition

Expected impact: medium to high.

### 6. The planner is better, but not yet truly "shared-hidden-parameter first"

[observation_strategy.py](observation_strategy.py) now does adaptive information-gain planning, but the score still looks heuristic:

- predicted entropy
- terrain volatility proxy
- settlement/coast/frontier importance
- repeated-window uncertainty

That is reasonable, but it is still mostly a local tile-ranking policy.

What the docs imply instead:

- early queries should maximize discrimination between competing round regimes
- later queries should reduce uncertainty in the highest-value frontier windows

That means the first queries should be chosen partly for how much they separate historical regime hypotheses, not only for local entropy or coastline density.

Highest-value fix:

- score candidate windows by expected reduction in round-regime uncertainty
- compute which windows best distinguish historical rounds or latent parameter clusters
- only then spend repeat samples on windows whose uncertainty matters to the final tensor

Expected impact: medium to high.

### 7. The system still does one final submit, even though the docs reward safer overwrite behavior

[RUNBOOK.md](RUNBOOK.md) currently says the default is a single inspected final submission.

That is too conservative for this task.

The official docs and [API.md](API.md) say:

- resubmitting the same seed overwrites the earlier submission
- missing a seed yields zero for that seed

Operationally, that means the safer policy is:

1. submit a complete baseline prediction early in the round
2. spend queries and improve the prediction
3. overwrite with the stronger tensor later

This directly protects score against:

- missed rounds
- late-run crashes
- partial submit failures
- human interruption

This is not a cosmetic improvement. Missing round 9 already demonstrated the risk.

Expected impact: high on reliability-adjusted leaderboard performance.

### 8. Offline strategy selection is useful, but it still overestimates live performance

[artifacts/d0a2c894-2162-4d49-86cf-435b9013f3b8/team/score_feedback.json](artifacts/d0a2c894-2162-4d49-86cf-435b9013f3b8/team/score_feedback.json) shows a big gap on round 14:

- expected offline score: about `69.03`
- official score: `41.57`

That gap is too large to ignore.

Possible reasons:

- real live rounds shifted harder than the completed-history replay suggests
- cached-simulation replay is still not matching live observation policy well enough
- the chosen variant is not the only thing that matters; the observation plan itself also needs offline selection

Highest-value fix:

- evaluate planner variants, not only prediction variants
- compare `45+5`, `40+10`, and more regime-oriented early-query policies on historical replay
- store planner-specific offline results the same way variants are stored now

Expected impact: medium.

### 9. The model underuses the mechanics-specific inductive structure

The docs expose a clearer causal story than the current model uses:

- growth depends on adjacent terrain productivity
- trade depends on ports within range
- conflict depends on reach, desperation, and faction structure
- winter drives collapse
- environment drives ruin recovery or forest takeover

The current solver mostly learns this indirectly from static map context.

That is too weak.

Highest-value fix:

- add engineered proxies for each phase
- growth proxy: land productivity, local terrain mix, settlement crowding
- trade proxy: coast access, port graph connectivity, sea-reach density
- conflict proxy: nearby rival settlements, owner fragmentation, coastal raid reach
- winter-collapse proxy: isolated settlements, food-poor observed windows, low-defense settlements
- environment proxy: forest adjacency, ruin proximity, rebuildable coastal sites

Expected impact: medium to high.

### 10. Analysis artifacts are good enough to operate, but not yet ideal for score debugging

Current artifacts are already useful, but there are still diagnosis blind spots:

- some older reports were produced before the current variant-selection stack
- some report fields are missing or `null` in places where they should help post-round review
- round-level score regressions are visible, but not all of them can be decomposed into "model issue" versus "planner issue" versus "round shift"

This is not the top scoring blocker, but it slows iteration.

Expected impact: medium on iteration speed, low on immediate round score.

## Prioritized Score Improvements

## P0: Change The Operating Policy

These should be treated as top priority because they improve score quickly and safely.

- Switch from "one final submit" to "early safe submit, later overwrite".
- Keep a lightweight baseline submission ready before heavy simulation.
- Continue using all 50 queries, but do not make score depend on one late perfect run.
- Record which submission version was early-safe versus final-overwrite.

Why this matters:

- the docs explicitly allow overwrite
- missing one seed gives zero
- leaderboard weighting increases over time, so later operational misses are expensive

## P1: Make The Model Care About Entropy

- weight training examples by target entropy from `/analysis`
- separately report performance on high-entropy cells
- add a specialized frontier/dynamic-cell model
- route static terrain through a simpler prior path and spend model capacity elsewhere

Why this matters:

- this is the most direct alignment with the official score formula

## P1: Make Live Observations Affect The Whole Map

- create a post-observation model, not only local observed-cell blending
- feed live round summaries and seed summaries into the learned predictor
- let observed settlement stats influence predictions for unsampled cells
- add spatial propagation from observed windows into nearby cells

Why this matters:

- this is the biggest modeling gap between current code and the task

## P1: Improve Regime Inference

- infer latent round axes explicitly
- score early windows by regime-discrimination power
- update both the planner and final prediction variant from those inferred axes

Why this matters:

- the docs say hidden parameters are shared across seeds
- that is the main cross-seed leverage in the task

## P2: Expand Features Around Mechanics

- add coastal topology and fjord features
- add settlement-network and port-network features
- add mountain barrier/passability features
- add competition and rebuild-risk features

Why this matters:

- the current radius-1/local-distance feature set is too weak for 50-year dynamics

## P2: Fix Calibration Properly

- calibrate on held-out rounds
- test per-class or entropy-bucket calibration
- compare calibration by official-like offline score

Why this matters:

- current calibration appears mostly inactive

## P2: Evaluate Planners, Not Just Variants

- replay multiple observation policies offline
- compare score per query, not only final score
- allow "less than 50" if historical replay shows diminishing returns in a round type

Why this matters:

- current planner is improved, but still heuristic

## Concrete Next Experiments

These are the best next experiments to run in order.

1. Add entropy-weighted sample weights to the sklearn training path and compare against the current unweighted model.
2. Add a post-observation feature path that includes live round summaries and seed summaries when predicting unsampled cells.
3. Add planner evaluation to [prediction_variants.py](prediction_variants.py), so query policy is selected offline the same way prediction variant is selected now.
4. Change operations to early-safe submit plus final overwrite.
5. Add a richer phase-inspired feature set from the mechanics doc.
6. Replace in-sample temperature tuning with held-out round calibration.

## Bottom Line

The current system is viable, but still under-optimized for the actual game.

The most important conclusion is this:

- the repo no longer needs more scaffolding work
- the next score gains will come from metric alignment, better use of live observations, stronger regime inference, and safer round operations

If only one principle should drive the next implementation round, it should be:

predict the dynamic cells better, and use early live evidence to update the full-map posterior rather than only the sampled windows.

# Astar Island Task-Solving Analysis

This document analyzes how to solve the NM i AI Astar Island task from the public task docs and the live API behavior observed on March 20, 2026.

Primary task sources:

- https://app.ainm.no/docs/astar-island/overview
- https://app.ainm.no/docs/astar-island/mechanics
- https://app.ainm.no/docs/astar-island/endpoint
- https://app.ainm.no/docs/astar-island/scoring
- https://app.ainm.no/docs/astar-island/quickstart

This document is intentionally system-oriented. It explains what must exist in a serious solver and why.

## 1. What The Task Really Is

This is not a standard classification problem.

It is a constrained probabilistic inference problem over a hidden stochastic simulator.

The actual task is:

1. read the public initial state for 5 seeds
2. use at most 50 simulation queries across the whole round
3. infer the round-wide hidden dynamics from sparse viewport observations
4. estimate the full per-cell outcome distribution after 50 simulated years
5. submit one `H x W x 6` probability tensor per seed

That means the winning system is not just:

- "predict the terrain class"

It is:

- "infer a distribution over future world states under hidden parameters and stochastic rollouts"

## 2. What The Scoring Implies

The scoring function changes the optimal engineering approach.

The docs define the score as entropy-weighted KL divergence between:

- `p`: organizer ground truth distribution from many Monte Carlo runs
- `q`: your submitted distribution

Implications:

1. Calibration matters more than argmax accuracy.
2. Static cells matter less because low-entropy cells are down-weighted or effectively ignored.
3. Dynamic frontiers matter most: settlements, ports, ruins, reclaimable land, and conflict zones.
4. A single zero in `q` can be catastrophic when `p_i > 0`.

So the model should optimize for:

- probability quality
- uncertainty estimation
- safe probability floors

Not for:

- hard labels only
- pure majority-class prediction
- overconfident one-hot outputs

## 3. What Is Observable Versus Hidden

### 3.1 Publicly observable

From `GET /astar-island/rounds/{round_id}` you can get:

- map width and height
- 5 seeds
- full initial terrain grid for each seed
- initial settlement positions
- whether an initial settlement has a port

### 3.2 Hidden but partially inferable

The docs explicitly say that initial states do not expose internal settlement stats.

Hidden at round start:

- population
- food
- wealth
- defense
- tech level
- longship ownership
- faction dynamics
- hidden round parameters controlling growth, conflict, trade, winter severity, and environment

### 3.3 Observable only through simulation queries

`POST /astar-island/simulate` reveals, for one stochastic run and one viewport:

- final terrain grid in that viewport
- settlements in that viewport
- settlement stats including population, food, wealth, defense, owner_id, and port status

This is the key task structure:

- map seed differs per seed
- hidden parameters are shared by the round
- stochastic sim seed differs per query

So information learned from one seed can transfer to the others.

## 4. What The World Mechanics Mean For Modeling

The mechanics docs imply a small number of dominant causal drivers:

1. Coastlines and ports strongly affect trade and long-range interaction.
2. Adjacent terrain, especially forests and coast access, affects settlement viability.
3. Winter and food stress drive collapse pressure.
4. Conflict and raids create ruin and allegiance shifts.
5. Environment can reclaim ruins into forest or plains.
6. Successful settlements can rebuild ruins or found new settlements.

This suggests that the most informative features are not raw coordinates alone. They include:

- coastal adjacency
- local forest count
- local mountain barriers
- settlement neighborhood density
- distance to ports
- distance to coast
- ruin accessibility
- conflict exposure from nearby rival settlements

## 5. What A Serious Solver Needs

## 5.1 Round ingestion

The solver must reliably capture:

- current round metadata
- all 5 initial states
- budget state
- prior submissions and later analysis artifacts

## 5.2 Query planning

Because only 50 queries are available per round, the solver needs an explicit query planner.

Good query plans concentrate on:

- settlement clusters
- ports and coasts
- contested frontiers
- representative regions across multiple seeds

Bad query plans waste budget on:

- open ocean
- mountains
- redundant coverage of obviously static plains

## 5.3 Observation accumulation

The solver should store every simulation result as reusable evidence:

- viewport geometry
- observed terrain outcome
- settlement stats
- seed index
- query number

Even a simple empirical frequency estimate per observed cell is better than ignoring observations.

## 5.4 Probabilistic model layer

At minimum, the solver needs:

- a prior from the initial grid and settlement layout
- an observation update rule that incorporates simulate samples
- floor-and-renormalize safety before submission

Stronger versions should add:

- feature engineering around settlements and terrain
- per-cell or per-region predictive models
- cross-seed transfer of round-level behavior
- post-round learning from `/analysis/{round_id}/{seed_index}`

## 5.5 Submission management

The solver must always submit all 5 seeds.

The docs make this explicit: missing a seed gives a zero for that seed. Even a weak submission is better than no submission.

## 6. Recommended Modeling Roadmap

### Phase 1: Safe baseline

Use:

- terrain prior from initial grid
- settlement/port prior overrides
- probability floor

This is what the original scaffold did.

### Phase 2: Observation-informed baseline

Add:

- a viewport plan
- simulator calls
- per-cell empirical class counts from observed windows
- posterior blending of baseline prior with observed outcomes

This is the first practical improvement because it uses the actual task budget.

### Phase 3: Learned outcome model

Train on completed rounds using `/analysis`:

- derive supervised targets from organizer ground truth tensors
- build features from initial map topology and visible settlements
- fit models for class probabilities or class logits

Likely useful toolkits:

- `numpy`
- `scipy`
- `pandas` or `polars`
- `scikit-learn`
- gradient boosting libraries if allowed in your environment

### Phase 4: Round-level parameter inference

A stronger system should infer round-global latent behavior:

- aggressive conflict round
- high growth round
- harsh winter round
- strong trade round

This can be approximated by:

- repeated queries on strategically chosen windows
- summary statistics over observed outcomes
- using those statistics as inputs to seed-specific prediction models

## 7. Operational Implications

## 7.1 Public versus authenticated API surface

The task docs describe `/rounds`, `/rounds/{round_id}`, and `/leaderboard` as public.

Live verification on March 20, 2026 confirmed:

- `GET /astar-island/rounds` works without auth
- `GET /astar-island/rounds/{round_id}` works without auth
- `GET /astar-island/budget` returns `401 Missing token` without auth
- round payloads expose `prediction_window_minutes`, `started_at`, and `closes_at`
- live rounds so far have used `165` minute windows, but automation should still trust the API timestamps rather than hard-coding cadence

The scaffold should therefore treat public reads separately from team-authenticated actions.

## 7.2 Cloud Run note

The generic NM i AI Google Cloud page still lists Astar as if it required a public `/solve` endpoint.

That is inconsistent with the Astar-specific docs and the actual API contract.

For Astar:

- the organizer submission surface is the organizer REST API
- Cloud Run is optional infrastructure for your own batch worker or internal control plane
- Cloud Run Jobs fit this task better than a public Cloud Run service

## 8. What The Updated Scaffold Should Cover

The scaffold should provide:

1. public round ingestion without requiring a token
2. token-gated budget, simulate, and submit handling
3. `.env`-driven configuration
4. artifact capture for round detail, budgets, simulations, predictions, and submit responses
5. a budget-aware observation planner so the round-level query cap is usable immediately
   Current default strategy: tile each `40x40` map once with `9` windows before using repeats.
6. a simple observation-informed posterior update
7. history-cache sync and reuse from `/analysis`
8. an offline scorer and repeatable evaluation loop on cached completed rounds
9. a dataset builder for later model work
10. explicit local validation before submission
11. optional GCS artifact upload
12. Cloud Run Job deployment support for automated round execution
13. a default round flow that ingests newly completed rounds into training before predicting the next active round
14. a looped watcher that records official server round scores and automatically processes each new active round

## 9. What Still Remains A Real Modeling Problem

Even after the scaffold is improved, the main unsolved work is still model quality.

The scaffold can make it easy to:

- collect data
- run rounds reproducibly
- avoid API mistakes
- ship safe predictions

It cannot, by itself, solve:

- latent parameter inference
- strong uncertainty calibration
- full-map generalization from limited windows

Those remain the core competition work.

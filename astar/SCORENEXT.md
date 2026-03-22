# Next-Wave Score Plan

This file is the focused follow-up plan after [SCOREIMPROV.md](SCOREIMPROV.md) and the completed implementation board in [SCORETASKS.md](SCORETASKS.md).

It is intentionally narrower than those files. The goal here is not more scaffolding. The goal is to move the solver past the current `~73-76` range and improve official round scores.

Primary references:

- [SCOREIMPROV.md](SCOREIMPROV.md)
- [SCORETASKS.md](SCORETASKS.md)
- [README.md](README.md)
- [ANALYSIS.md](ANALYSIS.md)
- [API.md](API.md)
- [run_round.py](run_round.py)
- [prediction_variants.py](prediction_variants.py)
- [observation_strategy.py](observation_strategy.py)
- [history_priors.py](history_priors.py)
- [sklearn_model.py](sklearn_model.py)
- [artifacts/history/variant_selection.json](artifacts/history/variant_selection.json)
- [artifacts/history/sklearn_evaluation.json](artifacts/history/sklearn_evaluation.json)
- [artifacts/8f664aed-8839-4c85-bed0-77a2cac7c6f5/report.json](artifacts/8f664aed-8839-4c85-bed0-77a2cac7c6f5/report.json)
- [artifacts/8f664aed-8839-4c85-bed0-77a2cac7c6f5/team/score_feedback.json](artifacts/8f664aed-8839-4c85-bed0-77a2cac7c6f5/team/score_feedback.json)

Official docs:

- Overview: https://app.ainm.no/docs/astar-island/overview
- Mechanics: https://app.ainm.no/docs/astar-island/mechanics
- Endpoints: https://app.ainm.no/docs/astar-island/endpoint
- Scoring: https://app.ainm.no/docs/astar-island/scoring
- Quickstart: https://app.ainm.no/docs/astar-island/quickstart

## Current Position

The current solver is no longer failing because of missing infrastructure.

As of round 16:

- official score: `75.4904` in [artifacts/8f664aed-8839-4c85-bed0-77a2cac7c6f5/team/score_feedback.json](artifacts/8f664aed-8839-4c85-bed0-77a2cac7c6f5/team/score_feedback.json)
- selected live variant: `sklearn_observation_context`
- offline mean round score for that variant: `73.1990` in [artifacts/history/variant_selection.json](artifacts/history/variant_selection.json)

That means the current live performance is roughly in line with offline expectation. The system is behaving as designed. The problem is that the design itself still tops out around the mid-70s.

## Why The Current Ceiling Exists

### 1. The model is still mostly local

The current learned path in [sklearn_model.py](sklearn_model.py) and [feature_engineering.py](feature_engineering.py) is a tabular local model. It sees useful structure, but it does not explicitly model multi-step world dynamics such as:

- expansion corridors
- port-supported development
- conflict fronts
- ruin and forest recovery patterns

That is enough to be competitive, but not enough to fully exploit a 50-year simulator.

### 2. Live evidence is still under-propagated

[prediction_variants.py](prediction_variants.py) now has observation-conditioned variants, but the final posterior still stays conservative on unsampled cells.

Round 16 confirms this in [artifacts/8f664aed-8839-4c85-bed0-77a2cac7c6f5/report.json](artifacts/8f664aed-8839-4c85-bed0-77a2cac7c6f5/report.json):

- every seed ended with `0` port argmax cells
- every seed ended with `0` ruin argmax cells
- settlements remained very sparse in argmax space

But [artifacts/8f664aed-8839-4c85-bed0-77a2cac7c6f5/history/regime_summary.json](artifacts/8f664aed-8839-4c85-bed0-77a2cac7c6f5/history/regime_summary.json) shows the observed round itself was materially more active than that.

So the solver still learns from observations, but not strongly enough.

### 3. The query budget is used for coverage first, but not enough for uncertainty estimation

[observation_strategy.py](observation_strategy.py) is now much better than the old planner. It uses exploration, regime disagreement, and full-round coverage.

But the scoring docs reward probability quality, not only map coverage.

One sweep across the map is good for discovery.
It is not enough for estimating the true class distribution in volatile windows.

### 4. Variant selection is still based on replay, not a richer learned post-observation model

[artifacts/history/variant_selection.json](artifacts/history/variant_selection.json) shows the current best variant is `sklearn_observation_context`.

That is useful, but it is still a relatively shallow family:

- baseline/history prior
- sklearn prior
- observation-conditioned adjustments
- simple ensembles

There is not yet a dedicated second-stage predictor that says:
"Given what this round looks like after early observations, how should the whole map posterior move?"

## Highest-Yield Next Steps

### Priority 1: Add A Round-Conditioned Global Post-Observation Model

Why this is first:

- It directly targets the main remaining gap.
- It uses the strongest information the docs allow: shared hidden parameters across all 5 seeds plus structured `simulate` outputs.
- It should improve unsampled cells, where the current solver is weakest.

Implementation direction:

- Build a second-stage model on top of [history_dataset.py](history_dataset.py).
- Training examples should include:
  - initial cell/local features
  - round-level summary features derived from partial observations
  - optional seed-level summary features
- At replay time, synthesize the same kind of observation summaries from cached completed rounds.
- At live time, use actual early-round observation summaries to shift the entire tensor.

Concrete feature groups:

- observed class mix across the round
- observed settlement density
- observed port rate
- observed alive/dead settlement ratio
- observed owner fragmentation
- observed defense / wealth / food / population means
- per-seed observation summaries plus global pooled summaries

Where it should live:

- new post-observation dataset builder near [history_dataset.py](history_dataset.py)
- new model path near [sklearn_model.py](sklearn_model.py)
- variant integration in [prediction_variants.py](prediction_variants.py)

Current repo status:

- A first in-repo version of this now exists as `sklearn_learned_post_observation`.
- It is implemented as a lightweight residual model trained from synthetic replay observations over cached completed rounds.
- The main remaining extension within this priority is richer per-seed observation-summary conditioning if the current global-summary model plateaus.

Expected impact: very high.

### Priority 2: Split Query Policy Into Discovery Then Uncertainty Estimation

Why this is second:

- The docs give only `50` shared queries.
- The current sweep-first behavior is correct as a base policy, but the last queries should be used to estimate probability spread, not just maximize unique coverage.

Implementation direction:

- Keep the first `45` queries as one sweep over the 5 maps.
- Reserve the last `5` for repeated sampling of the most score-critical windows.
- Choose repeat windows using a score that combines:
  - regime disagreement
  - local settlement/port/frontier importance
  - current posterior entropy
  - dynamic-cell historical volatility

Important rule constraint:

- stay at `50` total queries
- use only documented `simulate`
- do not infer hidden state from anything outside returned payloads

Where it should live:

- [observation_strategy.py](observation_strategy.py)
- report fields in [reporting.py](reporting.py)

Expected impact: high.

### Priority 3: Add Rare-Class Probability Lifting For Port / Ruin / Settlement Frontiers

Why this is third:

- The current final tensors are too conservative on rare but score-relevant classes.
- Round 16 clearly showed underprediction of ports and ruins.

Implementation direction:

- Train explicit specialized heads or calibrators for:
  - settlement vs non-settlement
  - port vs non-port
  - ruin vs non-ruin
- Apply them only in candidate regions:
  - near coasts
  - near existing settlements
  - near conflict-heavy observed windows
  - near historically volatile cells
- Blend those specialized outputs back into the 6-class tensor rather than replacing the main model.

Where it should live:

- [sklearn_model.py](sklearn_model.py)
- [prediction_variants.py](prediction_variants.py)

Expected impact: medium to high.

### Priority 4: Make Regime Inference Explicit Instead Of Implicit

Why this is fourth:

- [history_priors.py](history_priors.py) already reweights historical rounds.
- But it still does this as a soft heuristic mixture, not as explicit latent-axis inference.

Implementation direction:

- Convert regime inference into named latent axes:
  - development
  - conflict
  - trade/naval
  - collapse/harshness
- Estimate these axes from early observations.
- Feed those axes into:
  - the global post-observation model
  - the query planner
  - the pre-submit diagnostics

Where it should live:

- [history_priors.py](history_priors.py)
- [observation_strategy.py](observation_strategy.py)
- [prediction_variants.py](prediction_variants.py)

Expected impact: medium to high.

### Priority 5: Promote Live Candidate Comparison Before Final Overwrite

Why this matters:

- The docs allow overwrite submission.
- We already use staged submit in [run_round.py](run_round.py).
- That should now be exploited more aggressively.

Implementation direction:

- Keep the early safe submit exactly as now.
- After the full query budget is spent, build multiple final candidates, not only one:
  - current best offline variant
  - post-observation global model
  - rare-class-lifted variant
  - possibly one conservative ensemble
- Score candidates using offline signals plus current-round diagnostics.
- Submit the best final candidate as the overwrite.

Where it should live:

- [run_round.py](run_round.py)
- [prediction_variants.py](prediction_variants.py)

Expected impact: medium.

## What Not To Spend Time On Next

These are lower-yield than the priorities above:

- more deployment work
- more loop/supervisor work
- more baseline heuristic tuning without better live evidence usage
- more history caching work
- more one-shot local feature tweaks without a stronger post-observation stage

Those are not the current bottleneck.

## Recommended Execution Order

1. Round-conditioned global post-observation model
2. Discovery-then-repeat query policy
3. Rare-class probability lifting
4. Explicit latent-axis regime inference
5. Multi-candidate final overwrite selection

## Success Criteria

This next-wave plan is working if:

- offline variant selection beats the current `73.1990` mean round score
- official rounds become less conservative on settlement/port/ruin outcomes
- final overwrite tensors differ meaningfully from the safe submit
- score feedback stays above the old plateau instead of oscillating around mid-70s

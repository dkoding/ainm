# Astar Island API Reference For NM i AI

This document is a task-focused summary of the Astar Island API and the operational details that matter for a competition solver.

Primary sources:

- https://app.ainm.no/docs/astar-island/overview
- https://app.ainm.no/docs/astar-island/mechanics
- https://app.ainm.no/docs/astar-island/endpoint
- https://app.ainm.no/docs/astar-island/scoring
- https://app.ainm.no/docs/astar-island/quickstart

Live API checks on March 20, 2026:

- `GET https://api.ainm.no/astar-island/rounds` returned `200` without auth
- `GET https://api.ainm.no/astar-island/rounds/{round_id}` returned `200` without auth
- `GET https://api.ainm.no/astar-island/budget` returned `401 {"detail":"Missing token"}` without auth

## 1. Base URL

The base URL is:

```text
https://api.ainm.no/astar-island
```

## 2. Authentication

The task docs describe two authentication options:

1. cookie auth via `access_token`
2. bearer auth via `Authorization: Bearer <jwt>`

The same JWT is used for both.

For automation, bearer auth is simpler.

You obtain the JWT by logging in at `app.ainm.no` and copying the browser `access_token`.

## 3. Public Versus Team Endpoints

### Public

- `GET /astar-island/rounds`
- `GET /astar-island/rounds/{round_id}`
- `GET /astar-island/leaderboard`

### Team-authenticated

- `GET /astar-island/budget`
- `POST /astar-island/simulate`
- `POST /astar-island/submit`
- `GET /astar-island/my-rounds`
- `GET /astar-island/my-predictions/{round_id}`
- `GET /astar-island/analysis/{round_id}/{seed_index}`

## 4. Round Metadata

## 4.1 `GET /astar-island/rounds`

Purpose:

- list rounds
- detect the active round
- inspect timing and weighting

Important fields:

- `id`
- `round_number`
- `event_date`
- `status`
- `map_width`
- `map_height`
- `prediction_window_minutes`
- `started_at`
- `closes_at`
- `round_weight`

Round status values:

- `pending`
- `active`
- `scoring`
- `completed`

## 4.2 `GET /astar-island/rounds/{round_id}`

Purpose:

- fetch full round detail and the initial state for all 5 seeds

Important fields:

- `map_width`
- `map_height`
- `seeds_count`
- `initial_states`

Each `initial_states[i]` contains:

- `grid`: `height x width` terrain codes
- `settlements`: `[{x, y, has_port, alive}, ...]`

Important limitation:

- internal settlement stats are not exposed here

## 5. Terrain Codes And Submission Classes

The internal grid uses 8 terrain codes, but submission collapses them into 6 classes.

Internal codes:

- `10`: Ocean
- `11`: Plains
- `0`: Empty
- `1`: Settlement
- `2`: Port
- `3`: Ruin
- `4`: Forest
- `5`: Mountain

Submission class indices:

- `0`: Empty class, which includes Ocean, Plains, and Empty
- `1`: Settlement
- `2`: Port
- `3`: Ruin
- `4`: Forest
- `5`: Mountain

This mapping matters both for:

- prediction tensors
- converting observed simulation grids into class counts

## 6. Query Budget

## 6.1 `GET /astar-island/budget`

Purpose:

- check remaining simulation budget for the active round

Important fields:

- `round_id`
- `queries_used`
- `queries_max`
- `active`

Docs state:

- maximum queries per round: `50`

## 7. Simulation Endpoint

## 7.1 `POST /astar-island/simulate`

Purpose:

- reveal one viewport from one stochastic 50-year simulation

Request fields:

- `round_id`
- `seed_index`
- `viewport_x`
- `viewport_y`
- `viewport_w`
- `viewport_h`

Constraints from docs:

- `seed_index`: `0..4`
- `viewport_w`: `5..15`
- `viewport_h`: `5..15`

Response fields:

- `grid`: viewport-only terrain grid
- `settlements`: viewport-only settlements with full stats
- `viewport`
- `width`
- `height`
- `queries_used`
- `queries_max`

Important settlement response fields:

- `x`
- `y`
- `population`
- `food`
- `wealth`
- `defense`
- `has_port`
- `alive`
- `owner_id`

Key operational fact:

- each simulate call uses a different stochastic sim seed

That means repeated queries against the same viewport are meaningful. They produce samples from the hidden outcome distribution, not duplicate deterministic answers.

Docs rate limit:

- `POST /simulate`: `5 requests/second per team`

Common error conditions:

- round not active
- invalid `seed_index`
- not on a team
- budget exhausted
- rate limit exceeded

## 8. Submission Endpoint

## 8.1 `POST /astar-island/submit`

Purpose:

- submit one probability tensor for one seed

Request fields:

- `round_id`
- `seed_index`
- `prediction`

Prediction format:

- shape: `H x W x 6`
- indexing: `prediction[y][x][class_index]`
- each cell must have exactly 6 non-negative probabilities
- each cell must sum to `1.0` within the task tolerance

Docs make two critical points:

1. you must submit all 5 seeds for a complete round score
2. resubmitting the same seed overwrites the previous submission

So:

- always submit something for every seed
- last submission wins

Docs rate limit:

- `POST /submit`: `2 requests/second per team`

Common validation failures:

- wrong number of rows
- wrong number of columns
- wrong probability vector length
- probabilities not summing to 1
- negative probability

## 9. Team State Endpoints

## 9.1 `GET /astar-island/my-rounds`

Purpose:

- inspect team round performance and query usage

Useful fields:

- `round_score`
- `seed_scores`
- `seeds_submitted`
- `rank`
- `total_teams`
- `queries_used`
- `queries_max`
- `initial_grid`

## 9.2 `GET /astar-island/my-predictions/{round_id}`

Purpose:

- inspect what your team actually submitted

Useful fields:

- `seed_index`
- `argmax_grid`
- `confidence_grid`
- `score`
- `submitted_at`

## 9.3 `GET /astar-island/analysis/{round_id}/{seed_index}`

Purpose:

- compare your submitted tensor with the organizer ground-truth tensor after scoring

Useful fields:

- `prediction`
- `ground_truth`
- `score`
- `width`
- `height`
- `initial_grid`

This endpoint is the main post-round learning surface. It is what makes supervised improvement across rounds possible.

## 10. Leaderboard Endpoint

## 10.1 `GET /astar-island/leaderboard`

Purpose:

- inspect public team ranking

Useful fields:

- `team_id`
- `team_name`
- `weighted_score`
- `rounds_participated`
- `hot_streak_score`
- `rank`
- `is_verified`

Docs say leaderboard score is the best weighted round score across all rounds.

## 11. Scoring Constraints That Affect API Usage

The scoring docs define:

- entropy-weighted KL divergence
- exponential conversion to a `0..100` score

The practical API implication is:

- never submit zero probability for any class

Safe pattern:

```python
prediction = np.maximum(prediction, 0.01)
prediction = prediction / prediction.sum(axis=-1, keepdims=True)
```

This is not optional defensive programming. It is a direct consequence of the scoring rule.

## 12. Practical Usage Pattern

The correct round loop is:

1. `GET /rounds`
2. identify the active round
3. `GET /rounds/{round_id}`
4. optionally `GET /budget`
5. `POST /simulate` up to budget
6. build one tensor per seed
7. `POST /submit` once per seed
8. later inspect `my-rounds`, `my-predictions`, and `analysis`

That is the actual submission surface for Astar.

It is not a public `/solve` endpoint flow.

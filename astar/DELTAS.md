# Astar Delta Review

This file records the current delta status after the latest implementation pass.

References:

- [ASTARTASKS.md](ASTARTASKS.md)
- [README.md](README.md)
- [RUNBOOK.md](RUNBOOK.md)
- [ANALYSIS.md](ANALYSIS.md)
- [API.md](API.md)
- [TASKS.md](TASKS.md)

## Local Delta Status

There are no remaining local code or repo-documentation deltas from the previously identified list.

The following items are now implemented in-repo:

- paced POST handling and request metadata capture
- adaptive information-gain query planning
- live-evidence-driven repeat sampling
- broader round-regime inference using observed settlement summaries
- variant evaluation with replayed observations, preferring real cached simulations when available
- strategy-cache invalidation by config/model signature
- automatic baseline tuning
- calibrated sklearn probabilities
- richer global and distance-based features
- official score feedback with automatic variant fallback for repeated regressions
- loop event logs, heartbeat, lock file, and a lightweight local supervisor
- updated docs and expanded tests

## Non-Repo Note

The official organizer endpoint page still contains a public/auth wording ambiguity that conflicts with the live API behavior and the endpoint table.

That is outside this repository. The local implementation already follows the real API behavior correctly, as documented in [API.md](API.md) and implemented in [astar_client.py](astar_client.py).

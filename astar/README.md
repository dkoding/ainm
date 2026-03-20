# Astar Island

This directory contains a documented and automation-ready scaffold for the Astar Island task.

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
- `astar_client.py`: public/team API wrapper for rounds, budget, simulate, submit, leaderboard, and post-round analysis.
- `baseline.py`: safe prior generator plus observation-informed posterior blending.
- `observation_strategy.py`: simple viewport planner for spending simulator budget on high-value cells.
- `run_round.py`: env-driven round runner for public sync, optional simulation, prediction writing, and optional submission.
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

Configure local env:

```bash
cp .env.example .env
```

Public dry run without a token:

```bash
python3 run_round.py --no-simulate --no-submit
```

Run a small observation-informed round locally:

```bash
python3 run_round.py --token "$AINM_ACCESS_TOKEN" --simulate --queries-per-seed 4 --no-submit
```

Submit the active round:

```bash
python3 run_round.py --token "$AINM_ACCESS_TOKEN" --simulate --queries-per-seed 4 --submit
```

Deploy as a Cloud Run Job:

```bash
./deploy_cloud_run_job.sh
```

Notes:

- The task docs describe Astar as a direct API task. You submit tensors to the organizer API; you do not need to expose a public `/solve` endpoint for the core task flow.
- `GET /rounds` and `GET /rounds/{round_id}` are public. Budget, simulate, submit, and team analysis endpoints require a token.
- The updated scaffold can spend simulator queries and blend observed outcomes back into the per-cell probability tensor.
- For deployed Cloud Run Jobs, prefer storing `AINM_ACCESS_TOKEN` in Secret Manager and wiring it through `ASTAR_TOKEN_SECRET_NAME`.

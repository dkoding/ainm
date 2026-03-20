# Astar Island

This directory contains a baseline local client for the Astar Island task.

What the docs require:

- Authenticate with your `access_token` JWT from `app.ainm.no`.
- Use `https://api.ainm.no/astar-island/...`.
- Query the active round and round details.
- Submit one `H x W x 6` probability tensor per seed.
- There are 5 seeds per round and 50 total simulation queries per round.
- Never assign `0.0` to any class; use a probability floor and renormalize.

What is included here:

- `astar_client.py`: API wrapper for rounds, budget, simulate, and submit.
- `baseline.py`: safe prior generator from the initial terrain and settlement positions.
- `submit_baseline.py`: CLI for dry runs or direct submission.

Install:

```bash
cd astar
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Dry run:

```bash
python3 submit_baseline.py --token "$AINM_ACCESS_TOKEN"
```

Submit the baseline for the active round:

```bash
python3 submit_baseline.py --token "$AINM_ACCESS_TOKEN" --submit
```

Notes:

- The task docs describe Astar as a direct API task. You submit tensors to the organizer API; you do not need to expose a public `/solve` endpoint for the core task flow.
- This baseline does not spend any simulation queries yet. It only uses the public round detail endpoint and initial states.
- The main manual blocker is the JWT token: you need to copy `access_token` from your browser after logging in.

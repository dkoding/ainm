# Tripletex

This directory contains a FastAPI scaffold for the Tripletex task.

What the docs require:

- Public HTTPS endpoint.
- `POST /solve` with JSON body containing `prompt`, optional `files`, and `tripletex_credentials`.
- 300 second timeout.
- All Tripletex API calls must go through the provided proxy `base_url`.
- Auth to Tripletex is Basic Auth with username `0` and password `session_token`.
- Your endpoint must return `{"status":"completed"}` on success.

What is included here:

- `app/main.py`: `/health` and `/solve` endpoints.
- `app/client.py`: small Tripletex API wrapper.
- `app/attachments.py`: attachment preparation with text and PDF extraction.
- `app/tasking.py`: normalized task-analysis and command models.
- `app/openapi_registry.py`: OpenAPI-backed endpoint registry and command validation.
- `app/planner.py`: Vertex AI / Gemini task analysis plus spec-guided action planning.
- `app/execution.py`: command-style Tripletex executor with OpenAPI validation.
- `app/solver.py`: request validation, attachment persistence, planning, execution, and API key protection.
- `Dockerfile`: Cloud Run deployment image.
- `.env.example`: local configuration template.

Local run:

```bash
cd tripletex
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Environment:

- `GOOGLE_CLOUD_PROJECT`: required for Vertex AI planning.
- `GOOGLE_CLOUD_LOCATION`: defaults to `europe-north1`.
- `GEMINI_MODEL`: defaults to `gemini-2.5-pro`.
- `CLOUD_RUN_SERVICE_NAME`: defaults to `tripletex-agent`.
- `CLOUD_RUN_REGION`: defaults to `europe-north1`.
- `TRIPLETEX_API_KEY`: optional shared secret checked against `Authorization: Bearer ...`.
- `TRIPLETEX_MAX_STEPS`: defaults to `8`.
- `TRIPLETEX_REQUEST_TIMEOUT`: defaults to `30`.
- `TRIPLETEX_ALLOW_NOOP`: set to `true` only for wiring tests if Vertex AI is not configured.

Cloud Run deploy:

```bash
./deploy_cloud_run.sh
```

Notes:

- The current baseline architecture is: normalized task analysis -> Gemini planning -> command executor -> Tripletex API.
- Planned commands are validated against the saved `docs/openapi.json` spec before execution.
- Attachments are saved to a temporary request directory, summarized for the planner, and PDFs are text-extracted when possible.
- PDF and image attachments can also be passed to Gemini through Vertex AI multimodal input.
- This is still a baseline scaffold, not a completed competition solver.

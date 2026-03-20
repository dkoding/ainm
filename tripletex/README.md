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
- `app/generated_methods.py`: OpenAPI-derived generated endpoint method catalog and method-call to command conversion.
- `app/internal_tasks.py`: internal vocabulary and canonical payload extraction for deterministic flow routing.
- `app/openapi_registry.py`: OpenAPI-backed endpoint registry and command validation.
- `app/planner.py`: Vertex AI / Gemini task analysis plus spec-guided method planning.
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
- `TRIPLETEX_MAX_PLANNER_STEPS`: defaults to `12`.
- `TRIPLETEX_MAX_API_CALLS`: defaults to `12`.
- `TRIPLETEX_MAX_STEPS`: legacy compatibility fallback for both budgets.
- `TRIPLETEX_REQUEST_TIMEOUT`: defaults to `30`.
- `TRIPLETEX_ALLOW_NOOP`: set to `true` only for wiring tests if Vertex AI is not configured.

Cloud Run deploy:

```bash
./deploy_cloud_run.sh
```

Notes:

- The current baseline architecture is: normalized task analysis -> curated workflow method extraction -> deterministic flow router OR generated endpoint method call -> spec-aware command repair -> command executor -> Tripletex API.
- The LLM no longer needs to emit raw HTTP paths. It can select generated endpoint methods derived from `docs/openapi.json`.
- The generated endpoint method catalog currently exposes the full OpenAPI surface as method names plus required and optional arguments. The current `docs/openapi.json` contains `800` concrete `GET`/`POST`/`PUT`/`DELETE` operations, and each one has a deterministic wrapper.
- Planned commands are validated against the saved `docs/openapi.json` spec before execution.
- Known example-doc deltas such as `name -> customerName`, missing ledger prefixes, and required date windows are repaired against the OpenAPI contract before execution.
- Common customer, product, employee, department, project, sales, invoice-payment, and ledger-dimension tasks now have deterministic code flows and do not fall back to LLM-generated API actions once mapped to a supported internal method.
- For workflows that span multiple Tripletex domains, the planner now scopes method hints across related resources such as `timesheet`, `activity`, `project`, `customer`, `order`, `invoice`, payment, travel, and ledger APIs instead of only a single target resource.
- Attachments are saved to a temporary request directory, summarized for the planner, and PDFs are text-extracted when possible.
- PDF and image attachments can also be passed to Gemini through Vertex AI multimodal input.
- This is still a baseline scaffold, not a completed competition solver.

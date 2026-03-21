# Tripletex

This directory contains the Tripletex competition solver.

The current architecture is method-centric:

- every `/solve` request is normalized into a concrete workflow method
- curated deterministic routers own the high-value multi-step business workflows
- OpenAPI-derived wrapper methods cover the remaining resource families without falling back to `UnknownMethod`
- the LLM is used for task analysis first; per-step LLM execution fallback is disabled by default so coded workflows own execution

What the docs require:

- Public HTTPS endpoint.
- `POST /solve` with JSON body containing `prompt`, optional `files`, and `tripletex_credentials`.
- `POST /` is also accepted as a compatibility alias for the same request contract.
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
- `app/planner.py`: Vertex AI / Gemini task analysis, with optional step-planning fallback for unsupported workflows.
- `app/execution.py`: command-style Tripletex executor with OpenAPI validation.
- `app/solver.py`: request validation, attachment persistence, planning, execution, and API key protection.
- `Dockerfile`: Cloud Run deployment image.
- `.env.example`: local configuration template.

Current method catalog:

- `20` curated workflow methods in `app/internal_tasks.py`
- `57` named OpenAPI workflow-wrapper methods generated from the saved Tripletex OpenAPI surface
- no live runtime `UnknownMethod` path in `app/`

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
- `LOG_LEVEL`: defaults to `DEBUG`.
- `CLOUD_RUN_SERVICE_NAME`: defaults to `tripletex-agent`.
- `CLOUD_RUN_REGION`: defaults to `europe-north1`.
- `TRIPLETEX_API_KEY`: optional shared secret checked against `Authorization: Bearer ...`.
- `TRIPLETEX_MAX_PLANNER_STEPS`: defaults to `12`.
- `TRIPLETEX_MAX_API_CALLS`: defaults to `12`.
- `TRIPLETEX_MAX_STEPS`: legacy compatibility fallback for both budgets.
- `TRIPLETEX_REQUEST_TIMEOUT`: defaults to `30`.
- `TRIPLETEX_ALLOW_NOOP`: set to `true` only for wiring tests if Vertex AI is not configured.
- `TRIPLETEX_ENABLE_LLM_STEP_PLANNING`: defaults to `false`. Leave this off in production if you want the LLM to classify the request once and let deterministic code own execution.

Cloud Run deploy:

```bash
./deploy_cloud_run.sh
```

Notes:

- The default execution path is: normalized task analysis -> concrete workflow method -> deterministic workflow router -> spec-aware command repair -> validated execution -> Tripletex API.
- By default the LLM does not do per-step recovery. If a workflow is not coded, the solver now fails explicitly instead of spending extra LLM calls trying to improvise execution.
- If you explicitly enable `TRIPLETEX_ENABLE_LLM_STEP_PLANNING=true`, the legacy planner-driven step fallback is still available for experimentation.
- The generated endpoint method catalog currently exposes the full OpenAPI surface as method names plus required and optional arguments. The current `docs/openapi.json` contains `800` concrete `GET`/`POST`/`PUT`/`DELETE` operations, and each one has a deterministic wrapper.
- Planned commands are validated against the saved `docs/openapi.json` spec before execution.
- Known example-doc deltas such as `name -> customerName`, missing ledger prefixes, and required date windows are repaired against the OpenAPI contract before execution.
- Curated workflows now cover customer, product, employee upsert, employee onboarding, department, project, project lifecycle, sales, project time invoicing, supplier invoices, invoice payments, invoice payment reversals, invoice credit notes, employee entitlements, and ledger dimensions.
- Curated workflows now also include deterministic supplier upsert rather than routing supplier creation through customer semantics or generic OpenAPI execution.
- Attachments are saved to a temporary request directory, summarized for the planner, and PDFs are text-extracted when possible.
- PDF and image attachments can also be passed to Gemini through Vertex AI multimodal input.
- `DELTAS.md`, `NEWANALYSIS.md`, and `DELTATASKS.md` are the current architectural audit, gap analysis, and execution ledger.

Observability and production debugging:

- Every HTTP request gets a request-scoped `request_id`, returned as `x-request-id` and included in every log line.
- `/solve` logs now capture the full execution chain: request summary, normalized task analysis, chosen workflow method, deterministic router step results, command repair before/after, Tripletex API call summaries, and final finish or exhaustion state.
- Router logs now show which workflow route owned each step, the trimmed workflow payload or search state, the recent history tail, and the exact decision returned from that route.
- Planner step logs are only relevant when `TRIPLETEX_ENABLE_LLM_STEP_PLANNING=true`.
- Tripletex client logs now include the upstream base host, timeout, response request id when present, value or values counts for list endpoints, and validation-message summaries for 4xx responses.
- Validation and repeated-failure handling are logged with enough context to distinguish solver bugs from sandbox precondition issues.
- Credentials are still redacted: session tokens are never logged, and base URLs are reduced to scheme plus host.
- `DEBUG` is now the default log level for both local runs and Cloud Run deploys unless you explicitly override it, but noisy dependency HTTP trace logs are held at `INFO`.

Useful log events to search for in Cloud Run:

- `http.request.start` and `http.request.end`
- `solve.analysis.complete`
- `workflow.step.start` and `workflow.step.result`
- `planner.step.start` and `planner.step.method`
- `solve.command.repaired`
- `tripletex.request.error`
- `solve.command.api_failed`
- `solve.finish.precondition_failed`
- `solve.finish.unsuccessful`
- `solve.exhausted`

Verification:

```bash
python3 -m py_compile app/*.py
/tmp/tripletex-venv/bin/python -m unittest discover -s tests -p 'test_*.py'
rg -n "UnknownMethod|FlowKind\\.UNKNOWN" app tests
```

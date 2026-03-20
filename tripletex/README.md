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
- `app/planner.py`: Vertex AI / Gemini planner loop that emits one API action at a time.
- `app/solver.py`: request validation, attachment persistence, planner execution, and API key protection.
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
- `GEMINI_MODEL`: defaults to `gemini-2.0-flash`.
- `TRIPLETEX_API_KEY`: optional shared secret checked against `Authorization: Bearer ...`.
- `TRIPLETEX_MAX_STEPS`: defaults to `8`.
- `TRIPLETEX_REQUEST_TIMEOUT`: defaults to `30`.
- `TRIPLETEX_ALLOW_NOOP`: set to `true` only for wiring tests if Vertex AI is not configured.

Cloud Run deploy:

```bash
gcloud run deploy tripletex-agent \
  --source . \
  --region europe-north1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 300
```

Notes:

- The planner scaffold is a starting point, not a finished competition agent. It gives you a working tool loop and request contract.
- Attachments are saved to a temporary request directory and exposed to the planner as file metadata and local paths.
- Some Tripletex tasks involve PDFs or images. This scaffold does not yet do OCR or PDF extraction.

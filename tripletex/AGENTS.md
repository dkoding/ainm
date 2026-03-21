# Repository Guidelines

## Project Structure & Module Organization

The runtime scaffold lives in [`app/`](./app): [`app/main.py`](./app/main.py) exposes `GET /`, `GET /health`, and `POST /solve`; [`app/__init__.py`](./app/__init__.py) is minimal package glue. Deployment files are [`Dockerfile`](./Dockerfile), [`deploy_cloud_run.sh`](./deploy_cloud_run.sh), [`requirements.txt`](./requirements.txt), and local env templates in `.env` / `.env.example`.

This repo is documentation-driven. Core design files are [`RULES.md`](./RULES.md), [`DESC.md`](./DESC.md), [`LLM.md`](./LLM.md), [`EXAMPLE.md`](./EXAMPLE.md), [`ANALYSIS.md`](./ANALYSIS.md), [`API.md`](./API.md), [`PLAN1.md`](./PLAN1.md), [`TASKS1.md`](./TASKS1.md), [`PLAN2.md`](./PLAN2.md), and [`TASKS2.md`](./TASKS2.md). Raw Tripletex source material is under [`docs/`](./docs), especially [`docs/openapi.json`](./docs/openapi.json).

## Required Reading Before Planning

Before creating or editing any `PLAN*.md` or `TASKS*.md`, read these in order:

1. [`RULES.md`](./RULES.md)
2. [`DESC.md`](./DESC.md)
3. [`LLM.md`](./LLM.md)
4. [`EXAMPLE.md`](./EXAMPLE.md)
5. [`ANALYSIS.md`](./ANALYSIS.md) and [`API.md`](./API.md)
6. Existing plan/task docs: [`PLAN1.md`](./PLAN1.md), [`TASKS1.md`](./TASKS1.md), [`PLAN2.md`](./PLAN2.md), [`TASKS2.md`](./TASKS2.md)
7. Relevant source docs in [`docs/`](./docs), especially [`docs/openapi.json`](./docs/openapi.json)

`RULES.md` is mandatory. If a plan or task list conflicts with it, fix the plan/task list.

## Build, Test, and Development Commands

- `pip install -r requirements.txt`: install the FastAPI scaffold dependencies.
- `uvicorn app.main:app --reload --host 0.0.0.0 --port 8080`: run locally.
- `python3 -m compileall app`: quick Python syntax smoke test.
- `bash -n deploy_cloud_run.sh`: validate the deploy script without deploying.
- `docker build -t tripletex-scaffold .`: build the Cloud Run image locally.
- `./deploy_cloud_run.sh`: deploy to Cloud Run using `.env` / environment variables.

## Coding Style & Naming Conventions

Use Python 3.11 style, 4-space indentation, and type hints on public functions. Prefer small, explicit modules over framework-heavy abstractions. Keep FastAPI edge code thin and move logic into dedicated packages as the system grows. Use `snake_case` for functions, variables, and module names; keep raw Tripletex `operationId` names exact when generated.

## Testing Guidelines

There is no full test suite yet. Until one exists, every change should include at least:

- `python3 -m compileall app`
- `bash -n deploy_cloud_run.sh`

When tests are added, place them under `tests/` and name files `test_*.py`. Prioritize router, wrapper, LLM-contract, and OpenAPI coverage tests.

## Commit & Pull Request Guidelines

Recent history uses short subjects such as `Nuking Tripletex and starting again` and `TRIPLETEX WIP`. Keep commits short, imperative, and scoped; avoid vague `WIP` on shared branches when a specific subject is possible.

PRs should include:

- purpose and scope
- affected docs/spec files
- validation commands run
- deployment or env-var impact

## Security & Planning Notes

Never hardcode Tripletex credentials or bypass the provided proxy. This repository is docs-first: update the relevant `.md` files when architecture or execution behavior changes.

Maintain [`COMPLETEDTASKS.md`](./COMPLETEDTASKS.md) as a rolling work log. Update it whenever a meaningful task or milestone finishes so interrupted work can resume cleanly.

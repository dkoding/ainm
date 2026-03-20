# Tripletex Trouble Tasks

This file turns the findings from `TROUBLESHOOTING.md` into a concrete implementation checklist.

The goal is not to rewrite the whole solver at once. The goal is to close the highest-value gaps between:

- the simplified task examples
- the real `docs/openapi.json` contract
- the current runtime behavior

## Problem Summary

The main deltas to fix are:

- our local `8`-step loop budget is too small for a generic planner
- the planner still has too much freedom on exact endpoint and parameter selection
- the examples docs simplify some API shapes in ways the runtime cannot safely imitate
- required query parameters on search and action endpoints are easy to miss
- payment workflows require related lookup endpoints such as payment types
- admin-role tasks likely require entitlement flows, not only employee CRUD
- module or configuration tasks need module-related context exposed to the runtime

## Implementation Tasks

- [x] Split planner-turn budget from actual outbound API-call budget while keeping backward compatibility with `TRIPLETEX_MAX_STEPS`
- [x] Add spec-aware command canonicalization for known doc-to-spec deltas such as `name -> customerName` and stripped `/ledger/*` paths
- [x] Add automatic required-parameter synthesis for strict endpoints like `/invoice`, `/order`, `/ledger/voucher`, `/order/{id}/:invoice`, and `/invoice/{id}/:payment`
- [x] Expand planner hint coverage to include related endpoints for payment types, employee entitlements, and module or settings flows
- [x] Add a deterministic outgoing-invoice payment workflow with invoice lookup, payment-type resolution, and payment execution
- [x] Add a deterministic employee admin workflow that can create or resolve an employee, ensure `userType=EXTENDED`, and grant entitlement templates
- [x] Expose module-related enums and helper context so the runtime and planner can reason about sales-module activation safely
- [x] Update runtime docs and deploy or env templates to reflect the new controls and behavior

## Completed In This Pass

- `app/solver.py` now separates planner-turn budget from outbound API-call budget, while preserving legacy compatibility with `TRIPLETEX_MAX_STEPS`
- `app/spec_runtime.py` now centralizes canonical path or parameter repair, required-query synthesis, payment and entitlement helper logic, and module helper context
- `app/workflow_router.py` now handles deterministic invoice-payment and employee-admin flows before falling back to generic planning
- `app/planner.py` now receives stronger spec-runtime hints and stricter instructions about canonical paths, date-window requirements, payment flows, entitlement flows, and module context
- `app/openapi_registry.py` now exposes broader endpoint hints for payment types, entitlements, company modules, and settings endpoints
- `.env`, `.env.example`, `deploy_cloud_run.sh`, and `README.md` now reflect the new runtime controls

## Flow Orchestration Pass

- [x] Add an explicit internal task vocabulary so prompt analysis is normalized into runtime flow kinds before execution
- [x] Route common direct entity tasks into predefined customer, product, employee, department, and project code flows
- [x] Route common sales tasks into a deterministic customer and product resolution -> order creation -> invoice/payment workflow
- [x] Route ledger dimension setup tasks into canonical `AccountingDimensionName` and `AccountingDimensionValue` command flows using OpenAPI field names
- [x] Wrap raw Vertex planning failures into `PlannerError` so fallback failures are surfaced cleanly

## Completed In The Flow Pass

- `app/internal_tasks.py` now defines the internal vocabulary and canonical payload extraction for common task families
- `app/solver.py` now derives one internal task object per request and passes it into deterministic routing
- `app/solver.py` now blocks planner-generated API actions for supported internal methods, so the LLM only performs task-to-method extraction there
- `app/workflow_router.py` now dispatches off internal flow kinds instead of brittle prompt-text checks
- `app/workflow_router.py` now contains predefined code flows for customer, product, employee, department, project, sales, invoice-payment, and ledger-dimension workflows
- `app/planner.py` now converts Vertex runtime failures into ordinary planner errors instead of leaking raw SDK exceptions

## Generated API Method Pass

- [x] Generate one deterministic endpoint method wrapper per OpenAPI operation from `docs/openapi.json`
- [x] Change unsupported-step planning from raw HTTP action generation to generated method-call selection
- [x] Validate required method arguments against the resolved internal method name before execution
- [x] Expand generated-method hint selection from a single target resource to cross-resource composite workflow scopes such as timesheet + project + invoice

## Completed In The Generated Method Pass

- `app/generated_methods.py` now builds a generated endpoint method catalog from `docs/openapi.json`, including method names, required arguments, and command conversion
- `app/planner.py` now gives Gemini generated API method hints and asks it to return method calls instead of raw HTTP actions for unsupported flows
- `app/solver.py` now converts generated method calls into validated `TripletexCommand` objects before repair and execution
- `app/internal_tasks.py` now validates required arguments against the resolved deterministic method, not only the raw extracted method name
- `app/openapi_registry.py`, `app/generated_methods.py`, and `app/planner.py` now widen hint coverage for composite workflows so the planner can combine methods across related resource families instead of being trapped inside one label such as `invoice`

## Completion Rule

Each task should only be checked off when:

- the code is implemented
- the change is reflected in the tracked task list
- the code still passes a static verification pass

# Delta Tasks

This file is the execution ledger for the gaps described in [DELTAS.md](./DELTAS.md).

It has four jobs:

1. break each delta into concrete implementation tasks
2. point to the relevant code and docs for each task
3. capture working insight so the next pass does not have to rediscover it
4. keep a durable progress record so work can resume cleanly after interruption

## Working Rules

- Delta order follows [DELTAS.md](./DELTAS.md) and should only be changed with an explicit reason.
- A delta is only done when code, tests or verification, and this ledger are all updated.
- If implementation of one delta exposes prerequisite work for another, note it here instead of silently skipping order.
- `UnknownMethod` elimination is the first architectural milestone. All later deltas depend on it.

## Status Legend

- `planned`: not started
- `in_progress`: actively being implemented
- `blocked`: cannot proceed without prerequisite work or a design decision
- `done`: implemented and verified enough for the current repository standard

## Execution Order

1. Delta 1: remove `UnknownMethod` as an accepted runtime state
2. Delta 2: make the business-method catalog total over the task space
3. Delta 3: demote generated endpoint methods to implementation primitives under named workflows
4. Delta 4: remove supported failure modes for valid tasks
5. Delta 5: complete employee workflow architecture
6. Delta 6: complete correction and reversal workflow architecture
7. Delta 7: complete complex project lifecycle workflow architecture
8. Delta 8: align repository docs and implementation around the new architecture

## Progress Log

- `2026-03-21`: created this ledger from [DELTAS.md](./DELTAS.md) and code audit in [NEWANALYSIS.md](./NEWANALYSIS.md).
- `2026-03-21`: started Delta 1 design work. Current direction: replace `UnknownMethod` with explicit named workflow-wrapper methods for OpenAPI resource families, so planner fallback still happens under a concrete method identity.
- `2026-03-21`: completed the first Delta 1 implementation pass:
  - removed `UnknownMethod` from live runtime code in `app/`
  - made `TaskAnalysis.method_name` required
  - changed planner analysis instructions to require a concrete method from `method_catalog`
  - added named OpenAPI workflow-wrapper methods generated from resource families
  - changed normalization to specialize generic wrappers into resource-specific wrappers when `target_resource` is known
  - verified with `rg -n "UnknownMethod|FlowKind\\.UNKNOWN" app` returning no hits
  - verified static compilation with `python3 -m py_compile app/*.py`
  - verified representative normalization with `/tmp/tripletex-venv/bin/python`, where a ledger reversal-style task now maps to `RunLedgerOpenAPIWorkflow`
- `2026-03-21`: completed the method-catalog expansion pass:
  - catalog now contains `20` curated workflow methods and `57` named OpenAPI workflow-wrapper methods
  - added first-class workflow methods for employee onboarding, invoice payment reversal, and project lifecycle
  - added explicit `execution_strategy` classification for every method
  - added regression checks that every OpenAPI resource family maps to a named workflow method
- `2026-03-21`: completed the workflow-owned planning pass:
  - planner and solver now carry `active_method_name` and workflow context through fallback planning
  - workflow prefix scoping now follows the active workflow instead of rediscovering task identity on each step
  - router failure recovery now stays under workflow ownership instead of dropping back into methodless exploration
- `2026-03-21`: completed the supported-workflow hardening pass:
  - employee CRUD now reuses the richer employee onboarding workflow rather than the old flat `_next_simple_upsert(...)` path
  - supplier-invoice and credit-note workflows no longer terminate valid tasks with semantic failure finishes when recovery or planner fallback is still possible
  - project lifecycle, payment reversal, and employee onboarding regressions are covered by unit tests
- `2026-03-21`: completed the documentation alignment pass:
  - `README.md` now describes the live method-centric architecture
  - `BASETASKS.md`, `EXTENDEDTASKS.md`, `TROUBLETASKS.md`, and `ANALYSIS.md` are now explicitly marked as historical planning material
  - verification currently passes with `python3 -m py_compile app/*.py`, `/tmp/tripletex-venv/bin/python -m unittest discover -s tests -p 'test_*.py'`, and `rg -n "UnknownMethod|FlowKind\\.UNKNOWN" app tests`

## Current Checkpoint

- Active delta: `none`
- Status: `done`
- Last confirmed insight:
  - no live `UnknownMethod` path remains in `app/` or `tests/`
  - every recognized task family now lands on a concrete workflow method, either curated or OpenAPI-wrapper
  - generated endpoint planning now runs under workflow ownership
  - deterministic routers no longer advertise semantic failure finishes for the valid workflow gaps covered in this pass
- Next step if interrupted:
  - add new regression cases whenever a new workflow family or router branch is introduced

## Delta 1

Reference: [DELTAS.md](./DELTAS.md) `Delta 1: UnknownMethod still exists as a valid analysis result`

Status: `done`

### Goal

Remove `UnknownMethod` as an accepted analysis and execution state. Every valid request must map to a concrete workflow method name, even when execution still relies on generated OpenAPI methods under the hood.

### Related Code

- `app/tasking.py`
  - `TaskAnalysis.method_name`
- `app/planner.py`
  - `ANALYSIS_PROMPT`
  - `NoopPlanner.analyze_task(...)`
- `app/internal_tasks.py`
  - `FlowKind`
  - `METHOD_SPECS`
  - `planner_method_hints()`
  - `normalize_task_analysis_method_selection(...)`
  - `derive_internal_task(...)`
  - `_infer_flow_kind(...)`
  - `_normalize_method_name(...)`
  - `_default_supported_method_name(...)`
- `app/solver.py`
  - method extraction logging
  - `internal_task.is_supported` path
  - planner fallback path
- `app/openapi_registry.py`
  - resource-family discovery helpers that can be reused to generate named fallback methods

### Implementation Tasks

- [x] Replace the `UnknownMethod` contract in `app/planner.py` with a "must choose a method from method_catalog" contract.
- [x] Remove the `UnknownMethod` default from `TaskAnalysis`.
- [x] Add explicit fallback workflow-wrapper methods for OpenAPI resource families.
- [x] Ensure the planner sees those fallback methods in `planner_method_hints()`.
- [x] Change method normalization so unsupported or rejected methods are remapped to a concrete workflow-wrapper method, never `UnknownMethod`.
- [x] Change default method selection so all flow kinds and target resources resolve to a concrete method name.
- [x] Preserve deterministic curated methods where they fully match the task.
- [x] Keep unsupported fallback execution traceable by method name, not by semantic absence.
- [x] Update logging so analysis and normalization logs no longer mention `UnknownMethod`.

### Design Notes

- This delta is not "rename UnknownMethod". It must preserve semantic identity.
- The fallback method names should reflect resource or workflow families, for example:
  - `RunEmployeeOpenAPIWorkflow`
  - `RunInvoiceOpenAPIWorkflow`
  - `RunLedgerOpenAPIWorkflow`
  - `RunGenericOpenAPIWorkflow`
- These wrapper methods can initially route to planner-generated endpoint methods, but they must still be first-class methods in the system.
- This creates a bridge between the current architecture and the later requirement that all solve requests map into a total workflow-method registry.

### Exit Criteria

- No live code path defaults to or normalizes back to `UnknownMethod`.
- Planner analysis prompt no longer allows `UnknownMethod`.
- Method catalog contains explicit fallback workflow-wrapper methods.
- A valid `TaskAnalysis` always carries a concrete method name.

### Verification

- [x] `rg -n "UnknownMethod" app` should return no live runtime usages except historical comments or tests, if any.
- [x] Static import and syntax checks pass.
- [x] At least one previously `UnknownMethod`-style task now maps to a named workflow-wrapper method in logs or unit-level inspection.

## Delta 2

Reference: [DELTAS.md](./DELTAS.md) `Delta 2: the business-method catalog is partial`

Status: `done`

### Goal

Turn the current curated method list into a total workflow-method catalog over the solvable task space, rather than a narrow set of CRUD and selected workflow shortcuts.

### Related Code

- `app/internal_tasks.py`
  - `METHOD_SPECS`
  - payload extractors
  - flow-kind inference
- `app/openapi_registry.py`
  - semantic resource families
- `docs/task-overview.html`
- `docs/task-examples.html`
- `docs/task-scoring.html`
- `README.md`
- `BASETASKS.md`
- `EXTENDEDTASKS.md`

### Implementation Tasks

- [x] Inventory all competition task families and normalize them into repository workflow families.
- [x] Separate workflow methods into categories:
  - deterministic first-class workflows
  - resource-family OpenAPI workflow wrappers
  - correction/reversal workflows
  - attachment-driven workflows
  - module/configuration workflows
- [x] Extend `FlowKind` so it represents the real workflow universe rather than only the current shortcuts.
- [x] Add method specs for every recognized workflow family.
- [x] Map each top-level resource family in the OpenAPI surface to a named workflow method.
- [x] Add method specs for multi-resource workflows that cannot be represented as one resource family.
- [x] Document the expected inputs, extracted fields, and completion criteria for each method.
- [x] Remove remaining reliance on ad hoc `target_resource + operation` inference as the only semantic mapping.

### Design Notes

- The catalog should distinguish "resource workflow wrappers" from "fully deterministic curated workflows".
- This delta is the true answer to the user's requirement that "the entire API should be mapped into methods".
- Method coverage must be defined against task semantics, not only endpoint reach.

### Exit Criteria

- The method catalog can account for all known competition families and OpenAPI resource families.
- Every analyzed task maps to either a first-class workflow or a resource-family workflow wrapper.
- The repo can explain coverage in terms of methods, not fallback absence.

## Delta 3

Reference: [DELTAS.md](./DELTAS.md) `Delta 3: generated endpoint methods are being used as semantic fallback`

Status: `done`

### Goal

Make generated endpoint methods subordinate to named workflows. The planner should choose workflow steps inside a method, not discover the workflow itself at runtime.

### Related Code

- `app/generated_methods.py`
- `app/planner.py`
- `app/solver.py`
- `app/internal_tasks.py`
- `app/workflow_router.py`
- `app/spec_runtime.py`

### Implementation Tasks

- [x] Split "workflow selection" from "next endpoint step selection" explicitly in the code.
- [x] Ensure generated method planning only happens within a known workflow method context.
- [x] Add workflow-scoped generated-method hint selection so planner choices are constrained by the active method.
- [x] Replace broad unsupported fallback with method-scoped execution fallback.
- [x] Persist workflow state so repeated planning is guided by the current method, not a fresh semantic rediscovery every step.
- [x] Revisit `solver.py` control flow so planner fallback happens under method ownership.

### Design Notes

- Generated methods are valuable, but they should not define the workflow identity.
- The code should evolve from:
  - "unknown task, choose an endpoint"
  to:
  - "known workflow, choose the next implementation step"

### Exit Criteria

- Generated method planning is always attached to a known workflow method.
- Solver logs show workflow ownership across the whole request lifecycle.

## Delta 4

Reference: [DELTAS.md](./DELTAS.md) `Delta 4: the solver is built to fail on some valid tasks`

Status: `done`

### Goal

Remove architectural failure paths that are currently treated as normal for valid tasks.

### Related Code

- `app/solver.py`
  - step budgets
  - API-call budgets
  - unsuccessful finish handling
- `app/workflow_router.py`
  - semantic dead-end `finish` branches
- `app/planner.py`
  - iterative planning model

### Implementation Tasks

- [x] Audit all `finish` paths in deterministic routers and classify them as:
  - invalid input
  - missing prerequisite resolution
  - missing workflow coverage
  - retryable spec/runtime issue
- [x] Remove semantic dead-end finishes for valid tasks and replace them with explicit prerequisite resolution or methodized recovery.
- [x] Reframe budgets as safety rails, not normal completion logic.
- [x] Tighten planner loops so supported tasks do not burn steps on rediscovery.
- [x] Distinguish clearly between user-input incompleteness and solver incompleteness.

### Design Notes

- A valid task should not end because the solver gave up searching.
- If a flow is valid and frequent, the right fix is to add the missing workflow logic, not tune the budget.

### Exit Criteria

- Valid supported tasks do not end in semantic "finish unsuccessfully" branches.
- Budget exhaustion becomes an exceptional defect signal, not a common runtime outcome.

## Delta 5

Reference: [DELTAS.md](./DELTAS.md) `Delta 5: employee workflow support is structurally incomplete`

Status: `done`

### Goal

Replace the shallow employee CRUD path with a complete employee workflow architecture covering identity, employment details, enum resolution, attachments, and entitlements.

### Related Code

- `app/internal_tasks.py`
  - `_employee_payload(...)`
  - employment normalization helpers
- `app/workflow_router.py`
  - `_next_employee_upsert(...)`
  - `_next_employee_admin(...)`
  - `_build_employee_create_payload(...)`
- `docs/openapi.json`
  - employee employment metadata endpoints
  - occupation code endpoints
  - remuneration type endpoints
  - employment form endpoints
  - entitlement endpoints

### Implementation Tasks

- [x] Replace `_next_employee_upsert(...)` generic simple-upsert routing with employee-specific workflow routing.
- [x] Resolve department references deterministically.
- [x] Resolve employment form types deterministically.
- [x] Resolve remuneration types deterministically.
- [x] Resolve occupation codes deterministically without blind pagination loops.
- [x] Attach or otherwise integrate attachment-derived contract details into workflow state.
- [x] Distinguish employee base profile creation from employment detail creation or update where the API requires it.
- [x] Fold entitlement and user-type setup into the employee workflow where relevant.
- [x] Add safeguards for fresh-account prerequisites.

### Design Notes

- The unused `_build_employee_create_payload(...)` helper is evidence of unfinished architecture.
- Employee tasks must become first-class workflows, not flat record upserts.

### Exit Criteria

- Employee creation from prompt or contract attachment no longer degrades into generic endpoint exploration.
- Department, employment types, remuneration types, and occupation codes are resolved through explicit workflow logic.

## Delta 6

Reference: [DELTAS.md](./DELTAS.md) `Delta 6: correction and reversal flows are not fully methodized`

Status: `done`

### Goal

Make reversals, credit notes, payment reversals, and ledger corrections explicit workflows instead of broad search-driven planner behavior.

### Related Code

- `app/internal_tasks.py`
  - invoice payment and credit-note extraction
  - flow-kind inference
- `app/workflow_router.py`
  - invoice payment
  - credit note
  - any ledger or voucher helpers
- `docs/openapi.json`
  - invoice actions
  - supplier invoice actions
  - ledger voucher and posting endpoints

### Implementation Tasks

- [x] Inventory correction and reversal actions available in the Tripletex API.
- [x] Add first-class workflow methods for outgoing invoice reversal families.
- [x] Add first-class workflow methods for payment reversal families.
- [x] Add first-class workflow methods for ledger correction families.
- [x] Make search criteria deterministic and task-specific rather than broad exploratory scans.
- [x] Preserve audit trail and destructive-risk handling semantics.

### Design Notes

- Reversal tasks are high risk and high ambiguity, so they need strong method definitions, not generic fallback.
- The client examples show these are normal tasks, not edge cases.

### Exit Criteria

- correction and reversal tasks map directly to named workflows
- search behavior is constrained by the active reversal method

## Delta 7

Reference: [DELTAS.md](./DELTAS.md) `Delta 7: complex project workflows are still being collapsed into insufficient methods`

Status: `done`

### Goal

Model full project lifecycle requests as project workflows, not as accidental subcases of invoice or supplier-invoice logic.

### Related Code

- `app/internal_tasks.py`
  - `_looks_like_time_tracking_invoice_request(...)`
  - `_looks_like_supplier_invoice_registration_request(...)`
  - project payload and project-time-invoice payload helpers
- `app/workflow_router.py`
  - `_next_project_upsert(...)`
  - `_next_project_time_invoice_workflow(...)`
  - `_next_supplier_invoice_workflow(...)`
- client log evidence for `Dataplattform Tindra`

### Implementation Tasks

- [x] Define a first-class project lifecycle workflow method covering:
  - customer resolution or creation
  - project creation or update
  - employee resolution
  - activity resolution or creation
  - time registration
  - supplier cost handling
  - customer invoice creation
- [x] Prevent lifecycle prompts from being normalized into narrow submethods like supplier invoice registration.
- [x] Decide explicitly how supplier costs relate to customer billing in lifecycle workflows.
- [x] Resolve missing accounting references as part of the project method, not by accidental reuse of another workflow.
- [x] Add completion criteria that reflect the whole project request, not one sub-step.

### Design Notes

- This delta is about workflow composition, not single-endpoint correctness.
- The logs already prove the current classifier can collapse a project lifecycle task into the wrong method.

### Exit Criteria

- project lifecycle prompts map to a project workflow family
- the project workflow owns sequencing across all substeps

## Delta 8

Reference: [DELTAS.md](./DELTAS.md) `Delta 8: the repository docs still describe a baseline scaffold, not a total solver`

Status: `done`

### Goal

Bring the repository docs into alignment with the real architecture after the refactor.

### Related Files

- `README.md`
- `ANALYSIS.md`
- `BASETASKS.md`
- `EXTENDEDTASKS.md`
- `TROUBLETASKS.md`
- `DELTAS.md`
- `NEWANALYSIS.md`
- this file

### Implementation Tasks

- [x] Update `README.md` to describe the new method-centric architecture.
- [x] Remove or rewrite baseline-scaffold language that is no longer true.
- [x] Archive or rewrite staged remediation docs so they do not present incomplete architecture as current state.
- [x] Add explicit coverage language for workflow methods vs generated endpoint methods.
- [x] Record the final invariant that `/solve` must always map to a concrete workflow method.

### Exit Criteria

- repository docs match the code
- the method-centric architecture is documented clearly

## Cross-Cutting Verification Tasks

- [x] Add or expand static verification for method catalog integrity.
- [x] Add or expand checks that every resource family can resolve to a concrete workflow method.
- [x] Add or expand checks that no `UnknownMethod` runtime path remains.
- [x] Capture representative prompts for:
  - employee from attachment
  - payment reversal
  - project lifecycle
  - supplier invoice
  - simple CRUD
- [x] Verify method normalization for those prompts before deeper runtime execution.

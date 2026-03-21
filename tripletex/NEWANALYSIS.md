# New Analysis

## Scope

This document is a code-level audit of the current Tripletex solver. It is based on the implementation in `app/`, the local competition docs in `docs/`, the project docs in the repository root, and the observed failure cases from the client logs.

The standard used here is stricter than "works on some examples":

- `UnknownMethod` is not acceptable.
- `/solve` must be a total function over the competition request space.
- OpenAPI endpoint coverage is necessary, but not sufficient.
- A request is only "supported" if the solver can deterministically complete it from the client payload and the provided Tripletex API surface.

## Executive Assessment

The current codebase is not a complete solver. It is a hybrid scaffold with three strong foundations:

- a correct transport and auth layer
- a broad OpenAPI-backed endpoint execution layer
- several useful deterministic workflow fragments

But those strengths are undermined by the central architectural choice to allow unresolved task semantics through `UnknownMethod`, then fall back to a bounded planner/exploration loop. That choice makes incomplete task-to-method mapping a first-class runtime behavior instead of a defect.

In practical terms:

- the code is good at turning a known method into validated API calls
- the code is not good enough at proving what the method is for every `/solve` request
- the code therefore compensates with planner iteration, repair, and heuristics
- that compensation is exactly why requests still end in `SolveError`, step-budget exhaustion, or "finish unsuccessfully"

This is the architectural fault line. The problem is not only "some bugs". The problem is that the current system is built to tolerate semantic incompleteness.

## Current Architecture

The runtime is organized into the following layers.

### 1. Transport and request boundary

`app/main.py` owns the HTTP boundary:

- validates the `/solve` request
- logs request metadata
- delegates to `TripletexSolver.solve(...)`
- maps internal exceptions to HTTP responses

This part is clean and serviceable.

### 2. Request modeling and attachment preparation

`app/models.py` models the client contract:

- `prompt`
- `files[]`
- `tripletex_credentials.base_url`
- `tripletex_credentials.session_token`

`app/solver.py` saves attachments, prepares them, and passes extracted content into planning.

This is a necessary foundation for competition tasks with PDFs and images.

### 3. Task analysis

`app/planner.py` performs LLM-driven task analysis and returns `TaskAnalysis`.

Important fact:

- the planner prompt explicitly permits `method_name = UnknownMethod`
- `app/tasking.py` defaults `TaskAnalysis.method_name` to `UnknownMethod`

So the code does not treat `UnknownMethod` as a bug. It treats it as a normal outcome of analysis.

### 4. Internal task normalization

`app/internal_tasks.py` tries to normalize `TaskAnalysis` into a curated internal method catalog and flow kind.

This layer contains:

- curated workflow method specs such as `CreateEmployee`, `RunSalesWorkflow`, `RegisterSupplierInvoice`, `RunProjectTimeInvoiceWorkflow`
- payload extraction helpers
- heuristic method normalization
- default mapping for a narrow set of CRUD-style flows

This is the closest thing the code has to a business-method registry.

### 5. Deterministic workflow routing

`app/workflow_router.py` routes supported internal tasks into hand-authored multi-step flows.

Examples:

- customer upsert
- product upsert
- department upsert
- project upsert
- sales workflow
- supplier invoice workflow
- invoice payment workflow
- credit note workflow
- project time invoice workflow
- employee admin workflow

This is the strongest part of the solver when it applies.

### 6. Generated endpoint method fallback

If the curated workflow path does not apply, the solver falls back to the generated OpenAPI method catalog:

- `app/openapi_registry.py` loads and validates the spec
- `app/generated_methods.py` creates deterministic wrappers for OpenAPI operations
- `app/planner.py` asks the LLM to choose one generated method at a time
- `app/spec_runtime.py` repairs paths, params, and bodies
- `app/execution.py` validates and executes the command

This gives the system broad API reach, but not full workflow semantics.

## What The Code Does Well

### Strong API contract handling

The service correctly models the client request shape, uses the provided `base_url`, and authenticates against Tripletex using the session token. That part is aligned with the docs and does not appear to be the source of the main failures.

### Good separation of concerns

The code distinguishes between:

- transport
- planning
- method/flow normalization
- routing
- spec validation
- execution

That separation is useful. It makes the defects diagnosable and gives the project a workable refactoring path.

### Broad endpoint coverage

The generated method system is a real strength. The codebase can reach a very large portion of `docs/openapi.json` through typed wrappers and command validation. This is far better than a raw-HTTP prompt hack.

### Spec-aware repair and validation

`app/spec_runtime.py` and `app/openapi_registry.py` provide real value:

- path canonicalization
- parameter alias repair
- required-query synthesis
- nested ID/reference repair
- validation before execution

These are useful hardening layers.

### Deterministic flows for some families

The workflow router is effective where it is complete. Project, sales, invoice-payment, and some ledger-related flows are clearly more robust than open-ended planner exploration.

### Useful observability

The logging is detailed enough to reconstruct real failure chains. That is one reason the architectural issues are visible rather than hidden.

## What The Code Does Poorly

### 1. `UnknownMethod` is a design state, not an exception

This is the most important finding.

The system explicitly allows analysis to say:

- "I do not know the workflow method"
- "fall back to endpoint-level exploration"

That is incompatible with the required invariant. If every `/solve` request must be solvable, then every valid request must map to a known method or composed workflow plan. A production solver cannot normalize uncertainty into `UnknownMethod` and still claim completeness.

### 2. The code has two method systems, and only one is total over the API

The code mixes two different ideas:

- business/workflow methods in `internal_tasks.py`
- generated endpoint methods in `generated_methods.py`

The second system covers operations. The first system covers task semantics.

Only the second system is broad. Only the first system is meaningful for `/solve`.

That is the core gap:

- endpoint coverage exists
- workflow-method coverage does not

The current solver uses the endpoint catalog as a semantic fallback. That is why it can search and poke at the API for many steps without actually having compiled the task into a complete method.

### 3. The solver is bounded to fail

`app/solver.py` enforces hard budgets:

- planner-step budget
- outbound API-call budget

It also accepts workflow-router branches that can return an unsuccessful `finish`.

That means the solver is built around the possibility of not solving the request. That may be a reasonable baseline scaffold. It is not acceptable under the user's stated standard.

### 4. Method normalization is heuristic and asymmetric

`app/internal_tasks.py` contains many useful heuristics, but it is still a heuristic layer:

- it infers flow kinds from text
- it tries to reject semantically insufficient shortcuts
- it provides default mappings only for a small set of CRUD cases
- it still returns `UnknownMethod` for many legitimate requests

This is not a total compiler from request semantics to workflow method.

### 5. Complex workflows are unevenly implemented

Some workflows have deep deterministic handling. Others are only shallowly represented.

The clearest example is employee creation:

- the codebase contains richer employee payload logic in `app/internal_tasks.py`
- `app/workflow_router.py` contains `_build_employee_create_payload(...)`
- but the live router path for employee upsert still delegates to `_next_simple_upsert(...)`
- that simple upsert only handles a flat employee record
- it does not own the full employment-resolution workflow the logs show is needed

That is not a small bug. It is evidence that part of the intended architecture is present in pieces but not wired into the actual execution path.

### 6. Unsuccessful completion is embedded inside deterministic flows

The supplier invoice router is a good example. It can terminate with reasons like:

- unable to determine ledger account
- unable to resolve VAT type
- unable to assemble valid payload

Those are not transport errors. They are semantic dead ends inside the workflow engine.

A complete solver should treat these as missing method coverage, missing extraction logic, or missing prerequisite-resolution logic, not as acceptable terminal outcomes.

### 7. Repair is compensating for semantic gaps

`app/spec_runtime.py` is doing too much semantic salvage:

- canonicalizing doc/spec mismatches
- synthesizing missing required parameters
- repairing references
- inferring payment and module details

These are useful, but they also show that the plan and method layers are not carrying enough structured intent. The runtime is patching after the fact.

### 8. There is no proof of totality over the competition task space

The competition docs describe:

- 30 tasks
- 56 variants per task
- 7 languages
- empty or near-empty fresh sandboxes
- attachments
- single-step and multi-step workflows
- correction, reversal, and bookkeeping tasks

Nothing in the current architecture proves total coverage over that space. The repository docs themselves still describe the system as a baseline scaffold and staged remediation effort.

## Structural Failure Patterns

The recent failures are consistent with the architecture.

### Pattern A: semantic collapse into the wrong curated method

Observed example:

- a full project lifecycle request was normalized into `RegisterSupplierInvoice`

That happens because the method catalog is partial and the classifier tries to force a rich task into an insufficient shortcut.

### Pattern B: fallback from unknown workflow to endpoint exploration

Observed example:

- employee creation from contract attachment became `UnknownMethod`
- then the system spent its budget paginating occupation-code endpoints

This is exactly what happens when the solver knows the API is large but does not know the workflow method.

### Pattern C: correction/reversal tasks degrade into search loops

Observed example:

- payment reversal searched customer, then ledger postings, then customer by name, with long planner latency and no deterministic finish

Again, the problem is not missing endpoints. The API has the endpoints. The problem is that the task was not compiled into a complete reversal workflow.

### Pattern D: deterministic routers still allow semantic dead ends

Observed example:

- supplier invoice flow aborted because it could not determine an account number

A complete system either extracts the needed field deterministically, derives it from task type, or uses a fully mapped task method that already encodes the right account semantics.

## Architectural Strengths

Despite the above, the codebase has real value.

### It is a strong platform, not a strong solver

This distinction matters.

The repository already contains the infrastructure needed for a complete solver:

- clean service boundary
- attachment handling
- OpenAPI loading and validation
- generated endpoint methods
- deterministic router framework
- runtime repair hooks
- useful logs

That means the project does not need to be thrown away. But it does need a change in design target.

### The right abstraction already exists in outline

The correct abstraction is not "planner picks another endpoint".

The correct abstraction is:

- every request belongs to a typed workflow family
- every family maps to a deterministic workflow method or a structured composition of deterministic submethods
- generated OpenAPI methods are implementation primitives under that workflow, not the primary fallback semantics

The code already hints at this architecture. It just does not enforce it consistently.

## Architectural Weaknesses Summarized

The current solver is weak in exactly the areas that matter most for the competition:

- semantic completeness
- total method coverage
- deterministic multi-step orchestration
- guaranteed completion from fresh accounts
- robust handling of corrections and reversals
- robust attachment-to-workflow compilation

The reason is not just missing cases. The reason is that the architecture still allows incomplete semantic understanding to reach runtime.

## Bottom Line

This codebase should be understood as:

- a well-instrumented baseline
- with strong OpenAPI reach
- with several good deterministic flow implementations
- but without a total task-to-method model

That is why `UnknownMethod` exists.
That is why the planner is allowed to explore.
That is why the solver can exhaust steps.
That is why the router can finish unsuccessfully.

If the requirement is:

- every `/solve` request is solvable
- every valid task maps to a known method
- `UnknownMethod` is forbidden

then the current architecture is not merely incomplete. It is misaligned with the required invariant.

The next phase should therefore not be framed as "more patches". It should be framed as:

- replace partial method recognition with total workflow-method mapping
- demote generated endpoint methods to workflow implementation primitives
- eliminate `UnknownMethod` as an accepted runtime analysis state
- remove bounded exploratory behavior as a normal path for supported tasks

Until that happens, the code will continue to solve some tasks well, many tasks partially, and some tasks not at all.

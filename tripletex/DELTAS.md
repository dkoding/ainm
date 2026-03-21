# Deltas

## Purpose

This document compares the current code against:

- the local competition docs in `docs/`
- the repository docs in `README.md` and `API.md`
- the actual client request shape
- the available Tripletex OpenAPI surface in `docs/openapi.json`
- the observed failure cases from the client logs

The comparison standard is strict:

- `UnknownMethod` is forbidden
- every valid `/solve` request must map to a solvable workflow method
- endpoint coverage alone does not count as solve coverage

## Baseline Requirements

From the local docs and the client contract, the solver must satisfy all of the following.

### Request contract

The client sends:

- `prompt`
- optional `files[]` with `filename`, `mime_type`, `content_base64`
- `tripletex_credentials.base_url`
- `tripletex_credentials.session_token`

The service must:

- use the provided `base_url`
- authenticate with the provided session token
- solve the task against the fresh sandbox account
- return `200 {"status":"completed"}` within the competition time limit

### Competition semantics

The docs describe:

- 30 task families
- 56 variants per task
- 7 languages
- fresh sandboxes
- attachments
- simple CRUD tasks
- multi-step workflows
- correction/reversal/bookkeeping tasks

This means the solver must not only know endpoints. It must know workflows.

### API semantics

`docs/openapi.json` exposes the low-level operations needed for the above. The current repository also already generates wrappers for the API surface. Therefore, lack of endpoint reach is not the main blocker. The blocker is task-to-method mapping.

## Comparison Summary

### What is aligned

- The HTTP request shape is modeled correctly.
- The service uses the provided Tripletex credentials.
- The code loads and validates against the OpenAPI spec.
- The generated method catalog provides broad endpoint reach.
- Some workflow families already have deterministic routing.

### What is only partially aligned

- Attachments are extracted, but not consistently compiled into deterministic workflows.
- Multi-step flows exist, but coverage is uneven and asymmetric.
- The runtime can repair many API mistakes, but that is compensating behavior, not proof of completeness.
- Fresh-account precondition creation exists in some flows, but not across the task universe.

### What is not aligned

- `UnknownMethod` is allowed.
- unsupported or partially supported tasks are expected to fall back to planner exploration
- the solver can terminate unsuccessfully
- the solver can exhaust planner or API-call budgets
- there is no total workflow-method mapping for `/solve`

## Concrete Deltas

### Delta 1: `UnknownMethod` still exists as a valid analysis result

Required state:

- every valid task maps to a known workflow method or typed workflow composition

Current state:

- `TaskAnalysis.method_name` defaults to `UnknownMethod`
- the planner prompt explicitly allows `UnknownMethod`
- `internal_tasks.py` can intentionally preserve or return `UnknownMethod`

Impact:

- semantic incompleteness is normalized into runtime behavior
- the solver is allowed to "not know the task method" and continue anyway

Why this is unacceptable:

- this is a direct violation of the required invariant

### Delta 2: the business-method catalog is partial

Required state:

- the entire taskable API/workflow surface must be mapped into methods

Current state:

- `internal_tasks.py` contains a curated method list, but it is clearly partial
- default mapping only covers a narrow set of CRUD families
- unsupported requests are pushed into generated endpoint-method fallback

Impact:

- the system has wide operation coverage but incomplete workflow coverage
- `/solve` is not total over the task space

### Delta 3: generated endpoint methods are being used as semantic fallback

Required state:

- generated OpenAPI methods should be low-level execution primitives inside complete workflows

Current state:

- when the workflow method is unknown or unsupported, the planner is asked to choose endpoint methods one step at a time

Impact:

- the system explores the API instead of executing a fully known task method
- this creates long search chains, retries, and failure-by-budget

### Delta 4: the solver is built to fail on some valid tasks

Required state:

- valid competition requests must complete, not merely be attempted

Current state:

- `solver.py` has hard planner-step and API-call budgets
- deterministic flows can return unsuccessful `finish`
- solver raises `SolveError` when budgets are exhausted or a router finishes unsuccessfully

Impact:

- failure is a supported runtime outcome, not a bug-class escape hatch

### Delta 5: employee workflow support is structurally incomplete

Required state:

- employee tasks with employment details, enums, department resolution, occupation-code resolution, and attachment-derived fields must map to a complete employee workflow

Current state:

- there is richer employee payload logic in `internal_tasks.py`
- there is an employee payload builder in `workflow_router.py`
- but the live employee route still delegates to the generic `_next_simple_upsert(...)`

Impact:

- employee creation behaves like flat CRUD in the router
- employment-specific prerequisites are discovered late and inconsistently
- this is exactly why the employee-from-contract case degraded into repeated occupation-code searches

### Delta 6: correction and reversal flows are not fully methodized

Required state:

- payment reversal, ledger correction, and similar tasks must have direct workflow mappings

Current state:

- correction tasks can degrade into broad search behavior over customer, invoice, and ledger endpoints

Impact:

- the solver spends latency budget discovering the workflow at runtime
- deterministic completion is not guaranteed

### Delta 7: complex project workflows are still being collapsed into insufficient methods

Required state:

- a request like full project lifecycle creation, time registration, supplier cost registration, and invoicing must map to a project workflow family, not to a single unrelated submethod

Current state:

- observed client request: full project lifecycle for `Dataplattform Tindra`
- observed analysis result: normalized into `RegisterSupplierInvoice`
- observed failure: flow terminated because account data for supplier-invoice workflow was missing

Impact:

- the solver is still semantically collapsing broad workflows into narrow shortcuts

### Delta 8: the repository docs still describe a baseline scaffold, not a total solver

Required state:

- repository design docs should describe a complete workflow-method architecture

Current state:

- `README.md`, `BASETASKS.md`, `EXTENDEDTASKS.md`, and `TROUBLETASKS.md` still describe staged remediation and baseline scaffolding

Impact:

- the implementation and the docs agree on the wrong thing: this is still an incremental baseline, not a completed competition solver

## Client Data vs Current Behavior

The client is already sending enough information for solvable workflows.

Observed examples include:

- full project lifecycle prompt with customer org number, supplier org number, budget, hours, and invoice request
- payment reversal prompt with customer org number, invoice description, and amount
- employee-creation prompt with attached contract PDF containing identity and employment details

These are not malformed inputs. They are normal competition-style tasks.

The failures therefore indicate:

- missing workflow-method coverage
- missing deterministic prerequisite resolution
- incorrect method normalization

They do not indicate a bad client contract.

## API Surface vs Current Behavior

The OpenAPI surface already contains the endpoints needed for these tasks, including:

- employee employment metadata
- occupation codes
- remuneration types
- employment form types
- supplier and incoming invoice flows
- order and invoice flows
- voucher and ledger flows
- payment and correction related endpoints

Therefore:

- the API is not the limiting factor
- the limiting factor is that the code has not mapped the API surface into a complete workflow-method system

## Non-Negotiable Conclusions

### 1. `UnknownMethod` must be removed as an accepted state

If it exists anywhere in live solve execution, the architecture is still incomplete.

### 2. The method layer must become total over the task space

Every valid `/solve` request must map to:

- one concrete workflow method, or
- a typed composition of concrete workflow methods

but never to semantic uncertainty.

### 3. Generated endpoint methods must be demoted

They are useful, but they must sit under workflow methods. They cannot remain the main fallback for normal task solving.

### 4. "finish unsuccessfully" is evidence of a missing method, not an acceptable result

If a deterministic flow can terminate with a semantic dead end for a valid request, that flow is incomplete.

### 5. Step-budget exhaustion is evidence of architectural mismatch

A complete solver should not need repeated exploratory planning to discover what method it is executing.

## Required Direction

The codebase needs a different contract with itself.

The new contract should be:

- no `UnknownMethod`
- no semantically unsupported valid tasks
- no planner-led endpoint exploration as a normal path
- no partial curated method catalog
- no acceptance of unsuccessful finish for valid competition inputs

The target design is:

- a total workflow-method registry over the competition task space
- deterministic prerequisite resolution inside those methods
- generated OpenAPI methods used as low-level execution steps
- attachment extraction feeding typed workflow inputs
- solver completion meaning actual task completion, not exhausted exploration

## Bottom Line

Current status:

- the transport layer is acceptable
- the OpenAPI execution layer is strong
- the workflow layer is incomplete
- `UnknownMethod` proves that incompleteness is currently designed in

Required status:

- the entire solvable request space must be mapped into methods
- `UnknownMethod` must not exist
- no valid `/solve` request should be unsolved

That is the real delta.

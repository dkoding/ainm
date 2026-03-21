# Tripletex Coverage Insight

## Verified State

The runtime boundary now matches the intended architecture:

- The LLM translates multilingual user requests and attachments into one structured `TaskAnalysis`.
- Code validates that contract.
- Code executes deterministic Tripletex API workflows from the structured contract only.

There is no active downstream prompt parsing or prompt-text workflow selection in the runtime path.

## Verified Coverage Snapshot

Local verification now reports:

- 84 total planner-selectable methods
- 27 coded deterministic workflows
- 57 deterministic Swagger-wrapper workflows
- 0 unsupported methods
- `documented_task_category_gaps = []`

The documented category coverage now includes:

- employees
- customers/products
- invoicing
- travel expenses
- projects
- corrections
- departments
- salary
- bank reconciliation

## What Changed

The latest production logs exposed two real deterministic gaps and one external precondition:

- Salary payroll was still falling through to `RunSalaryOpenAPIWorkflow` and failing with missing payroll-period arguments.
- Bank reconciliation was still falling through to `RunBankOpenAPIWorkflow` and exhausting generic wrapper routing.
- Supplier-invoice registration from PDF was structurally correct, but Tripletex rejected `POST /incomingInvoice` with `403 code=9000`, which is an account-permission constraint, not a missing workflow.

Those gaps are now closed in code by:

- adding `RunSalaryPayrollWorkflow`
- adding `RunBankReconciliationWorkflow`
- rejecting wrapper selections when the structured task clearly implies one of those curated workflows
- adding deterministic router coverage for salary-type resolution, salary transaction creation, outgoing invoice payment registration from bank entries, and supplier-invoice payment registration from bank entries

## Practical Boundary

This is the active handoff:

- LLM -> `TaskAnalysis`
- code -> contract validation
- code -> deterministic route execution
- Tripletex proxy -> API transport

The code still performs execution-time lookups, ID resolution, and payload assembly from structured fields. That is expected. It does not reinterpret raw natural language after the planner handoff.

## Remaining Risk Surface

The documented `/solve` competition scope is covered by deterministic routing and local regression tests, but runtime success can still be blocked by external Tripletex account constraints such as:

- missing module access
- missing feature entitlements
- proxy-token problems
- account-specific validation rules

Those are precondition failures, not workflow-selection failures.

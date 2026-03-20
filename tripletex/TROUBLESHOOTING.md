# Tripletex Troubleshooting Analysis

This document re-reads the local Tripletex markdown files, cross-checks them against the saved task docs and `docs/openapi.json`, and explains what may have been missed in the current implementation.

It focuses on:

- request and response handling
- API-call shape and workflow details
- doc-to-spec mismatches
- why the current solver is exhausting its step budget
- what should be changed next

## 1. Executive Summary

The main issue is not just "the model made a mistake."

The current solver is operating against a much stricter API surface than the simplified task examples suggest:

- some docs examples are illustrative, not canonical
- the OpenAPI spec contains required query parameters the planner must satisfy exactly
- some workflows depend on adjacent endpoints that are not currently emphasized in planner hints
- the current `8`-step limit is our own local execution guardrail, not a Tripletex requirement

That combination creates the failure mode seen so far:

1. the planner proposes a plausible but wrong endpoint or incomplete request
2. validation or the API rejects it
3. the loop consumes one more step
4. after a few search or repair iterations, the solver exhausts its local budget

## 2. What The Official Request Flow Actually Is

From the saved endpoint docs and the current app models, the submission flow is:

1. AINM sends `POST /solve`
2. The JSON body contains:
   - `prompt`
   - optional `files[]`
   - `tripletex_credentials.base_url`
   - `tripletex_credentials.session_token`
3. The agent must call the provided Tripletex proxy URL, not some hardcoded Tripletex base URL
4. Tripletex API authentication is Basic Auth:
   - username: `0`
   - password: `session_token`
5. The agent must return:
   - `{"status":"completed"}`
6. Total request timeout is `300 seconds`

Important implications:

- the request may include attachments
- prompts come in 7 languages
- every submission gets a fresh environment
- all API calls through the proxy are logged in the submissions view

## 3. What The Current App Does Correctly

The current implementation already respects several important constraints:

- it accepts the documented request shape in `app/models.py`
- it uses the incoming `base_url` and `session_token`
- it authenticates to Tripletex as `("0", session_token)` in `app/client.py`
- it validates planned commands against `docs/openapi.json`
- it logs inbound `/solve` requests and outbound Tripletex requests

So the current failures are not about using the wrong credentials model or the wrong external contract.

## 4. What The `8-Step Budget` Actually Is

The `8-step budget` is not from the competition docs.

It is our own internal loop cap:

- environment variable: `TRIPLETEX_MAX_STEPS`
- current default: `8`
- defined in `app/solver.py`

What it means in practice:

- the solver runs a planning loop
- each loop iteration asks the planner for the next decision
- the decision is either:
  - one API action
  - or `finish`
- every iteration consumes one step, even if:
  - the action is invalid
  - OpenAPI validation fails
  - Tripletex returns an API error

So `8 steps` is really:

- at most 8 planning turns
- at most 8 attempted action decisions before the solver gives up

It is not:

- an official AINM limit
- the HTTP timeout
- the total allowed number of API calls in the competition

Why this matters:

- a multi-step invoice flow can easily need search + create prerequisite + create order + invoice + payment + verify
- one or two invalid repair attempts can consume the whole budget
- complex tasks in the docs are explicitly described as multi-step

Conclusion:

- `8` is a local safety guardrail
- it is currently too tight for a generic step-by-step planner
- it may still be fine for deterministic family-specific handlers

## 5. Most Important Doc vs Spec Mismatches

These are the most important things that can mislead the planner.

### 5.1 Example search uses simplified parameter names

The saved examples page shows a customer search example using a `name` parameter.

But the OpenAPI spec for `GET /customer` exposes:

- `customerName`
- not `name`

That means:

- the examples page is useful for intent
- the OpenAPI spec must be treated as authoritative for exact request shaping

### 5.2 Example payment flow uses a non-canonical endpoint

The saved examples page includes a workflow like:

- `POST /customer -> POST /invoice -> POST /payment`

But the OpenAPI spec does not expose a generic `/payment` endpoint for this use case.

Instead it exposes payment actions such as:

- `PUT /invoice/{id}/:payment`
- `POST /supplierInvoice/{invoiceId}/:addPayment`
- `POST /incomingInvoice/{voucherId}/addPayment`

This matters because "register payment" is not one universal Tripletex action. The correct endpoint depends on what kind of invoice or voucher is involved.

### 5.3 Example invoice flow is only one of several valid flows

The examples page suggests:

- `GET /customer -> POST /order -> POST /invoice`

But the spec also exposes:

- `PUT /order/{id}/:invoice`

That action endpoint is likely the more native and efficient route when an order already exists.

### 5.4 The examples page is intentionally simplified

The examples page is useful for:

- common task families
- efficiency mindset
- error handling expectations

It is not sufficient for:

- exact query parameter names
- exact action endpoint paths
- exact payment flows
- exact module or entitlement configuration flows

## 6. Required Query Parameters The Planner Must Respect

These are especially important because a generic planner will often miss them unless they are encoded directly in logic or prompts.

### 6.1 Invoice search

`GET /invoice` requires:

- `invoiceDateFrom`
- `invoiceDateTo`

This means you cannot do a naive invoice lookup with only `invoiceNumber` or `customerId` unless you also supply a date range.

### 6.2 Order search

`GET /order` requires:

- `orderDateFrom`
- `orderDateTo`

This makes order lookup more constrained than a naive search planner may expect.

### 6.3 Ledger voucher search

`GET /ledger/voucher` requires:

- `dateFrom`
- `dateTo`

This is a major source of friction for voucher correction and reversal tasks.

### 6.4 Invoice payment action

`PUT /invoice/{id}/:payment` requires:

- `paymentDate`
- `paymentTypeId`
- `paidAmount`

So even after locating the invoice, payment registration may need:

1. invoice resolution
2. payment-type resolution
3. exact amount and date

### 6.5 Order-to-invoice action

`PUT /order/{id}/:invoice` requires:

- `invoiceDate`

This means invoice generation from an order still needs explicit date handling.

## 7. Related Endpoints The Current Planner May Be Underusing

One of the main findings is that task families are larger than the narrow primary resource paths.

### 7.1 Payment-type lookups

The spec includes:

- `GET /invoice/paymentType`
- `GET /travelExpense/paymentType`
- `GET /ledger/paymentTypeOut`

These are likely necessary when a task requires a `paymentTypeId` and the prompt does not directly provide the internal numeric ID.

If the planner only thinks in terms of `/invoice` or `/travelExpense`, it can stall.

### 7.2 Employee entitlement flows

The spec includes:

- `GET /employee/entitlement`
- `PUT /employee/entitlement/:grantEntitlementsByTemplate`
- `PUT /employee/entitlement/:grantClientEntitlementsByTemplate`

This is highly relevant because the scoring docs explicitly mention:

- `Administrator role assigned`

The `Employee` schema does expose `userType`, but admin-like tasks may require entitlement endpoints rather than only `POST /employee` or `PUT /employee/{id}`.

### 7.3 Company or module activation flows

The saved examples page explicitly warns:

- some tasks require enabling modules first

The spec includes adjacent endpoints such as:

- `GET /attestation/companyModules`
- `GET /company/salesmodules`
- `POST /company/salesmodules`
- `GET /project/settings`
- `PUT /project/settings`
- `GET /travelExpense/settings`

This strongly suggests that some tasks may require system or module configuration before the business object workflow can succeed.

### 7.4 Invoice and supplier-invoice payment variants

There is more than one payment workflow in the spec:

- outgoing invoice payment: `PUT /invoice/{id}/:payment`
- supplier invoice payment: `POST /supplierInvoice/{invoiceId}/:addPayment`
- incoming invoice/voucher payment: `POST /incomingInvoice/{voucherId}/addPayment`

The solver should not treat all "register payment" tasks as one generic action.

## 8. Why The Current Planner Is Likely Exhausting

The current architecture is:

1. analyze task
2. ask Gemini for next single action
3. validate it against OpenAPI
4. execute or record error
5. repeat

This is workable, but right now it is vulnerable in a few ways.

### 8.1 The planner is too generic for a strict API

The planner is still responsible for:

- picking the exact endpoint
- choosing exact query parameter names
- deciding which prerequisite lookup endpoints are needed
- deciding which action flow to use

That is too much freedom for a spec with 546 paths and several required-parameter traps.

### 8.2 Validation failures still burn budget

The system is now better than before because invalid actions do not crash the whole request immediately.

But each bad attempt still costs one step.

So if the planner:

- picks a wrong path
- omits required params
- searches too broadly
- forgets a prerequisite endpoint

the budget disappears quickly.

### 8.3 The planner hints are probably too narrow

The current registry hint mapping focuses on prefixes like:

- `/employee`
- `/customer`
- `/invoice`
- `/order`
- `/travelExpense`
- `/project`
- `/department`
- selected `/ledger/*`

That misses or under-emphasizes related endpoints such as:

- `/invoice/paymentType`
- `/travelExpense/paymentType`
- `/ledger/paymentTypeOut`
- `/employee/entitlement/*`
- `/company/salesmodules`
- `/attestation/companyModules`

This can lead the model into a local optimum where it keeps trying primary CRUD endpoints even when the real answer lives in an adjacent setup or lookup endpoint.

### 8.4 Required date-window searches create hidden complexity

For:

- invoices
- orders
- vouchers

the spec requires date windows on searches.

So a prompt like "register payment for invoice 12345" is not a trivial single lookup unless the solver also synthesizes a reasonable date range strategy.

### 8.5 The current loop is one-step-at-a-time, not workflow-first enough

The docs consistently encourage:

- plan before calling
- minimize calls
- avoid trial-and-error

The current implementation is better than blind tool use, but it still replans step-by-step rather than locking a small family-specific workflow up front.

That increases the chance of drift and repeated search loops.

## 9. What The Logs Already Prove

The recent failures match the analysis above.

### 9.1 First failure mode: wrong path normalization

One observed failure was:

- `GET /vatType`

instead of:

- `GET /ledger/vatType`

That confirmed the planner was generating plausible but non-canonical paths.

### 9.2 Second failure mode: local budget exhaustion

Later revisions no longer died immediately on the invalid path, but instead failed with:

- `Planner exhausted its 8-step budget before finishing`

That confirms the system moved from "bad command crashes" to "planner does not converge quickly enough."

This is a meaningful improvement, but it is still not competition-ready.

## 10. Things We Likely Missed In Earlier Written Analysis

The earlier `.md` files were directionally correct, but these items deserve stronger emphasis:

### 10.1 The examples page is not exact enough to drive execution

It should be treated as:

- intent guidance

not:

- request-template truth

### 10.2 Payment tasks need a richer taxonomy

"Register payment" is not one flow. It can mean:

- outgoing invoice payment
- supplier invoice payment
- incoming voucher/invoice payment
- possibly travel-expense-adjacent payment type handling

### 10.3 Admin-role tasks may need entitlement logic

The scoring docs heavily weight administrator-role assignment, but our current coverage documents did not emphasize the entitlement endpoints enough.

### 10.4 Module and settings tasks are real

The examples page explicitly says some tasks require enabling modules first. That should not be treated as a minor edge note.

### 10.5 Search endpoints are not uniformly simple

Some core list endpoints are easy.

Others require date windows or additional shaping that should be encoded explicitly, not rediscovered by the model every time.

## 11. Recommended Changes To The Solver Design

These are the most important next changes.

### 11.1 Treat `openapi.json` as authoritative, examples as illustrative

Operational rule:

- endpoint path, method, and parameter names come from the OpenAPI spec
- task docs and examples inform intent and workflow families only

### 11.2 Replace the generic step loop for core families

The highest-value deterministic handlers are:

- `customer.create`
- `customer.update`
- `employee.create`
- `employee.update`
- `invoice.create`
- `invoice.register_payment`
- `travelExpense.delete`
- `voucher.correct` or `voucher.reverse`

The model should classify and extract.

Python should own the workflow.

### 11.3 Expand planner hint coverage

The hint registry should include related endpoints, not just primary CRUD roots.

At minimum:

- payment-type endpoints
- employee entitlement endpoints
- company/module endpoints
- project and travel settings endpoints
- relevant action endpoints for invoice, voucher, and travel workflows

### 11.4 Separate budgets

Right now one number mixes together:

- planning retries
- invalid actions
- real API operations

That should be split into separate controls such as:

- planner decision budget
- outbound API call budget
- repair retry budget

That is a better fit than one hard `8`.

### 11.5 Add family-specific search synthesis

For families with required date-window filters, build that logic explicitly.

Examples:

- invoice searches should always synthesize `invoiceDateFrom` and `invoiceDateTo`
- order searches should always synthesize `orderDateFrom` and `orderDateTo`
- voucher searches should always synthesize `dateFrom` and `dateTo`

### 11.6 Add first-class payment-type resolution

For payment workflows, do not expect the model to invent numeric `paymentTypeId` values.

Add deterministic lookup helpers using:

- `/invoice/paymentType`
- `/travelExpense/paymentType`
- `/ledger/paymentTypeOut`

### 11.7 Add first-class admin and module flows

For employee admin and module tasks, explicitly support:

- employee entitlement lookup and grant flows
- company sales module activation or module state checks
- project or travel settings where relevant

## 12. Should The Step Budget Be Increased Right Now

Yes, but only as a temporary mitigation.

Short answer:

- `8` is too small for the current generic planner
- simply raising it is not the real fix

Practical recommendation:

- near-term: raise it modestly, for example to `12` or `16`
- medium-term: replace generic looping with deterministic task-family workflows
- long-term: keep a tighter budget once handlers are strong

Why not just set it very high:

- the scoring model rewards efficiency
- a large budget hides poor workflow design
- broad retry loops create more 4xx errors and burn time

## 13. Bottom Line

The main things missed were:

- the examples docs are simplified and sometimes non-canonical
- several important workflows depend on adjacent lookup or setup endpoints
- payment registration is split across multiple endpoint families
- admin-role tasks may require entitlement APIs
- some tasks may require module activation or settings changes
- the current `8-step budget` is our own limit and is too restrictive for the current generic planner

The next implementation work should not be "just prompt the model better."

It should be:

1. keep the model for classification and extraction
2. move core workflows into deterministic Python handlers
3. widen the spec-driven helper coverage to payment types, entitlements, and module flows
4. split planning budget from API-call budget
5. use the OpenAPI spec as the exact source of truth for requests

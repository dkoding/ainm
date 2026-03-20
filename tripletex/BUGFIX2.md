# BUGFIX2

## Scope

- Analyzed the Cloud Run request and stderr logs you provided from `2026-03-20`.
- Covered both revisions visible in the logs:
  - `tripletex-agent-00016-72w`
  - `tripletex-agent-00017-kjx`
- Audited all relevant local code paths instead of inferring from logs alone:
  - `app/main.py`
  - `app/solver.py`
  - `app/planner.py`
  - `app/internal_tasks.py`
  - `app/workflow_router.py`
  - `app/spec_runtime.py`
  - `app/client.py`
  - `docs/openapi.json`
  - `API.md`
  - `TROUBLESHOOTING.md`

## What The Logs Actually Show

There are three different categories in the pasted logs, and they must not be mixed together:

1. Old defects from revision `00016-72w`.
2. Regressions still present in revision `00017-kjx`.
3. Requests that are behaving correctly and should remain validation failures.

The critical mistake in the previous implementation was treating all `422` and `500` responses as one problem. They are not.

## Confirmed Findings

### 1. `GET /` and `GET /favicon.ico` were broken in `00016`, but are already fixed in `00017`

- Evidence in `00016-72w`:
  - `2026-03-20T21:55:28Z` `GET /` returned `405`
  - `2026-03-20T21:55:29Z` `GET /favicon.ico` returned `404`
- Evidence in `00017-kjx`:
  - `2026-03-20T22:24:07Z` `GET /` returned `200`
  - `2026-03-20T22:24:07Z` `GET /favicon.ico` returned `204`
- Code path:
  - `app/main.py` now has:
    - `@app.get("/")`
    - `@app.get("/favicon.ico")`
- Conclusion:
  - This problem is already fixed in the current codebase.
  - No additional code change was needed here.

### 2. `POST /` returning `422` is not the same bug as `GET /` returning `405`

- Evidence:
  - `2026-03-20T21:48:05Z` `POST /` returned `422`
  - `2026-03-20T22:24:07Z` `POST /` still returned `422`
- Code path:
  - `app/main.py` already exposes `POST /` as a solve alias:
    - `solve_root()`
  - `app/models.py` requires a valid `SolveRequest`:
    - `prompt`
    - `tripletex_credentials.base_url`
    - `tripletex_credentials.session_token`
- Conclusion:
  - `POST /` is not missing.
  - The `422` here is FastAPI/Pydantic request validation.
  - This should remain `422` for malformed solve payloads.
  - This log line is not a backend bug.

### 3. Vertex AI `429 RESOURCE_EXHAUSTED` was incorrectly surfaced as `500`

- Evidence in `00016-72w`:
  - `2026-03-20T21:59:54Z`
  - Planner threw `google.genai.errors.ClientError: 429 RESOURCE_EXHAUSTED`
  - Request still ended as `500`
- Root cause:
  - Planner failures were reaching the HTTP layer as generic internal errors.
- Code path:
  - `app/main.py`
  - `_planner_status_code()`
  - `_planner_detail()`
- Current behavior:
  - `429`/`RESOURCE_EXHAUSTED` is mapped to `503`
  - response detail now tells the caller to retry later
- Conclusion:
  - This old `00016` failure mode is fixed in the current code.

### 4. The old time-registration-plus-invoice task was misclassified as `UnknownMethod`

- Evidence in `00016-72w`:
  - `2026-03-20T21:59:22Z`
  - planner analysis returned `method_name=UnknownMethod`
  - task family was project billing / invoicing from time
  - subsequent planning hit Vertex AI repeatedly and then failed
- Root cause:
  - The request is a multi-step workflow:
    - resolve customer
    - resolve employee
    - resolve project
    - resolve activity
    - create/update timesheet entry
    - create order
    - create invoice
  - Treating this as a generic unknown invoice task forced too much planner work.
- Code path:
  - `app/internal_tasks.py`
  - `normalize_task_analysis_method_selection()`
  - `_looks_like_time_tracking_invoice_request()`
  - `RunProjectTimeInvoiceWorkflow`
  - `app/workflow_router.py`
  - `_next_project_time_invoice_workflow()`
- Conclusion:
  - Current code now has a deterministic project time invoicing workflow for this class of request.
  - This old `UnknownMethod` issue is fixed.

### 5. The old ledger-dimension workflow could mutate state and then crash because voucher requirements were incomplete

- Evidence in `00016-72w`:
  - `2026-03-20T21:56:36Z` dimension created
  - `2026-03-20T21:56:37Z` dimension values `IT` and `HR` created
  - then solver raised:
    - `Deterministic method routing could not continue`
    - `Planner-generated API actions are disabled for supported methods`
- What is known from the log:
  - The task requested both:
    - dimension creation
    - voucher posting
  - Planner extracted:
    - `postingAccount`
    - `postingAmount`
    - `postingDimensionValue`
  - Planner did not extract a balancing account
- Root cause:
  - A Tripletex ledger voucher must be balanced.
  - The old flow allowed voucher mode to start without requiring `counterAccount`.
  - That meant the flow could partially mutate state and only fail after the dimension/value creation phase.
- Code path:
  - `app/internal_tasks.py`
  - `_ledger_dimension_payload()`
  - `resolved_missing_required_arguments()`
  - `app/workflow_router.py`
  - `_next_ledger_dimension_workflow()`
- Current fix:
  - When the prompt implies voucher posting, `counterAccount` is now treated as required.
  - Missing voucher requirements are rejected early as `422` input errors instead of creating partial state and then crashing later.
- Conclusion:
  - The ledger workflow bug was incomplete required-argument enforcement, not the dimension creation calls themselves.

### 6. Revision `00017` was still dropping VAT intent before `POST /order`

- Evidence in `00017-kjx`:
  - The invoice request at `2026-03-20T22:28:40Z` included three explicit VAT rates:
    - `25 %`
    - `15 %`
    - `0 %`
  - The logged internal payload only preserved simplified order-line fields.
  - The first `POST /order` failed with `422`.
  - The retry only added `deliveryDate`; no VAT repair happened before the next attempt.
- Root cause:
  - `app/internal_tasks.py` extracted order lines but discarded VAT metadata.
  - `app/workflow_router.py` created order lines without resolving a `vatType` reference.
  - This means the user requested VAT semantics were lost before the write payload was built.
- Code changes made:
  - `app/internal_tasks.py`
    - `_extract_order_lines()` now preserves VAT information.
    - `_extract_vat_type_reference()` now normalizes:
      - nested `vatType`
      - `vatTypeId`
      - `vatTypeNumber`
      - `vatCode`
      - `vatTypeName`
      - `vatTypeDisplayName`
      - `vatRate`
      - `vatPercentage`
      - `percentage`
  - `app/workflow_router.py`
    - added `_resolved_vat_type_by_ref()`
    - added `_vat_type_lookup_params()`
    - sales workflow now calls `GET /ledger/vatType` before order creation when explicit VAT intent exists
    - `_build_order_payload_from_internal()` now writes `vatType: {"id": ...}` onto each order line
  - `app/spec_runtime.py`
    - `_resolve_vat_type_reference()` now resolves VAT types by percentage as well as code/name
- Conclusion:
  - This was a real data-loss bug in the request translation layer.
  - It is now fixed.

### 7. Revision `00017` still omitted `deliveryDate` from generated order payloads

- Evidence in `00017-kjx`:
  - First `POST /order` returned `422`
  - planner fallback explicitly said:
    - `The previous attempt to create an order failed because the deliveryDate was missing.`
  - retry with `deliveryDate` succeeded:
    - `POST /order` returned `201`
- Root cause:
  - Local order builders were not consistently including `deliveryDate`.
- Code changes made:
  - `app/internal_tasks.py`
    - `RunSalesWorkflow` and `RunProjectTimeInvoiceWorkflow` now accept `deliveryDate`
    - `_sales_payload()` now defaults `deliveryDate`
    - `_project_time_invoice_payload()` now defaults `deliveryDate`
  - `app/workflow_router.py`
    - `_build_order_payload_from_internal()` now includes `deliveryDate`
    - `_build_project_time_invoice_order_payload()` now includes `deliveryDate`
- Conclusion:
  - This was a confirmed root cause from the logs.
  - It is now fixed.

### 8. Revision `00017` repeated the same failing invoice conversion call until the step budget ran out

- Evidence in `00017-kjx`:
  - `POST /order` succeeded at `2026-03-20T22:28:51.978Z`
  - then the service repeatedly called:
    - `PUT /order/401975280/:invoice`
  - every one of those returned `422`
  - the same action was repeated in steps `7`, `8`, `9`, `10`, `11`, and `12`
  - final solver error:
    - `Planner exhausted its 12-step budget before finishing`
- Root cause:
  - The deterministic router had no exact-error matching helper wired into its fallback branch.
  - The same failing request could be produced again and again.
  - The service was not learning from its own immediate `422` history.
- Important point:
  - The logs do not expose the exact Tripletex validation message for that invoice conversion failure.
  - It would be incorrect to invent a specific hidden requirement from those logs alone.
  - The safe repair is:
    - surface the validation payload
    - stop replaying the same invalid request
    - use the documented direct invoice path when the action endpoint fails
- Code changes made:
  - `app/workflow_router.py`
    - added `_has_api_error_exact_where()`
    - sales workflow now falls back from:
      - `PUT /order/{id}/:invoice`
      - to `POST /invoice`
      after the first exact `422`
    - project time invoice workflow now uses the same fallback
    - fallback payload uses the repo-local documented structure:
      - `invoiceDate`
      - `invoiceDueDate`
      - `customer`
      - `orders: [{"id": ...}]`
  - `app/solver.py`
    - added `_prior_repeatable_tripletex_error()`
    - identical non-retryable `4xx` Tripletex requests are now skipped instead of burning API calls repeatedly
- Conclusion:
  - This retry loop was a real deterministic-routing bug.
  - It is now fixed in two layers:
    - router-level fallback
    - solver-level duplicate-failure suppression

### 9. Validation details were present in Tripletex responses but effectively hidden by local logging

- Evidence:
  - The logs show Tripletex returned structured error payloads with:
    - `developerMessage`
    - `validationMessages`
  - But local request logging summarized responses only as dict keys.
  - That prevented the next planning step from having strong error context in logs, and made human debugging harder than necessary.
- Root cause:
  - `app/client.py` reduced response logging to:
    - dict type
    - first few keys
  - `TripletexAPIError` message text also dropped most of the useful validation detail.
- Code changes made:
  - `app/client.py`
    - `_summarize_payload()` now includes:
      - `status`
      - `code`
      - `message`
      - `developerMessage`
      - first validation messages
    - `TripletexAPIError` string now includes a compact validation suffix
- Conclusion:
  - This was not the primary business bug, but it was a major observability bug.
  - It is now fixed.

## Files Changed

- `app/client.py`
- `app/internal_tasks.py`
- `app/spec_runtime.py`
- `app/solver.py`
- `app/workflow_router.py`

## Verification Performed

- Syntax check passed:
  - `python3 -m py_compile app/*.py`
- Runtime smoke checks passed in a temporary virtualenv:
  - VAT type resolution by percentage now resolves correctly
  - sales order payload now carries `deliveryDate`
  - sales order payload now carries resolved `vatType` ids
  - project time invoice order payload now carries `deliveryDate`
  - after an exact `422` on `PUT /order/{id}/:invoice`, router now falls back to `POST /invoice`
  - duplicate identical `4xx` Tripletex requests are now detected and skipped
  - client-side error summaries now expose `developerMessage` and `validationMessages`

## Final Status

- Already fixed before this pass:
  - `GET /`
  - `GET /favicon.ico`
  - planner `429` surfacing as `500`
  - old `UnknownMethod` project time invoice routing
  - old ledger voucher partial-flow bug
- Fixed in this pass:
  - VAT intent loss in sales order extraction/building
  - missing `deliveryDate` propagation
  - repeated `PUT /order/{id}/:invoice` retry loop
  - hidden Tripletex validation detail
  - generic duplicate `4xx` command replay
- Not a bug:
  - `POST /` returning `422` when the body is not a valid `SolveRequest`

## One Thing I Am Explicitly Not Guessing

The exact hidden Tripletex validation rule behind the `PUT /order/401975280/:invoice -> 422` responses in revision `00017` cannot be proven from the pasted logs, because that revision did not surface the actual `validationMessages` content in its own logs. The fix therefore avoids guessing. It does two concrete things instead:

- exposes the real validation payload next time
- stops replaying the same failing action and falls back to the documented direct invoice path

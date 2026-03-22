# New Bugs: Production Log Analysis for the Last 15 Minutes

## Scope

- Analysis time: `2026-03-22T10:58:29+01:00`
- Log window analyzed: `2026-03-22T09:43:29Z` to `2026-03-22T09:58:29Z`
- Sources used:
  - [`RULES.md`](./RULES.md)
  - [`DESC.md`](./DESC.md)
  - [`API.md`](./API.md)
  - [`docs/openapi.json`](./docs/openapi.json)
  - `scripts/cloud_run_logs.sh read 80`
  - `artifacts/cloud_run_logs/tripletex-agent.log`

## Important Exclusions

These log lines are not part of the production defect cluster for this analysis:

- local malformed `POST /solve` `422` requests from shell quoting errors
- local attachment import tests using artificial text-file payloads
- earlier local tests on revisions `00052` to `00054` that intentionally exercised missing attachments or fake selectors

Per the user instruction, the fix should not target those local test artifacts.

## Real Requests Observed

Within the analysis window, the logs show these meaningful production paths:

### 1. Control success: customer creation

- Revision: `tripletex-agent-00055-blt`
- Time: `2026-03-22T09:49:20Z` to `2026-03-22T09:50:26Z`
- Behavior:
  - planner selected `customer.create`
  - transport called `POST /customer`
  - request completed successfully

Conclusion:
- the service is live
- credentials and transport are working
- the current regression is not a general deployment failure

### 2. Blocked plan: travel expense

- Revision: `tripletex-agent-00055-blt`
- Time: `2026-03-22T09:54:29Z`
- Behavior:
  - planner selected `travel_expense.create_with_rows`
  - validator demoted execution to blocked with concrete missing inputs

Conclusion:
- this is not a bug by itself
- this is the expected blocked-plan behavior for insufficient task data

### 3. Hard failure: `invoice.order_first`

- Revision: `tripletex-agent-00055-blt`
- Time: first failure `2026-03-22T09:54:32Z`, repeated after repair at `2026-03-22T09:55:40Z`
- Execution path:
  - planner selected `invoice.order_first`
  - flow executed customer resolution
  - flow resolved currency
  - flow called `POST /order`
  - Tripletex returned `422 Request mapping failed`

- Exact API validation message:
  - `field: unitPriceExVat`
  - `message: Feltet eksisterer ikke i objektet.`

Conclusion:
- this is a real execution bug
- it is repeatable across both the first execution and the repair path
- the repair loop did not change the payload family or field names, so the system retried the same schema-invalid write shape

### 4. Planner JSON instability

- Revision: `tripletex-agent-00055-blt`
- Times:
  - `2026-03-22T09:51:18Z`
  - `2026-03-22T09:55:49Z`
- Behavior:
  - `/solve` returned `200`
  - app logged `Planner output was not valid JSON`

Conclusion:
- this is still a real production failure family
- it is independent of the `/order` field-name mismatch
- it remains an LLM-boundary reliability problem

## What the Docs Say

### Order creation contract

The repo docs and OpenAPI both point to the same order/invoice shape constraints:

- [`DESC.md`](./DESC.md): `invoice.order_first` is the default invoicing flow when line items are present
- [`DESC.md`](./DESC.md): direct invoice creation should be structured as `invoice -> orders -> orderLines`
- [`DESC.md`](./DESC.md): `Invoice.orderLines` is read-only
- [`app/generated/command_catalog.json`](./app/generated/command_catalog.json): `order.create` currently models `order_lines[]` using payload family `line_item`
- [`docs/openapi.json`](./docs/openapi.json): `POST /order` takes schema `Order`
- [`docs/openapi.json`](./docs/openapi.json): `Order.orderLines` embeds schema `OrderLine`
- [`docs/openapi.json`](./docs/openapi.json): `OrderLine` writable price fields are:
  - `unitPriceExcludingVatCurrency`
  - `unitPriceIncludingVatCurrency`

The OpenAPI does **not** define:

- `unitPriceExVat`
- `unitPriceIncVat`

### Attachment import contract

The docs are explicit that `POST /ledger/voucher/importDocument` only accepts:

- PDF
- PNG
- JPEG
- TIFF

This came from:

- [`docs/openapi.json`](./docs/openapi.json): `Valid document formats are PDF, PNG, JPEG and TIFF. EHF/XML is possible with agreement with Tripletex. Send as multipart form.`

This matters for real attachment flows, but the log evidence for the recent `422 Ugyldig format` was from an artificial local test input and is therefore excluded from the root production defect cluster in this analysis.

## Root Cause Analysis

## 1. Wrapper payload families are not sufficiently bound to the real writable OpenAPI schema

The live `/order` failure shows that the current internal `line_item` payload family still uses legacy/internal field aliases:

- `unit_price_ex_vat -> unitPriceExVat`
- `unit_price_inc_vat -> unitPriceIncVat`

But the real `OrderLine` write schema in `docs/openapi.json` uses:

- `unitPriceExcludingVatCurrency`
- `unitPriceIncludingVatCurrency`

That means the bug is not in one prompt or one repair attempt.

It is a contract-generation / payload-translation bug at the wrapper boundary.

Because the same `line_item` payload family is reused across flows and commands, this category can affect more than `invoice.order_first`.

## 2. The repair loop cannot solve schema drift if the canonical translator is wrong

The logs show:

- first `/order` attempt failed with `unitPriceExVat`
- repair reran the same flow
- second `/order` attempt failed with the same field

This means the repair system is downstream of the real defect.

If the canonical body translator emits a schema-illegal field name, retries will continue to fail.

So the fix must be:

- upstream of execution
- upstream of repair
- derived from OpenAPI, not from prompt tweaking

## 3. Planner invalid-JSON failures are still a separate root problem

The invalid-JSON events are not explained by the `/order` field mismatch.

They indicate the one-shot LLM boundary still has a residual reliability gap.

This is a second real defect family in the window, but it is not the same as the order schema drift.

## Common Pattern Across the Real Bugs

The common architectural weakness is:

- the system still trusts internal bridge/payload abstractions more than the final documented writable OpenAPI schema at some wrapper mutation boundaries
- when the LLM or wrapper emits a shape that is not aligned with the true write contract, the system discovers that only after transport
- repair is then operating too late in the pipeline

In short:

- the source of truth is `docs/openapi.json`
- the current guards are stronger for raw operations than for wrapper-generated nested mutation payloads
- the missing root fix is schema-derived validation and field projection for wrapper mutation bodies before transport

## What a Holistic Fix Must Do

Any acceptable fix for this log window should:

1. Derive wrapper mutation payload field projection from the real OpenAPI write schema, not from stale hand-maintained aliases.
2. Validate wrapper-generated nested bodies against the target writable OpenAPI schema before transport, not only after Tripletex rejects them.
3. Apply that validation generically across wrapper commands and flows, so future `field does not exist in object` errors are caught before execution.
4. Keep attachment validation aligned with the documented multipart contract, but not by reacting to artificial local test payloads.
5. Improve planner JSON boundary robustness separately, because invalid JSON is still occurring in real traffic.

## Bottom Line

The real production bug in the last 15 minutes is not an attachment-media transport issue.

The primary execution bug is that wrapper-generated order line payloads are still using field names that do not exist in the writable `OrderLine` schema from `docs/openapi.json`.

That is a source-level contract bug and must be fixed at the schema generation / wrapper validation layer, not by patching one concrete request.

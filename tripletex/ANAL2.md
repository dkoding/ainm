# ANAL2: Production Failure Analysis Before New Code Changes

## Scope

- Analysis date: `2026-03-22`
- Requested production window: last `15` minutes before analysis
- Effective observed window in the active Cloud Run tail:
  - start: `2026-03-22T11:01:09Z`
  - end: `2026-03-22T11:15:22Z`
- Log source used for this pass:
  - `artifacts/cloud_run_logs/tripletex-agent.log`
  - specifically `tail -n 120` and `tail -n 200`

## Sources Read Before Any Coding

- `RULES.md`
- `DESC.md`
- `LLM.md`
- `ANALYSIS.md`
- `docs/openapi.json`
- `app/contracts/bridge.py`
- `app/llm/llm_planner.py`
- `app/llm/prompt_builder.py`
- `app/llm/response_validator.py`
- `app/llm/attachment_evidence_builder.py`
- `app/llm/attachment_fact_extractor.py`
- `app/llm/context_catalog.py`
- `app/llm/json_payloads.py`
- `app/openapi_catalog.py`
- `app/router/service.py`
- `app/runtime_refs.py`
- `app/wrapper/flows.py`
- `app/generated/command_catalog.json`
- `app/generated/flow_catalog.json`
- `app/generated/operation_catalog.json`

## Rules And Docs That Matter For This Window

- `RULES.md` Rule 1: the system exists to complete the task, not stop at analysis.
- `RULES.md` Rule 2: `/solve` is one-shot. The system cannot require a later human turn for a task that should be executable in one request.
- `RULES.md` Rule 3: attachment handling is mandatory.
- `RULES.md` Rule 5: correctness first, then minimal calls and minimal errors.
- `RULES.md` Rule 12: prefer the narrowest correct route and avoid undocumented assumptions.
- `docs/openapi.json` top-level description explicitly says some endpoints are only supported in certain packages and that missing fields can occur because of authorization filtering.
- `docs/openapi.json` marks the `incomingInvoice` endpoints as `Restricted API for pilot customers`.
- `LLM.md` says attachments must be normalized into structured JSON before execution planning.
- `DESC.md` defines `supplier_invoice.import_from_attachment` as the attachment-derived bookkeeping path, but its current documented step list includes pilot-only `incoming_invoice.*` commands.

## Complete Issue List From The Current Live Window

### 1. Hard failure after attachment import: pilot-only follow-up command

- Request completed attachment import steps and then failed on:
  - `2026-03-22T11:14:46.161795Z`
  - `GET /incomingInvoice/609415405`
  - status `403`
  - message: `You do not have permission to access this feature.`
- Full logged execution path:
  1. `GET /supplier` with `organizationNumber`
  2. `POST /supplier`
  3. `POST /ledger/voucher/importDocument`
  4. `GET /incomingInvoice/{voucherId}` -> `403`

What this proves:

- attachment ingestion worked
- supplier resolution/creation worked
- multipart upload worked
- the failure happened after import, not during attachment extraction or upload

Why it failed:

- `app/wrapper/flows.py` currently makes `supplier_invoice.import_from_attachment` call `incoming_invoice.get` unconditionally after `ledger.voucher.import_document`
- `DESC.md`, `app/generated/command_catalog.json`, and `docs/openapi.json` all mark `incoming_invoice.get` and `incoming_invoice.update` as restricted/pilot APIs
- in this tenant, that capability is not available, so the unconditional follow-up read hard-failed the whole task

Why this is a root problem:

- this is not an attachment-media bug
- this is not a single-endpoint bug
- this is an execution-policy bug:
  - the system knows from docs/catalog metadata that some commands are restricted
  - but flow execution does not use that metadata to distinguish:
    - required business steps
    - optional enrichment steps
    - optional verification steps
- that means any future flow that performs a non-essential restricted follow-up can fail the whole request the same way

### 2. Planner emitted bridge JSON that violated the bridge schema

- `2026-03-22T11:15:22.988049Z`
- Logged failure:
  - `Planner output did not match the bridge schema.`
  - error at `('sources', 'prompt')`
  - expected `string`
  - got object:
    - `{"text": "...", "normalizedDate": "2026-03-22", "timezone": "Europe/Oslo"}`

Why it failed:

- the bridge contract in `app/contracts/bridge.py` requires `sources.prompt: str | None`
- the LLM produced a richer prompt-source object instead of the canonical string
- `app/llm/response_validator.py` currently injects prompt defaults, but it does not normalize richer prompt-source structures into the canonical bridge form before Pydantic validation

Why this is a root problem:

- this is not just one bad LLM sample
- it shows that the boundary between:
  - raw LLM output
  - evidence/source sections
  - validated bridge JSON
  is still too brittle
- the system already performs normalization for many command/body/input types
- it does not yet do the same for the bridge evidence layer itself

This family can recur for:

- `sources.prompt`
- `language.promptOriginal`
- `language.promptCanonical`
- attachment/source wrappers that carry text plus provenance instead of the exact final scalar shape

### 3. Over-blocked one-shot request: analysis-only bridge for a task that should remain one-turn executable

- `2026-03-22T11:15:18.795573Z`
- Logged failure:
  - `Bridge JSON is blocked.`
  - blocking issue:
    - `The plan to create projects and activities is incomplete. The system can only execute the analysis part of the request. The creation steps need to be defined in a subsequent turn after the analysis is complete and the top three accounts are identified.`
- Selected steps before block:
  - `ledger.posting.search`
  - `ledger.posting.search`
  - `ledger.account.search`

Why it failed:

- the planner was able to express the read/analysis half of the task
- it did not have a supported way to carry derived results from those reads into the later create steps
- instead of producing a fully executable one-shot plan, it degraded to an imaginary multi-turn workflow

Why this is a root problem:

- `RULES.md` explicitly says the system cannot depend on later clarification turns for competition execution
- current runtime support is weak here:
  - `BridgeRouter` stores outputs by step id, but later inputs are not resolved from prior results
  - `runtime_refs.py` and `response_validator.py` currently reject step-output placeholders because there is no supported runtime dereference system
- that previous safeguard prevented invalid placeholder refs, but it also removed any supported mechanism for legitimate one-turn `search -> derive -> create` workflows

This is a genuine capability gap, not just a prompt wording problem.

## Common Pattern Across The Real Bugs

The failures are different on the surface, but they share one deeper problem:

- the system is still not treating contract metadata as executable runtime semantics

Three forms of that drift are visible:

1. Capability metadata drift
   - docs/catalog know an endpoint is restricted
   - runtime still treats it like a universally safe mandatory step

2. Bridge-shape normalization drift
   - the planner emits semantically valid evidence, but in a richer shape
   - validator expects the final exact schema immediately instead of normalizing it

3. Dataflow capability drift
   - the planner can reason about dependent multi-step tasks
   - runtime lacks a first-class way to carry selected values from earlier results into later steps
   - the planner therefore blocks or invents a later human turn

## Attachment Handling Assessment

## What works today

- `app/llm/attachment_evidence_builder.py` builds structured attachment evidence before planning
- `app/llm/attachment_fact_extractor.py` runs Gemini against that evidence and media
- `app/llm/json_payloads.py` is already used there, so attachment JSON wrapped in fences/prose can now still be parsed
- `app/llm/prompt_builder.py` passes both raw attachment evidence and normalized `attachmentFacts` into the planning call
- `app/llm/response_validator.py` already enforces that attachment-dependent routes require valid `sources.attachments`
- `ledger.voucher.import_document` correctly maps `attachment_id` to the multipart `file` field from the request attachment

Conclusion:

- yes, the LLM path can extract data from uploaded PDFs/images and turn it into structured JSON before planning
- the current live attachment failure was not caused by failed extraction

## What does not work well enough

- the attachment flow depends on pilot-only `incoming_invoice.*` steps even when the user task may already be satisfiable without them
- attachment understanding is therefore stronger than the follow-up execution policy

Real implication:

- the attachment pipeline is good enough to produce useful JSON
- the downstream execution path is not capability-aware enough to use that JSON safely in all tenants

## Root Causes

### Root Cause A: Restricted-command metadata is descriptive only, not operational

Evidence:

- `docs/openapi.json` and `command_catalog.json` say `incoming_invoice.get` / `incoming_invoice.update` are restricted APIs for pilot customers
- runtime still executes them as hard requirements in `supplier_invoice.import_from_attachment`

Required fix class:

- promote restriction metadata into a real runtime capability model
- distinguish:
  - mandatory route steps
  - optional enrichment reads
  - optional verification reads
- make optional restricted follow-ups non-fatal when the core business task is already complete
- make required restricted capabilities block or reroute deterministically instead of failing late

### Root Cause B: Bridge evidence normalization is too narrow

Evidence:

- `sources.prompt` object caused schema failure even though it contained the needed source text

Required fix class:

- add a normalization layer for bridge evidence sections before Pydantic validation
- canonicalize richer prompt/source objects into the bridge contract
- do this centrally, not by special-casing one prompt form

### Root Cause C: The system lacks a supported one-turn result-binding mechanism

Evidence:

- the planner blocked a task because it could only express the analysis part and not the derived create steps
- runtime stores outputs but cannot bind later inputs from them

Required fix class:

- introduce a supported, validated step-result reference model
- make it available in planner instructions, validator normalization, and router execution
- keep the guard against arbitrary free-form placeholders, but replace the total ban with a supported contract

Without this, any task of the form:

- search
- identify subset
- create/update based on those exact discovered values

will remain fragile or block incorrectly.

## What Should Not Be Misdiagnosed

- The attachment failure is not a PDF/image extraction failure.
- The `403` is not evidence that the client sent bad data.
- The schema failure is not evidence that the bridge model should become untyped.
- The blocked project/activity request is not evidence that the task truly needs a second user turn.

## Required Holistic Fix Direction

The next code changes should target three root layers, in this order:

1. Capability-aware execution
   - teach the runtime and flow layer to use restricted/pilot metadata from docs/catalogs
   - optional restricted follow-up reads must not hard-fail successful core mutations

2. Bridge evidence normalization
   - normalize richer `sources` and language prompt structures into canonical bridge scalars before validation

3. Supported step-result binding
   - add one validated mechanism for using prior step outputs in later steps
   - update planner guidance to use that mechanism instead of blocking multi-step one-shot tasks

## Bottom Line

The current failures are not random regressions.

They show that three contract boundaries are still incomplete:

- capability restrictions from docs are not enforced as execution semantics
- bridge evidence is not normalized robustly enough before schema validation
- multi-step derived execution has no supported runtime binding model

Attachment extraction itself is on the core path and is functioning.
The broken part is the execution contract that follows it.

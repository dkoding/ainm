# Analysis: Cloud Run Failures in the Last 5 Minutes

## Scope

- Analysis time: `2026-03-22T10:20:38+01:00`
- Log window analyzed: `2026-03-22T09:15:38Z` to `2026-03-22T09:20:38Z`
- Active revision: `tripletex-agent-00052-lcx`
- Sources used:
  - `gcloud logging read` for `tripletex-agent`
  - `artifacts/cloud_run_logs/tripletex-agent.log`
  - `app/llm/attachment_evidence_builder.py`
  - `app/llm/gemini_client.py`
  - `app/llm/llm_planner.py`
  - `app/llm/prompt_builder.py`
  - `app/llm/response_validator.py`

## Control Cases

These show the service and the latest root fixes are partially working.

- `2026-03-22T09:16:48Z`: `/health` returned `200`.
- `2026-03-22T09:17:07Z`: a direct bridge JSON using invalid selector ids for `invoice.register_payment` no longer failed with `...id must be an integer id`; it reached `GET /invoice` with `invoiceNumber`, then failed only because the invoice selector was deliberately nonexistent.
- `2026-03-22T09:18:04Z`: `TimesheetEntryTotalHours_getTotalHours` executed successfully with only `startDate` and `endDate`.
- `2026-03-22T09:18:53Z` to `2026-03-22T09:18:54Z`: three `department.create` commands executed successfully.
- `2026-03-22T09:18:36Z`: Vertex AI primary returned `429`, but fallback kicked in and the overall request still completed.

Conclusion: this is not a deployment outage, auth outage, or a regression in the invalid-id normalization fix. The new failures are concentrated in planner output normalization, especially for attachment-centric blocked plans.

## Complete Issue List in the Window

### 1. FastAPI-level `POST /solve` request rejected with HTTP 422

- Timestamp: `2026-03-22T09:16:48.977065Z`
- Evidence:
  - request log shows `POST /solve` -> `422`
  - there is no matching `tripletex_app solve.failed`

Assessment:
- This was malformed local test traffic, not application logic.
- It should be excluded from the product failure cluster.

### 2. `Planner output did not match the bridge schema`

- Timestamp: `2026-03-22T09:19:28.665128Z`
- Prompt context: attachment-oriented prompt with no files
- Detailed validation error:
  - `validation.blockingIssues[0]` was an object, not a string
  - actual model output item:
    - `level: error`
    - `code: missing_required_input`
    - `message: The prompt asks to bookkeep an attachment, but no attachment was provided...`
    - `blockingInputs: ['attachment_id']`

Assessment:
- The planner produced a semantically good blocked-plan diagnostic.
- The failure was structural: the bridge schema currently expects `validation.blockingIssues` to be `list[str]`, but the model emitted `list[object]`.
- This is not a business-logic error. It is a normalization-gap error at the planner-output boundary.

### 3. `Planner output was not valid JSON`

- Timestamp: `2026-03-22T09:19:54.144372Z`
- Layer: planner output transport / parsing

Assessment:
- This is the same broad model-output-contract instability seen earlier.
- In this 5-minute slice it appears after the attachment-blocking case, so it likely belongs to the same family of weak output canonicalization for non-executable/blocked responses.

### 4. Vertex primary model `429` with fallback retry

- Timestamp: `2026-03-22T09:18:36.444996Z`
- Result: request still completed successfully via fallback

Assessment:
- This is operational noise, not the root cause of the planner/schema failures.
- It matters for latency and resilience, but not for the current correctness defect.

## Common Patterns Across the Failures

The current failures are no longer about:

- bad raw body field names
- invalid nested selector ids dominating flow refs
- missing OpenAPI coercion for raw parameters

Those areas improved in the latest revision.

The new common pattern is:

- attachment-centric or blocked-plan outputs are semantically close to correct
- but the LLM is still being asked to do too many jobs in one response:
  - inspect attachments
  - infer missing inputs
  - decide executability
  - format the final bridge JSON exactly
- the normalization layer is still too weak for structured blocked-plan diagnostics

This means the remaining defect boundary is planner-output canonicalization for attachment-aware blocked flows, not raw execution.

## Do We Handle Attachments Properly?

Short answer: partially, but not strongly enough at the structured-data boundary.

## What currently works

### 1. Attachments do reach the LLM in Vertex mode

`LLMPlanner.plan(...)` builds `attachment_media` with:

- `attachmentId`
- `filename`
- `mimeType`
- `contentBase64`

`GeminiClient._build_user_parts(...)` then sends:

- a JSON part containing `request` and `context`
- one text part per attachment
- one `inlineData` part per attachment for:
  - `image/*`
  - `application/pdf`

So in the deployed Vertex path, Gemini can directly inspect image and PDF bytes.

### 2. Local attachment evidence is included

`AttachmentEvidenceBuilder.build(...)` produces evidence entries with:

- `attachmentId`
- `filename`
- `mimeType`
- `extractedText`
- `warnings`
- `provenance.mode`
- `supportsMultimodal`

That means the planner gets both:

- local text evidence when available
- direct multimodal media for PDFs/images

### 3. Text and embedded-PDF extraction already exist

- text files, JSON, CSV, and Markdown are locally decoded into `extractedText`
- PDFs with embedded text are locally parsed via `pypdf`

## What is still weak or missing

### 1. There is no dedicated attachment-to-JSON extraction stage

The system does not first extract structured attachment facts into a typed JSON schema before planning.

Current behavior:

- attachment understanding and bridge planning happen inside the same LLM response
- `AttachmentEvidenceBuilder.extractedFactHints` is always empty
- no deterministic intermediate attachment-facts object exists

Why this matters:

- when the prompt is attachment-centric, the model must invent both:
  - the semantic diagnosis
  - the exact bridge-schema formatting
- this is exactly where the current blocked-plan object-vs-string failure came from

### 2. Local OCR is effectively absent

For images and scanned PDFs:

- `ocrText` is always empty
- `ocrConfidence` is always `0.0`
- local extraction falls back to `multimodal_only`

This is acceptable only if Gemini is consistently used and the model behaves perfectly. It is not a robust structured extraction pipeline by itself.

### 3. Endpoint-mode Gemini requests silently drop media

`GeminiClient.generate(...)` strips `media` when `GEMINI_ENDPOINT` is used:

- `request_payload = {key: value for key, value in prompt_package.items() if key != "media"}`

That means:

- in Vertex mode, attachments are sent
- in custom endpoint mode, attachments are not sent at all

This is a systemic attachment-handling gap even if it is not the current Cloud Run failure mode.

### 4. The normalization layer is not attachment-aware enough

`ResponseValidator._normalize(...)` already canonicalizes:

- missing sections
- step arrays
- step ids
- flow/command argument keys
- semantic payload keys
- raw input coercion

But it does not yet robustly canonicalize:

- structured validation issue objects into the schema’s expected string lists
- richer blocked-plan diagnostics that attachment prompts naturally elicit
- attachment-derived structured outputs before bridge-schema validation

## Why the Current Design Fails

## 1. Attachment understanding and bridge formatting are still coupled

The same model response is responsible for:

- reading attachment evidence/media
- deciding what is missing
- deciding whether the plan is executable
- producing exact bridge JSON

That coupling is the root reason attachment-centric prompts still break structurally even when the semantic conclusion is correct.

## 2. The bridge schema expects strings where the planner naturally wants richer diagnostics

For blocked attachment prompts, the model naturally emits objects like:

- `code`
- `message`
- `blockingInputs`

The current bridge schema accepts only strings in `validation.blockingIssues`.

That mismatch is now an architectural problem, not a one-off prompt problem.

## 3. Attachment preprocessing is informational, not contractual

`AttachmentEvidenceBuilder` provides metadata and text, but not a typed contract such as:

- supplier invoice facts
- amounts
- dates
- invoice numbers
- VAT indicators
- payment clues

So attachment data reaches the model, but the system does not force that understanding into a stable JSON layer before planning.

## Root Problem Statement

The root problem is that attachment-aware reasoning still lacks its own canonical structured boundary.

Today the system has:

- raw input normalization
- semantic selector normalization
- OpenAPI-backed raw body validation

But it still lacks:

1. typed attachment-fact extraction
2. robust normalization for blocked-plan issue objects
3. consistent attachment transport across all LLM backends

Because that boundary is missing, attachment-centric prompts still oscillate between:

- semantically reasonable blocked plans
- schema-invalid blocked-plan objects
- outright invalid JSON

## Requirements for a Holistic Fix

Any acceptable fix should do all of the following.

### 1. Normalize validation issue payloads generically

Before bridge-schema validation:

- accept string or object diagnostics in `validation.blockingIssues`, `warnings`, and similar lists
- canonicalize object items to stable strings or to a formal issue schema

This must be generic across all blocked-plan scenarios, not just attachments.

### 2. Add a dedicated attachment-facts extraction layer

Before the final bridge planner runs:

- extract structured facts from attachments into JSON
- populate `extractedFactHints` or a new typed attachment-facts section
- let the bridge planner consume those normalized facts instead of relying on one-shot multimodal reasoning alone

This is the real root fix for attachment-heavy flows.

### 3. Ensure every LLM backend receives attachments consistently

If `GEMINI_ENDPOINT` mode is supported, it must either:

- forward attachments/media correctly
- or fail explicitly when attachment-dependent prompts are used

Silent media dropping is not acceptable.

### 4. Keep planner/repair output contracts tighter for blocked plans

The planner and repair prompts should explicitly constrain:

- `validation.blockingIssues` shape
- blocked-plan JSON formatting
- attachment-missing diagnostics

This reduces variance, but it is not sufficient by itself without normalization.

## What Should Not Be Done

These would be non-holistic:

- patching only the single attachment prompt that failed
- special-casing only `blockingIssues[0]`
- adding one more ad hoc repair rule for “attachment missing”
- relying only on prompt wording without normalization
- assuming attachment handling is solved just because Vertex sees the binary

## Recommended Implementation Direction

The cleanest root-level direction is:

1. strengthen `ResponseValidator._normalize(...)` so validation issue lists accept richer planner objects and canonicalize them before schema validation
2. add a separate attachment-facts extraction contract, preferably before final bridge planning
3. feed those structured attachment facts into the planner as typed JSON instead of only raw evidence/media
4. ensure custom endpoint mode does not silently lose attachments
5. preserve the current raw/schema fixes while improving the attachment pipeline

## Bottom Line

The last 5 minutes do not show a new raw execution problem.

They show that attachment-aware blocked plans are still missing a proper structured boundary.

The LLM can currently inspect attachments in Vertex mode, but the system does not yet convert that understanding into a deterministic typed JSON layer before bridge planning. That is why attachment-centric requests are still failing at the schema/JSON boundary even when the semantic diagnosis is basically correct.

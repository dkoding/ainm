# RULES

## Purpose

This document is the canonical constraint baseline for this repository.

Its job is to condense the non-negotiable rules from the Tripletex competition docs and the current internal design docs into one place so future planning, task creation, and implementation do not drift.

When creating or updating any future `PLAN*.md` or `TASKS*.md`, this file must be referenced explicitly.

## Source Documents

External competition docs:

- `docs/task-overview.html`
- `docs/task-endpoint.html`
- `docs/task-scoring.html`
- `docs/task-sandbox.html`
- `docs/openapi.json`

Internal design docs:

- `DESC.md`
- `LLM.md`
- `EXAMPLE.md`
- `ANALYSIS.md`
- `API.md`

## Rule 1. The system exists to solve Tripletex tasks, not to chat

The core competition loop is:

- receive one accounting task
- interpret the prompt and optional attachments
- execute the needed Tripletex API calls
- leave Tripletex in the correct final state
- return `{"status":"completed"}`

Implications:

- the system must be execution-oriented
- planning that does not connect to real Tripletex mutations/reads is incomplete
- correctness is judged on the resulting Tripletex state, not on explanations

## Rule 2. `/solve` is the only competition entrypoint

The competition contract requires a single HTTPS `POST /solve` endpoint.

The request format must accept:

- `prompt`
- `files[]`
- `tripletex_credentials.base_url`
- `tripletex_credentials.session_token`

The response contract must be:

- HTTP `200`
- body exactly `{"status":"completed"}`

The endpoint must complete within:

- `300` seconds
- `5` minutes

Implications:

- all internal architecture must ultimately serve this one endpoint
- no design may rely on multi-request human clarification loops during competition execution
- latency and retry policy must respect the hard 5-minute ceiling

## Rule 3. Competition requests may include attachments and multilingual prompts

The docs state that prompts come in one of `7` competition languages and some tasks include PDF or image attachments.

Internal design target:

- the LLM layer should normalize arbitrary-language input into canonical JSON

Minimum guaranteed external coverage:

- Norwegian
- English
- Spanish
- Portuguese
- Nynorsk
- German
- French

Implications:

- prompt-only solutions are insufficient
- attachment handling is not optional
- planning and tasking must treat multilingual normalization as part of the core path, not as an extension

## Rule 4. All Tripletex calls must use the provided proxy credentials

Competition execution must use:

- `tripletex_credentials.base_url`
- Basic Auth username `0`
- Basic Auth password `session_token`

All Tripletex calls in competition must go through the provided `base_url` proxy.

Implications:

- no hardcoded Tripletex base URL in competition logic
- no direct Tripletex endpoint bypass in the execution path
- credentials must stay outside the LLM planning payload except where explicitly reduced to non-secret context

## Rule 5. Correctness is field-by-field, and efficiency matters

The competition verifies results field-by-field against expected values.

Scoring then rewards efficiency for perfect submissions.

Implications:

- correctness comes first
- after correctness, call count and error count matter
- designs that rely on broad scans, repeated trial-and-error mutations, or redundant verification reads are strategically weak
- verification should be minimal and task-specific, not generic “fetch everything”

Derived implementation rule:

- prefer the narrowest correct search
- prefer direct aggregate/read endpoints when they match the user request
- perform at most the minimal verification needed to protect correctness

## Rule 6. The competition account starts fresh every submission

Competition behavior:

- fresh Tripletex account per submission
- starts empty each time
- scored automatically
- accessed via authenticated proxy

Sandbox behavior differs:

- persistent account
- data accumulates over time
- direct API access
- no competition scoring

Implications:

- execution must not depend on historical sandbox data
- planning must assume no pre-existing records unless the current task explicitly creates or references them
- sandbox discoveries are useful for conformance, but sandbox persistence must never leak into competition assumptions

## Rule 7. The raw Tripletex API surface is fully in scope

Per `DESC.md`, every raw operation in `docs/openapi.json` is in scope and callable by exact `operationId`.

The wrapper stack therefore has three execution layers:

1. hand-authored business flows
2. hand-authored friendly command aliases
3. exact raw OpenAPI `operationId` fallback

Implications:

- planning and tasking must never assume the wrapper surface is limited to the hand-authored aliases
- full-surface raw fallback is mandatory
- if a business flow or friendly command does not exist, the system must still be able to execute through exact raw operations

## Rule 8. The stable internal bridge is JSON, not free text

Per `LLM.md`, the intended chain is:

`HUMAN -> LLM -> JSON -> FLOWS/COMMANDS -> Tripletex`

Implications:

- the LLM must normalize the user request into canonical machine-readable JSON
- the router must consume JSON, not reinterpret the original prompt
- future planning must preserve a clean boundary between:
  - human language understanding
  - JSON planning
  - execution

## Rule 9. One-shot LLM planning is the happy path

The current design target is:

- one Gemini call in the normal case
- optional bounded repair only if JSON output is invalid or contract-breaking

Implications:

- prompt composition must be strict and example-driven
- planning docs must prefer deterministic local validation and retrieval over adding extra LLM calls
- task design should optimize for one-shot JSON generation, not conversational back-and-forth

## Rule 10. Planning and task documents must inherit these rules

Any future `PLAN*.md` or `TASKS*.md` must:

- list `RULES.md` in its source/reference section
- stay compatible with the `/solve` endpoint contract
- stay compatible with the scoring model
- stay compatible with the proxy/auth model
- preserve the `HUMAN -> LLM -> JSON -> FLOWS/COMMANDS -> Tripletex` architecture
- preserve full raw `operationId` fallback coverage

Any plan or task list that conflicts with this file must be revised.

## Rule 11. Known conformance gaps are not excuses to avoid implementation

The docs and internal analysis are enough to start implementation of:

- raw wrapper generation
- wrapper/flow structure
- router structure
- LLM JSON planner structure

But some families still require sandbox-confirmed minimal payloads for top-tier performance, especially:

- employee admin/system access
- department/module enablement
- credit-note and correction flows
- attachment-derived bookkeeping
- some invoice and travel-expense payloads

Implications:

- these are implementation-time conformance tasks
- they do not block core architecture work
- plans and task lists should call them out explicitly instead of pretending the OpenAPI alone settles them

## Rule 12. Default engineering posture

When several correct designs are possible, prefer the one that is:

- more deterministic
- lower call count
- lower error count
- less dependent on undocumented defaults
- less dependent on pre-existing data
- easier to validate against the docs

That is the posture most aligned with the competition constraints.

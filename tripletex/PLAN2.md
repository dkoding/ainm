# PLAN2

## Goal

Plan the LLM layer that uses Gemini on GCP to transform `/solve` input into the execution JSON contract defined in `LLM.md`.

The target chain is:

`HUMAN -> Gemini -> JSON -> wrapper/router -> Tripletex`

This plan covers only the LLM portion:

- prompt and attachment understanding
- multilingual normalization
- structured JSON generation
- flow/command selection
- argument extraction and denormalization
- validation and bounded repair

It does not cover raw Tripletex wrapper implementation details except where the LLM must know how to reference flows, commands, and raw `operationId` values.

## Reference Documents

- `RULES.md`
  Canonical operational constraint baseline distilled from the competition docs and internal design docs. This plan must not violate it.
- `LLM.md`
  Source of truth for the JSON contract and extraction behavior.
- `DESC.md`
  Source of truth for:
  - business flows
  - friendly commands
  - raw `operationId` fallback
  - intent routing rules
- `EXAMPLE.md`
  Source of truth for one concrete happy-path execution example and for the intended behavior of the LLM output.

This plan inherits all constraints in `RULES.md`, especially:

- `/solve` endpoint contract
- attachment and multilingual requirements
- proxy/auth rules
- field-by-field correctness and efficiency constraints
- one-shot JSON planning as the happy path
- `HUMAN -> LLM -> JSON -> FLOWS/COMMANDS -> Tripletex`

## Core LLM Objective

The Gemini module must do one job well:

- read the solve request
- understand it in any language
- extract every usable fact from prompt and attachments
- normalize and denormalize the facts
- choose the right flow/command plan
- emit one strict JSON object that matches `tripletex.llm_bridge.v1`

The LLM is not the Tripletex executor.

It is the structured planner that produces the machine-readable bridge consumed by the router and wrapper.

## Universal-Language Input

The system should not implement per-language business logic.

Natural-language understanding is delegated to Gemini.

The stable contract is:

- arbitrary human language input
- one canonical JSON output format

This means the real implementation problem is prompt composition and normalization discipline, not a manual language support matrix.

## Model Strategy

Use the highest-capability Gemini model available in the GCP project, selected by configuration rather than hardcoded in logic.

Recommended model policy:

- one configurable `GEMINI_MODEL` setting
- default it to the highest-capability Gemini model available in the current GCP environment
- do not bake model-specific behavior into business logic

This keeps the implementation stable even when the preferred Gemini model changes later.

## Operating Principle

The LLM layer should be optimized for:

- correctness first
- JSON determinism second
- completeness third
- token efficiency fourth

The main risk is not latency. The main risk is producing an incomplete or incorrect JSON plan.

## Happy-Path Operation Count

The target design should use:

- `1` Gemini call per `/solve` request in the normal case

This matches the design intent already documented in `EXAMPLE.md`.

An optional repair call may be allowed, but only as an exception when:

- the model returns invalid JSON
- the JSON violates the contract
- the JSON references unknown flows/commands/operations

The repair path should be bounded to at most one extra Gemini call.

## One-Shot Prompt Contract

The happy path should be a single Gemini inference.

To make that reliable, the prompt package must be unusually explicit.

It should include:

- the exact JSON contract
- positive examples of valid JSON outputs
- examples of raw `operationId` fallback outputs
- examples of blocked-plan outputs
- anti-pattern warnings such as:
  - no prose outside JSON
  - no invented IDs
  - no omitted required top-level sections
  - no mixing of wrapper names and raw parameter names

The model should be left with as little interpretive freedom as possible about output format.

## End-To-End LLM Pipeline

## Stage 1. Solve request intake

Input to the LLM layer begins with:

- `prompt`
- `files[]`
- request-time environment context
  - `currentDate`
  - `timezone`
  - request metadata

Important rule:

- `tripletex_credentials` should not be forwarded into the LLM prompt except as a minimal boolean fact such as “credentials are present”
- the LLM does not need the raw session token

## Stage 2. Attachment preprocessing

The LLM should not receive opaque base64 blobs.

Before calling Gemini, the system should preprocess attachments into an evidence package:

- file metadata
- extracted text
- OCR text where relevant
- extracted tables where relevant
- content warnings when extraction quality is poor

The LLM prompt should receive:

- source text
- structured extraction hints
- attachment provenance labels

This keeps Gemini focused on reasoning and planning, not raw file decoding.

## Stage 3. Prompt normalization context

The Gemini request should include:

- original prompt
- attachment evidence
- current date
- timezone
- required JSON contract version

The LLM must be instructed to:

- preserve source-language text
- normalize into canonical English field names internally
- resolve relative time expressions
- extract all explicit facts
- derive only safe aliases

## Stage 4. Routing context injection

The LLM needs compact but authoritative knowledge of:

- the business flows from `DESC.md`
- the friendly commands from `DESC.md`
- the raw fallback rule via exact `operationId`

It should not be given raw prose only.

It should be given structured routing context compiled from:

- flow catalog
- command alias catalog
- technical flow-family rules
- raw operation catalog
- conformance policy catalog for known tricky Tripletex families

Before the single Gemini call, the runtime may perform deterministic local candidate retrieval over the full catalog.

That retrieval is not a second LLM step.

Its only purpose is to assemble the smallest correct context slice for the one-shot Gemini call.

## Stage 5. Gemini JSON generation

Gemini should emit exactly one JSON object matching the `LLM.md` contract:

- `contractVersion`
- `requestContext`
- `language`
- `understanding`
- `sources`
- `richData`
- `flatBridge`
- `executionPlan`
- `validation`
- `completion`

No prose should be allowed outside the JSON object.

## Stage 6. Local validation

After Gemini returns, the system should validate:

- valid JSON
- correct contract version
- schema validity
- flow/command/operation references
- argument presence
- internal consistency

The validator is local code, not another LLM step.

## Stage 7. Optional bounded repair

If the response is invalid, the system may perform one bounded repair call to Gemini.

The repair call should include:

- the invalid JSON
- the validation errors
- an instruction to fix only the JSON

The repair call should not re-open the whole planning space.

## Stage 8. Handoff to router

Once validated, the JSON becomes the single source of truth for execution.

The downstream router must consume:

- `executionPlan`
- `flatBridge`
- `richData`
- `validation`

The router must not re-read the original prompt for intent.

## LLM Runtime Architecture

Recommended LLM package responsibilities:

- `prompt_builder`
  builds the full Gemini request package
- `context_catalog`
  provides compact structured catalogs derived from `DESC.md` and `openapi.json`
- `attachment_evidence_builder`
  converts uploaded files into evidence payloads
- `gemini_client`
  calls Vertex AI Gemini
- `response_validator`
  validates the returned JSON locally
- `repair_engine`
  performs the bounded correction call when needed
- `llm_planner`
  orchestrates the whole LLM flow and returns validated JSON

## Structured Output Strategy

The LLM layer should use structured JSON generation, not free-form text prompting.

Preferred strategy:

- use Gemini with native structured output or response schema enforcement if available in the selected GCP environment

Fallback strategy:

- request JSON-only output with explicit schema instructions
- validate locally
- repair once if needed

The schema used for generation should mirror `LLM.md`, not a simplified subset.

## Prompt Design Strategy

The system prompt should be built from stable rules, not ad hoc wording.

It should contain:

- role: “produce the Tripletex bridge JSON”
- output rule: “JSON only”
- truthfulness rules from `LLM.md`
- routing priority from `DESC.md`
- denormalization rules from `LLM.md`
- provenance rules from `LLM.md`
- no-guessing rules
- multilingual rules

The user prompt portion should contain:

- the original prompt
- attachment evidence
- current date and timezone
- the compact catalogs required for routing

## Context Packaging Strategy

The full `DESC.md` and `openapi.json` are too large to pass verbatim every time.

The runtime should therefore use precompiled context packs:

- flow catalog pack
- friendly command catalog pack
- raw operation catalog pack
- parameter vocabulary pack
- technical flow-family routing pack
- conformance policy pack

Each pack should be machine-readable and concise.

Recommended pack contents:

- flow name
- one-line purpose
- key inputs
- likely trigger phrases
- command/operation sequence

For raw operations:

- `operationId`
- method
- path
- domain
- short purpose
- semantic aliases and likely trigger phrases
- anti-triggers or common confusions
- required inputs
- parameter semantics
- safety class
- workflow membership or likely usage family
- technical flow family

For conformance policies:

- known minimal-working payload rules
- sandbox-proven quirks
- preferred verification strategy
- whether one corrected retry is allowed on validation failure

## Multilingual Strategy

Gemini must support multilingual prompts and multilingual attachments.

No manual language support matrix is required for business logic.

The competition's documented `7` languages are the minimum evaluation baseline, not the ceiling for input comprehension.

The LLM must:

- detect primary language
- detect mixed-language content
- preserve source text
- normalize meaning into canonical English
- keep locale-aware number and date parsing

The internal JSON should use:

- English field names
- ISO dates
- ISO language codes
- ISO country/currency codes when possible

## Fact Extraction Strategy

The LLM should extract facts into two simultaneous representations:

### 1. Rich semantic model

Use `richData` for:

- entities
- relations
- scalar facts
- provenance
- confidence
- explicit/derived/inferred labeling

### 2. Flat bridge model

Use `flatBridge` for:

- denormalized convenience fields
- ready-to-bind flow arguments
- ready-to-bind command arguments
- primary entity references

The denormalization rule is critical.

Example:

If the prompt contains `Jason Bourne`, the bridge should emit all reliable variants:

- `customerName`
- `customerFirstName`
- `customerLastName`
- `customerDisplayName`

The same applies to addresses, organization names, invoice numbers, dates, periods, account numbers, and payment references.

## Routing Strategy

The LLM must follow `DESC.md` routing priority exactly:

1. business flow first
2. friendly command alias second
3. raw `operationId` fallback third

This logic must be explicit in the Gemini instructions.

### Business flow routing

Use when the request is a recognizable business task.

Examples:

- create employee
- create invoice
- register payment
- issue credit note
- create travel expense with rows

### Friendly command routing

Use when the request is low-level or clearly maps to one specific known command.

Examples:

- get invoice by id
- list VAT types
- find employee by email

### Raw fallback routing

Use when no business flow or friendly alias is the best fit.

Examples from `DESC.md`:

- salary operations
- timesheet operations
- purchase order operations
- bank reconciliation operations
- inventory operations
- asset operations

## Parameter Binding Strategy

The Gemini output must already contain the arguments needed downstream.

The LLM should emit:

- flow-level arguments in `flatBridge.flowArguments`
- command-level arguments in `flatBridge.commandArguments`
- reusable denormalized facts in `flatBridge.fieldBag`

Binding rules:

- preserve exact raw parameter names where the plan references raw `operationId`
- use friendly wrapper parameter names where the plan references wrapper commands/flows
- duplicate fields when duplication reduces downstream logic

## Date And Time Strategy

Date resolution must be deterministic.

The LLM must use:

- request `currentDate`
- request `timezone`

The LLM must preserve:

- original relative date phrase
- normalized date or date range

Examples:

- `today`
- `this month`
- `in February`
- `last quarter`

The timesheet example in `EXAMPLE.md` should be a mandatory acceptance case.

## Attachment Strategy

Attachment handling should be explicit because many tasks rely on PDFs and scanned documents.

The LLM should receive attachment evidence in a structured form:

- attachment ID
- filename
- MIME type
- extracted text
- OCR text
- extracted tables
- confidence notes

The LLM must merge prompt facts and attachment facts into one JSON result.

## Cross-Source Conflict Resolution

The LLM layer must define how conflicts are handled when:

- prompt text says one thing
- OCR says another
- extracted tables say another
- retrieved Tripletex facts disagree with attachment-derived facts

The planner should carry:

- provenance
- confidence
- conflict notes
- the rule used to pick the execution candidate

Low-confidence or contradictory evidence should bias toward:

- blocked execution
- safer read-only steps
- or conservative search-first plans

## Safety And Truthfulness Rules

Gemini must be instructed to:

- never invent resource IDs
- never invent dates not grounded in input or the request anchor
- never invent amounts
- never invent customer, supplier, employee, or invoice identifiers
- mark ambiguity explicitly
- list missing required data explicitly
- mark `isExecutable = false` when the plan is blocked

## Validation Strategy

Local validators must check:

- JSON syntax
- schema shape
- legal `contractVersion`
- legal flow names from `DESC.md`
- legal command aliases from `DESC.md`
- legal raw `operationId` values from the generated OpenAPI catalog
- argument presence for referenced steps
- no contradictory bindings

Validation should be deterministic and machine-enforced.

## Evaluation Strategy

The LLM module should be evaluated on:

- JSON validity rate
- contract compliance rate
- routing accuracy
- parameter extraction accuracy
- denormalization completeness
- multilingual accuracy
- attachment extraction accuracy
- one-call success rate

The first canonical test case should be the exact timesheet scenario in `EXAMPLE.md`.

The documented competition languages should be used as the minimum benchmark set.

Separate stress cases should still probe arbitrary-language, mixed-language, and noisy-language inputs, because the design target is universal normalization into JSON.

Additional evaluation sets should cover:

- employee creation
- customer create/update
- invoice creation
- invoice payment
- credit note
- travel expense with rows
- voucher reversal
- supplier invoice payment
- raw fallback domains such as salary, timesheet, inventory, bank, and year-end

## Observability Strategy

The LLM layer should log structured metadata, not prompt secrets.

Recommended logging fields:

- request ID
- model name
- prompt language
- attachment count
- output validity
- repair used or not
- selected flow count
- selected command count
- raw fallback used or not
- latency

Do not log:

- session tokens
- raw bearer secrets
- full attachment contents by default

## Failure Modes To Plan For

### 1. Invalid JSON

Mitigation:

- local validation
- one bounded repair call

### 2. Wrong routing

Mitigation:

- strong catalog context
- routing tests from `DESC.md`

### 3. Missing denormalized fields

Mitigation:

- field-family extraction rules
- evaluation cases that verify duplication behavior

### 4. Hallucinated IDs or parameters

Mitigation:

- no-guessing instructions
- validator checks
- blocked-plan behavior

### 5. Oversized prompt context

Mitigation:

- precompiled compact catalogs
- domain-focused context packs

### 6. OpenAPI-correct but Tripletex-invalid planning

Mitigation:

- conformance policy catalog for sandbox-sensitive families
- one corrected retry only when validation errors are precise and safe to use
- minimal verification checklists by flow family

## Recommended Delivery Order

Implement the LLM portion in this order:

1. define the internal JSON schema from `LLM.md`
2. compile flow/command/operation/conformance catalogs from `DESC.md` and `openapi.json`
3. define attachment evidence and conflict-resolution models
4. design the one-shot Gemini prompt template and structured output contract
5. add positive and negative JSON examples to the prompt package
6. implement deterministic local candidate retrieval
7. implement local validators
8. implement one-call happy path
9. implement bounded repair path
10. add multilingual and attachment-heavy evaluation sets

## Definition Of Done

The LLM plan is complete when all of the following are true:

- Gemini can turn a `/solve` request into `tripletex.llm_bridge.v1`
- the normal case uses one Gemini call
- the output matches `LLM.md`
- routing follows `DESC.md`
- the timesheet case in `EXAMPLE.md` is reproduced exactly
- the output is ready for the router without reparsing free text

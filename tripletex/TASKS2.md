# TASKS2

## Objective

Define the concrete work to build the Gemini-based LLM module that converts `/solve` input into the JSON contract described in `LLM.md`, routed according to `DESC.md`, and behaving like the example in `EXAMPLE.md`.

All tasks below are planning tasks only. Status starts at `pending`.

## Constraint Baseline

This task list inherits `RULES.md`.

Any future additions or edits to this file must remain compatible with:

- the `/solve` endpoint contract
- attachment and multilingual competition requirements
- proxy-only Tripletex access with Basic Auth `0:session_token`
- field-by-field correctness and efficiency constraints
- one-shot JSON planning as the normal path
- the `HUMAN -> LLM -> JSON -> FLOWS/COMMANDS -> Tripletex` execution chain

## Phase 1. LLM architecture and runtime boundary

- `L1` `pending`
  Define the LLM module boundary inside the application:
  - input to the LLM planner
  - output from the LLM planner
  - separation from the router
  - separation from Tripletex credentials

- `L2` `pending`
  Define the Gemini runtime policy:
  - configurable `GEMINI_MODEL`
  - use highest-capability Gemini model available in the GCP project
  - no hardcoded business logic tied to a specific model version
  - no manual language support matrix for business logic

- `L3` `pending`
  Decide where the LLM module lives in the package structure.
  Recommended components:
  - `prompt_builder`
  - `context_catalog`
  - `attachment_evidence_builder`
  - `gemini_client`
  - `response_validator`
  - `repair_engine`
  - `llm_planner`

- `L4` `pending`
  Define the boundary between:
  - raw `/solve` request
  - preprocessed evidence package
  - Gemini request payload
  - validated bridge JSON

## Phase 2. JSON contract modeling

- `L5` `pending`
  Define the internal schema for `tripletex.llm_bridge.v1` directly from `LLM.md`.

- `L6` `pending`
  Model all top-level sections:
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

- `L7` `pending`
  Define the universal entity envelope for `richData.entities`.

- `L8` `pending`
  Define the denormalized `flatBridge` structure:
  - `primaryEntityRefs`
  - `fieldBag`
  - `byEntityId`
  - `flowArguments`
  - `commandArguments`

- `L9` `pending`
  Define execution-plan structures for:
  - selected flows
  - selected commands
  - raw `operationId` fallback steps
  - `stepOrder`

## Phase 3. Catalog preparation for Gemini context

- `L10` `pending`
  Compile the business flow catalog from `DESC.md`.

- `L11` `pending`
  Compile the friendly command catalog from `DESC.md`.

- `L12` `pending`
  Compile the raw operation catalog from `openapi.json`.
  Include:
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
  - workflow membership
  - technical flow family

- `L13` `pending`
  Compile the routing rules from `DESC.md` into a machine-readable context pack.

- `L14` `pending`
  Compile the parameter vocabulary, reusable payload families, and conformance policy packs from `DESC.md`, `API.md`, and `ANALYSIS.md`.

- `L15` `pending`
  Define deterministic local candidate retrieval and ranking before the single Gemini call, including how much catalog context is injected versus retrieved dynamically.

## Phase 4. Attachment evidence preparation

- `L16` `pending`
  Define the attachment evidence schema passed to Gemini.

- `L17` `pending`
  Define preprocessing outputs for:
  - extracted text
  - OCR text
  - extracted tables
  - extraction confidence

- `L18` `pending`
  Define provenance labels for attachment-derived facts.

- `L19` `pending`
  Define how prompt facts and attachment facts are merged before Gemini planning, including conflict resolution and confidence thresholds.

## Phase 5. Prompt and instruction design

- `L20` `pending`
  Write the stable system instruction template for Gemini.

- `L21` `pending`
  Encode the `LLM.md` rules into the instruction template:
  - JSON only
  - no guessing
  - multilingual normalization
  - denormalization rules
  - explicit/derived/inferred labeling
  - no manual language-specific branching
  - no prose outside the JSON object

- `L22` `pending`
  Encode the `DESC.md` routing priority into the instruction template:
  - business flow first
  - friendly command second
  - raw `operationId` fallback third

- `L23` `pending`
  Encode `EXAMPLE.md` as a canonical behavior example for the planner, and add additional positive/negative few-shot examples:
  - valid wrapper-flow example
  - valid raw-`operationId` fallback example
  - valid blocked-plan example
  - invalid-output anti-example

- `L24` `pending`
  Define the solve-time prompt template that injects:
  - original prompt
  - attachment evidence
  - current date
  - timezone
  - the selected compact catalog slice
  - explicit output examples

- `L25` `pending`
  Decide whether the Gemini call uses:
  - native structured output
  - explicit JSON schema
  - JSON-only prompting plus local validation

## Phase 6. Universal-language normalization strategy

- `L26` `pending`
  Define language detection fields and behavior without introducing a manual language support matrix.

- `L27` `pending`
  Define canonical internal language behavior for field names and planning.

- `L28` `pending`
  Define normalization rules for:
  - dates
  - date ranges
  - amounts
  - currencies
  - percentages
  - organization numbers
  - invoice numbers
  - KID and payment references
  - mixed-language text
  - OCR-noisy text
  - locale-specific separators and formatting

- `L29` `pending`
  Define name-splitting rules for persons and organizations.

- `L30` `pending`
  Define derived-field duplication rules such as:
  - `customerName`
  - `customerFirstName`
  - `customerLastName`
  - `customerDisplayName`

## Phase 7. Flow and command planning behavior

- `L31` `pending`
  Define the business-flow selection algorithm used by Gemini.

- `L32` `pending`
  Define the friendly-command selection algorithm used by Gemini.

- `L33` `pending`
  Define the raw `operationId` fallback selection algorithm used by Gemini.

- `L34` `pending`
  Define how Gemini chooses technical flow families for raw fallback cases.

- `L35` `pending`
  Define how Gemini binds flow inputs versus command inputs in the JSON.

- `L36` `pending`
  Define how Gemini expresses assumptions, ambiguities, missing data, blocked execution, and out-of-scope or not-representable requests.

## Phase 8. Validation and repair

- `L37` `pending`
  Define local JSON validation rules for the bridge contract.

- `L38` `pending`
  Define local validation rules for:
  - flow existence
  - command existence
  - raw `operationId` existence
  - argument presence
  - step ordering

- `L39` `pending`
  Define the criteria for a valid one-call success.

- `L40` `pending`
  Define when a bounded repair call is allowed.

- `L41` `pending`
  Define the repair prompt contract:
  - original invalid JSON
  - validator errors
  - “fix JSON only” rule

- `L42` `pending`
  Define the hard stop rules when repair still fails.

## Phase 9. Security and data-handling rules

- `L43` `pending`
  Define which solve-time fields are allowed into the Gemini prompt.

- `L44` `pending`
  Define which secrets are excluded from the Gemini prompt.

- `L45` `pending`
  Define logging and redaction policy for:
  - prompt text
  - attachment evidence
  - credentials
  - model responses

- `L46` `pending`
  Define data retention policy for intermediate evidence and LLM outputs.

## Phase 10. Evaluation and acceptance tests

- `L47` `pending`
  Create the first canonical evaluation case from `EXAMPLE.md`.

- `L48` `pending`
  Create multilingual evaluation cases across the documented competition languages plus arbitrary-language and mixed-language stress cases.

- `L49` `pending`
  Create attachment-heavy evaluation cases using PDFs and mixed evidence.

- `L50` `pending`
  Create routing evaluation cases for:
  - business flows
  - friendly commands
  - raw fallback operations

- `L51` `pending`
  Create extraction evaluation cases for:
  - names
  - dates
  - money
  - identifiers
  - selectors
  - references

- `L52` `pending`
  Define quality metrics:
  - JSON validity rate
  - one-call success rate
  - routing accuracy
  - extraction completeness
  - denormalization completeness
  - hallucination rate

## Phase 11. Integration boundary with the router

- `L53` `pending`
  Define the exact handoff object from Gemini planner to router.

- `L54` `pending`
  Ensure the router never needs to reinterpret free text if the LLM succeeds.

- `L55` `pending`
  Define how blocked plans are surfaced downstream.

- `L56` `pending`
  Define how the router consumes:
  - `executionPlan`
  - `flatBridge`
  - `richData`
  - `validation`

## Phase 12. Release gates

- `L57` `pending`
  Define a validation gate that fails when Gemini output no longer matches `LLM.md`.

- `L58` `pending`
  Define a routing gate that fails when outputs drift from `DESC.md`.

- `L59` `pending`
  Define an example gate that fails when the timesheet case in `EXAMPLE.md` is not reproduced.

- `L60` `pending`
  Define the minimum documentation needed to keep the Gemini planning layer maintainable.

## Recommended Implementation Order

Execute tasks in this sequence:

1. `L1` to `L9`
2. `L10` to `L19`
3. `L20` to `L25`
4. `L26` to `L36`
5. `L37` to `L42`
6. `L43` to `L46`
7. `L47` to `L52`
8. `L53` to `L60`

## Exit Criteria

This task set is complete when:

- Gemini can produce `tripletex.llm_bridge.v1` from a `/solve` request
- the normal case succeeds in one Gemini call
- the output follows `DESC.md` routing rules
- the output matches the shape in `LLM.md`
- the example behavior in `EXAMPLE.md` is reproducible end-to-end

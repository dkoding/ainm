# LASTTRY

## Goal

Plan the next `v3` LLM-contract fix so Gemini keeps structured output, Vertex stops rejecting the schema, and the runtime remains the authoritative validator.

This plan is specifically for the live failure seen on Cloud Run revision `tripletex-agent-00066-6ws`:

- Vertex rejects the current `responseJsonSchema` with HTTP `400 INVALID_ARGUMENT`
- error message: the schema "produces a constraint that has too many states for serving"

The target outcome is:

- keep Gemini on structured JSON output
- stop sending overly stateful schemas to Vertex
- add a bounded fallback when Vertex rejects the primary schema
- preserve strict local validation against the real Tripletex bridge and wrapper contracts

## Source Of Truth

- `RULES.md`
  Canonical repository constraint baseline. This plan must not violate it.
- `DESC.md`
  Source of truth for the flow-first execution model, wrapper contracts, selector families, and payload families.
- `LLM.md`
  Source of truth for the `HUMAN -> LLM -> JSON -> FLOWS/COMMANDS -> Tripletex` bridge.
- `EXAMPLE.md`
  Source of truth for one-shot structured planning behavior.
- `ANALYSIS.md`
  Architectural background for efficient, workflow-aware execution.
- `API.md`
  Competition API contract, proxy/auth behavior, and Tripletex response/query patterns.
- `PLAN1.md`, `TASKS1.md`
  Earlier execution-stack planning baseline.
- `PLAN2.md`, `TASKS2.md`
  Earlier Gemini planning baseline, including the decision point around native structured output vs schema prompting vs local validation.
- `docs/openapi.json`
  Authoritative raw API surface. This plan does not change its role; it changes how much structure is enforced in Gemini-serving schemas.

This plan inherits all non-negotiable constraints from `RULES.md`, especially:

- `/solve` must finish within `300` seconds
- the stable bridge remains JSON
- the router consumes JSON, not raw prompt text
- full raw `operationId` fallback coverage must remain possible
- credentials stay out of the LLM payload except for reduced non-secret context

## Problem Statement

The current `v3` planner drifted through three boundary failures:

1. prompt-only JSON was too weak
   - Gemini could emit malformed or semantically illegal bridge objects
2. validator assumptions were too strong
   - malformed sections could still crash normalization
3. the new `responseJsonSchema` is too strong in the wrong place
   - Vertex rejects it before generation because the schema is too complex for serving

The latest live failure is category `3`.

This means the current architecture is over-constraining Gemini at the serving boundary while still relying on runtime validation for the real business contract anyway.

## Root Cause

The core mistake is treating Vertex `responseJsonSchema` as if it should encode most of the bridge contract.

That is the wrong level of enforcement.

The real bridge contract has multiple layers:

1. serving-time generation shape
   - "return one JSON object with these top-level sections and primitive types"
2. planner-level semantic admissibility
   - "use only legal flow names, legal command names, legal raw operationIds, legal input containers"
3. runtime contract validation
   - "the JSON must satisfy the actual Pydantic bridge models, wrapper contracts, selector families, payload families, and raw OpenAPI bindings"

The current implementation blurred layers `1` and `2`.

As a result:

- Vertex sees a relatively detailed schema and rejects it as too stateful
- even if Vertex accepted it, runtime would still need to perform the real admissibility checks
- the serving schema is carrying detail that belongs in local validation

## Design Principle

Use a layered contract, not one giant schema.

The correct split is:

- Gemini serving schema:
  compact structural contract only
- Gemini prompt and candidate context:
  route legality, route hints, OpenAPI slices, wrapper semantics
- local runtime validator:
  full authority on the real bridge and execution contract

## What Changes

### 1. Compact structural schemas for Gemini

The primary Gemini schema should enforce only:

- top-level object shape
- required top-level sections
- required major container presence where useful
- primitive types for obvious fields
- array-vs-object distinctions for a few critical sections

The primary Gemini schema should not try to enforce:

- deep nested bridge field catalogs
- detailed wrapper payload shapes
- exhaustive enum-like constraints
- fine-grained field legality for flows, commands, or raw operations

Those remain runtime concerns.

### 2. Fallback schema per model task

Each Gemini task should define:

- `responseJsonSchema`
  primary compact structural schema
- `fallbackResponseJsonSchema`
  even smaller structural schema used only when Vertex rejects the primary schema

The fallback schema should be strictly smaller, not just cosmetically different.

### 3. Schema-aware retry in the Gemini client

For Vertex generation only:

- first request uses the primary schema
- if Vertex returns the specific schema-complexity `400 INVALID_ARGUMENT`
- retry once with the fallback schema

This retry is:

- local
- bounded to one extra attempt
- specific to the known serving error

It is not a general retry loop.

### 4. Runtime remains the authority

Passing Gemini schema validation must never be treated as proof of correctness.

The runtime still must:

- normalize malformed sections defensively
- validate bridge structure with the local contract models
- validate flow and command names against the retrieved contract
- validate raw operation inputs against raw metadata and OpenAPI-derived shapes
- reject illegal payload field names and illegal selector shapes

### 5. Reduce what Gemini must invent

Because the schema becomes less detailed, the prompt/context contract must remain strong:

- stronger candidate contracts
- narrower spec slices
- clearer route hints
- fewer legal options per request where possible

This keeps planner quality high without moving detailed legality into the serving schema.

## Non-Goals

This plan does not attempt to:

- attach the entire `openapi.json` to every Gemini request
- encode the full bridge contract into Vertex schema serving constraints
- move detailed business-language heuristics into Python retrieval code
- replace runtime validation with Gemini schema validation
- redesign the whole `v3` planner stack again

## Target Architecture

The intended boundary after this work is:

`/solve -> attachments -> intent extraction -> candidate retrieval -> Gemini with compact schema -> local validation -> router/executor`

With Gemini serving subcontracts:

- attachment extraction: small schema + smaller fallback
- intent extraction: small schema + smaller fallback
- bridge planning: medium structural schema + smaller fallback
- repair: same bridge structural schema strategy + smaller fallback

The critical difference from the current build is that "medium structural schema" no longer tries to express the detailed bridge legality model.

## Implementation Plan

## Phase 1. Define compact and fallback schemas

Objective:

- replace the current overly detailed Gemini schemas with layered structural schemas

Work:

- audit `v3/app/llm/response_schemas.py`
- define, per task:
  - primary compact schema
  - fallback smaller schema
- ensure the bridge schema only enforces:
  - object root
  - required top-level sections
  - object-vs-array shape for `executionPlan` and `validation`
  - primitive types for a few critical fields like `contractVersion` and `validation.isExecutable`

Success criteria:

- the primary bridge schema is materially smaller and less stateful than the current one
- the fallback bridge schema is materially smaller than the new primary schema

## Phase 2. Thread fallback schemas through prompt packages

Objective:

- make every Gemini call site capable of providing a primary schema and a fallback schema

Work:

- update prompt/package builders and extractors to emit:
  - `responseJsonSchema`
  - `fallbackResponseJsonSchema`
- apply this to:
  - attachment fact extraction
  - intent extraction
  - bridge planning
  - repair

Success criteria:

- every structured Gemini call can degrade to a smaller schema without changing the semantic task

## Phase 3. Add schema-complexity fallback in `GeminiClient`

Objective:

- recover automatically from the exact Vertex serving failure already seen live

Work:

- update `v3/app/llm/gemini_client.py`
- detect the specific Vertex failure shape:
  - HTTP `400`
  - `INVALID_ARGUMENT`
  - schema too many states / too complex wording in the body
- retry once with `fallbackResponseJsonSchema`
- keep existing model fallback behavior separate:
  - schema fallback happens first within the same model request
  - model/location fallback remains for broader primary-model failure handling if still needed

Success criteria:

- the client does not immediately fail the request on the known schema-state error
- the retry is bounded and observable in logs

## Phase 4. Keep validator strict and defensive

Objective:

- ensure a smaller Gemini schema does not reopen earlier runtime crashes or silent contract drift

Work:

- audit `v3/app/llm/response_validator.py`
- keep defensive normalization for:
  - non-object top-level sections
  - malformed issue lists
  - prefixed flow/command keys
  - string-vs-object drift in `language`, `understanding`, and related sections
- confirm the validator still rejects semantically illegal routes and payloads even if the Gemini schema is smaller

Success criteria:

- smaller serving schemas do not reduce runtime strictness
- malformed planner output degrades into recoverable validation errors, not `500`s

## Phase 5. Tighten prompt-side grounding where schema detail is reduced

Objective:

- compensate for reduced serving-schema strictness with better route grounding

Work:

- review `v3/app/llm/prompt_builder.py`
- keep strong instructions around:
  - candidate allow-lists
  - wrapper-vs-raw field-name distinction
  - selector family legality
  - payload family legality
  - routing priority
  - blocked-plan contradiction handling
- keep exact OpenAPI slices narrow and task-relevant

Success criteria:

- planner quality stays high without pushing detailed legality into Vertex schemas

## Phase 6. Test the failure boundary directly

Objective:

- prove the fix targets the real live failure, not just local happy paths

Work:

- add unit tests for:
  - schema package generation with primary and fallback schemas
  - Gemini client retry on schema-complexity `400`
  - no retry on unrelated `400`s
  - validator handling after fallback-generated outputs
- keep existing planner and validator regressions passing

Success criteria:

- the schema-complexity failure is covered by explicit tests
- unrelated errors do not silently get masked as schema fallback cases

## Implementation Order

Recommended execution order:

1. simplify `response_schemas.py`
2. wire `fallbackResponseJsonSchema` through all prompt producers
3. implement schema-aware retry in `gemini_client.py`
4. extend tests for Gemini fallback behavior
5. re-run targeted `v3` test suite
6. only then consider redeploy

## File-Level Change Plan

Primary files:

- `v3/app/llm/response_schemas.py`
  - define compact primary and smaller fallback schemas
- `v3/app/llm/gemini_client.py`
  - implement Vertex schema-complexity retry logic
- `v3/app/llm/attachment_fact_extractor.py`
  - pass primary and fallback schemas
- `v3/app/llm/intent_extractor.py`
  - pass primary and fallback schemas
- `v3/app/llm/prompt_builder.py`
  - pass primary and fallback bridge schemas
- `v3/app/llm/repair_engine.py`
  - pass primary and fallback repair schemas
- `v3/app/llm/response_validator.py`
  - confirm defensive normalization remains intact

Primary tests:

- `v3/tests/test_gemini_client.py`
- `v3/tests/test_intent_extractor.py`
- `v3/tests/test_attachment_fact_extractor.py`
- `v3/tests/test_llm_planner.py`
- `v3/tests/test_response_validator.py`

## Validation Plan

Minimum validation for the implementation phase:

- `python3 -m compileall v3/app`
- `bash -n v3/deploy_cloud_run.sh`
- targeted `v3` unit tests covering:
  - Gemini client schema fallback
  - prompt/extractor schema wiring
  - bridge planner regression coverage
  - response validator hardening

If deployed later, live validation must specifically include:

- a request path that previously triggered the schema-state `400`
- confirmation that the request no longer fails at the Vertex serving boundary
- confirmation that any remaining planner failures are surfaced as validation/blocked-plan issues, not Vertex schema errors or `500`s

## Risks

- making the primary schema too small could increase planner drift
- masking unrelated Vertex `400`s as schema complexity errors would hide real integration bugs
- fallback retries consume extra latency inside the `300` second budget

Mitigations:

- keep prompt-side route grounding strong
- detect only the known schema-complexity error signature
- allow only one schema fallback retry
- keep runtime validation strict

## Completion Criteria

This plan is complete when the implementation can satisfy all of these:

- Gemini still uses structured output
- Vertex no longer rejects the primary or fallback schema for normal planner traffic
- the runtime, not Gemini serving schema, remains the final contract authority
- malformed model output produces validation/repair behavior, not uncaught server exceptions
- the live failure mode shifts away from schema-serving rejection and back to normal planner/runtime correctness work

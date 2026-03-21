# PLAN1

## Goal

Build the Tripletex execution stack in three ordered layers:

1. generate the full raw Tripletex API wrapper from `docs/openapi.json`
2. build the thin human-facing wrapper layer from `DESC.md` and call that layer `wrapper`
3. build the router that reads the LLM JSON contract from `LLM.md` and delegates to the correct flows and commands with the correct parameters

This plan is implementation planning only. No application logic is introduced here.

## Source Of Truth

- `RULES.md`
  Canonical operational constraint baseline distilled from the competition docs and internal design docs. This plan must not violate it.
- `docs/openapi.json`
  Raw API source of truth for all `546` paths, `800` operations, `56` top-level domains, `2167` schemas, all path/query/body parameters, and all exact `operationId` values.
- `DESC.md`
  Source of truth for the thin wrapper contract:
  - `78` friendly command aliases
  - `21` business flows
  - technical flow-family rules
  - selector/reference/payload normalization rules
- `LLM.md`
  Source of truth for the execution JSON contract and the handoff from `HUMAN -> LLM -> JSON -> FLOWS/COMMANDS`.
- `EXAMPLE.md`
  Source of truth for one concrete routed example and for the intended execution semantics of the JSON plan.

This plan inherits all constraints in `RULES.md`, especially:

- `/solve` endpoint contract
- proxy/auth rules
- field-by-field correctness and efficiency constraints
- fresh-account assumptions
- full raw `operationId` fallback coverage
- `HUMAN -> LLM -> JSON -> FLOWS/COMMANDS -> Tripletex`

## Key Facts That Shape The Plan

- the raw layer must cover all `800` operations
- `operationId` values are unique in the current spec, which makes them safe canonical raw command IDs
- `277` operations have request bodies
- `25` operations use multipart request bodies
- there are `365` path parameters and `1839` query parameters in the spec
- there are `69` action-style endpoints with `:` markers in the path
- OpenAPI exactness is necessary but not sufficient for all scoring-critical Tripletex behaviors
- the raw generated layer and the hand-authored wrapper layer must be kept separate
- the router must consume JSON only; it must not reinterpret raw human language

## Architectural Direction

The future codebase should stay thin at the HTTP edge and move almost all logic into internal packages under `app/`.

Recommended implementation layout:

- `app/main.py`
  HTTP entrypoint only. Receives `/solve`, validates auth, forwards to router entrypoint.
- `app/generated/`
  Generated raw Tripletex wrapper from OpenAPI.
- `app/raw/`
  Shared transport, auth, request execution, retries, response normalization, and runtime registry helpers used by generated code.
- `app/wrapper/`
  Thin hand-authored wrapper based on `DESC.md`.
- `app/router/`
  JSON contract parsing, validation, parameter binding, flow/command dispatch, and execution orchestration.
- `app/contracts/`
  Internal typed models for solve request, LLM JSON contract, execution result, and error/result envelopes.
- `app/tools/` or `scripts/`
  Code generation entrypoints and validation tools.

## Separation Of Responsibilities

### 1. Generated raw layer

Purpose:

- exact OpenAPI coverage
- exact `operationId` addressing
- exact parameter names and required flags
- no business normalization
- no prompt semantics

The raw layer must:

- expose one callable raw command per OpenAPI operation
- preserve raw path, query, body, and multipart behavior
- preserve exact `operationId`
- preserve response shapes as returned by Tripletex
- carry enough metadata for registries, router fallback, and auditing
- carry enough semantic and safety metadata for deterministic candidate retrieval and routing

The raw layer must not:

- rename raw parameter names for convenience
- decide business flows
- interpret LLM intent
- contain hand-authored prompt-specific logic

### 2. Thin `wrapper` layer

Purpose:

- implement the canonical hand-authored contract in `DESC.md`
- translate friendly command/flow inputs into raw command inputs
- hold selector resolution and business normalization rules

The `wrapper` layer must:

- implement the `78` friendly commands
- implement the `21` business flows
- implement technical flow-family metadata for the full surface
- adapt `date_window`, selectors, references, and reusable business payloads into raw API calls

The `wrapper` layer must not:

- depend on free-text prompts
- duplicate the full OpenAPI parameter model manually
- become a second generated SDK

### 3. Router layer

Purpose:

- read the LLM execution JSON
- validate it against `LLM.md`
- map `selectedFlows`, `selectedCommands`, and raw `operationId` fallbacks to the right execution units
- bind parameters from the JSON to wrapper and raw operations

The router must:

- trust the JSON plan, not the original prompt
- validate contract version and plan structure
- honor `stepOrder`
- resolve whether each step is:
  - business flow
  - friendly command alias
  - raw `operationId`
- bind parameters from:
  - `flatBridge.flowArguments`
  - `flatBridge.commandArguments`
  - `flatBridge.fieldBag`
  - selected entity references
- stop on blocked or invalid plans

The router must not:

- perform its own free-text intent classification
- invent missing parameters
- bypass wrapper rules for business flows

## Execution Model

The target execution chain should become:

1. HTTP layer receives `/solve`
2. LLM layer produces the JSON contract
3. router validates the JSON contract
4. router resolves execution units in order
5. wrapper flows/commands adapt friendly inputs where applicable
6. raw generated commands execute against Tripletex
7. results are normalized into execution output

## Phase Plan

## Phase 1. OpenAPI ingestion and codegen design

Objective:

- define exactly what the generator emits and what stays hand-authored

Outputs:

- normalized OpenAPI loader
- operation catalog design
- schema emission strategy
- generated file layout
- regeneration strategy
- conformance policy catalog design for sandbox-sensitive families

Required decisions:

- generated Python source vs generated JSON metadata plus generic executor
- one file per domain vs one global catalog plus domain facades
- typed models vs permissive dict payloads in the raw layer
- how multipart operations are represented
- how exact parameter names are preserved while still supporting runtime validation

Recommended direction:

- generate a machine-readable operation catalog plus Python call facades
- keep one shared runtime executor in `app/raw/`
- keep generated code deterministic and reproducible
- treat generated artifacts as disposable outputs of the generator, never as hand-edited files
- enrich the generated catalog with semantic routing metadata and conformance policy keys

## Phase 2. Generate the raw Tripletex wrapper

Objective:

- create the exact OpenAPI-backed execution layer

Outputs:

- one raw callable per `operationId`
- operation metadata registry
- schema/type artifacts required for request validation and response handling
- technical flow-family tags derived from path and method semantics
- semantic routing metadata for raw operations
- optional conformance policy keys for known tricky families

Required capabilities:

- path parameter interpolation
- query parameter encoding
- JSON body submission
- multipart body submission
- binary/document endpoints where applicable
- Basic Auth with username `0` and `session_token`
- base URL coming only from solve-time credentials

Acceptance target:

- every operation in `docs/openapi.json` is callable through its exact `operationId`
- missing/invalid parameters fail before or at the raw call boundary with precise errors

## Phase 3. Build the thin `wrapper`

Objective:

- implement the human-facing wrapper contract from `DESC.md`

Outputs:

- command alias registry
- flow registry
- selector resolution helpers
- reference resolution helpers
- business payload adapters
- shared verification helpers
- conformance policy catalog for known sandbox-sensitive flows
- task-family-specific verification checklists

Required capabilities:

- all `78` friendly commands
- all `21` business flows
- mapping from friendly alias to raw operation(s)
- mapping from flow to ordered command steps
- consistent handling of:
  - `fields`
  - `date_window`
  - selectors
  - references
  - line items
  - payment specs
  - posting lines
  - travel details

Acceptance target:

- every command and flow in `DESC.md` has a concrete executable implementation
- wrapper commands remain thin and deterministic
- known sandbox-sensitive families have explicit conformance policies instead of raw OpenAPI-only assumptions

## Phase 4. Build the router

Objective:

- turn the LLM JSON into actual wrapper/raw execution

Outputs:

- JSON contract validator
- execution-plan resolver
- parameter binder
- dispatcher
- execution result model

Required capabilities:

- validate `contractVersion`
- validate selected flow/command names
- validate raw `operationId` existence
- bind command inputs from the JSON without reparsing text
- support both:
  - business-flow-first execution
  - raw-command fallback execution
- execute `stepOrder`
- surface blocked plans and missing required data explicitly

Acceptance target:

- the JSON in `EXAMPLE.md` can be executed without custom-case code
- router behavior is deterministic and traceable

## Phase 5. Verification and coverage

Objective:

- prove the generated and hand-authored layers match the docs

Outputs:

- coverage audit against OpenAPI
- coverage audit against `DESC.md`
- JSON contract routing tests against `LLM.md`
- end-to-end example tests from `EXAMPLE.md`
- conformance tests for sandbox-sensitive families

Acceptance target:

- `800` raw operations covered
- `78` friendly commands covered
- `21` business flows covered
- technical flow-family assignment present for the full surface

## Generator Strategy

The generator should be treated as a first-class product, not a one-off script.

Requirements:

- deterministic output
- idempotent regeneration
- clear separation of generated vs hand-authored code
- stable naming from exact `operationId`
- stable metadata for:
  - domain
  - path
  - method
  - purpose
  - semantic aliases
  - anti-triggers
  - path params
  - query params
  - parameter semantics
  - body schema
  - response schema
  - safety class
  - action markers
  - technical flow family
  - conformance policy key

Recommended generated artifacts:

- `operation_catalog`
- `schema_catalog`
- domain-level raw facades
- operation-to-family mapping
- operation-to-parameter metadata
- operation semantic metadata
- conformance policy catalog

## Router Binding Strategy

The router should bind in this order:

1. explicit `flatBridge.flowArguments[flow_name]`
2. explicit `flatBridge.commandArguments[command_name_or_operationId]`
3. explicit `flatBridge.fieldBag`
4. entity-linked denormalized values
5. defaulting rules that are explicitly documented in OpenAPI or `DESC.md`

The router should never bind from:

- the raw human prompt
- guessed values
- undocumented defaults

## Bounded Retry And Verification Strategy

Execution should follow a conservative recovery model:

- one well-formed primary attempt
- at most one corrected retry when Tripletex returns a precise validation error that can be safely mapped

Verification should be specific, not generic.

The wrapper and router should use task-family-specific checklists so verification remains low-cost and scoring-friendly.

## Major Risks

### 1. Generated/raw mismatch

Risk:

- generator output drifts from `openapi.json`

Mitigation:

- generate metadata directly from spec
- build regeneration checks

### 2. Friendly wrapper drift

Risk:

- hand-authored aliases and flows drift from `DESC.md`

Mitigation:

- maintain a wrapper catalog with explicit coverage mapping back to `DESC.md`

### 3. JSON/router mismatch

Risk:

- LLM JSON shape and router expectations diverge

Mitigation:

- derive router contract models directly from `LLM.md`
- test the exact example in `EXAMPLE.md`

### 4. Over-normalization

Risk:

- wrapper loses raw parameter fidelity needed for uncommon operations

Mitigation:

- keep raw generated layer exact
- use wrapper only as a thin adapter layer

### 5. OpenAPI-correct but runtime-invalid payloads

Risk:

- raw generation succeeds but minimal working payloads differ in sandbox-sensitive families

Mitigation:

- conformance policy catalog
- sandbox-sensitive flow tests
- one corrected retry policy based on actual validation errors

## Recommended Delivery Order

The work should be executed in this exact order:

1. generator and raw operation catalog
2. raw execution runtime
3. raw operation coverage validation
4. thin `wrapper` command aliases
5. thin `wrapper` business flows
6. router contract validation
7. router dispatcher and binder
8. end-to-end execution tests from `EXAMPLE.md`

## Definition Of Done For The Whole Stack

The implementation is done when all of the following are true:

- every OpenAPI operation is callable by exact `operationId`
- every `DESC.md` command is implemented as a thin wrapper command
- every `DESC.md` flow is implemented as a thin wrapper flow
- the router can consume the `LLM.md` JSON contract without free-text interpretation
- the `EXAMPLE.md` example executes through the router exactly as documented
- the HTTP layer remains thin and delegates all business execution to the router and wrapper stack

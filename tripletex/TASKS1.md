# TASKS1

## Objective

Turn the plan in `PLAN1.md` into concrete implementation work items for:

1. full generated raw Tripletex wrapper coverage from `docs/openapi.json`
2. thin `wrapper` layer from `DESC.md`
3. JSON router from `LLM.md` and `EXAMPLE.md`

All tasks below are planning tasks only. Status starts at `pending`.

## Constraint Baseline

This task list inherits `RULES.md`.

Any future additions or edits to this file must remain compatible with:

- the `/solve` endpoint contract
- proxy-only Tripletex access with Basic Auth `0:session_token`
- field-by-field correctness and efficiency constraints
- fresh-account competition assumptions
- full raw `operationId` fallback coverage
- the `HUMAN -> LLM -> JSON -> FLOWS/COMMANDS -> Tripletex` execution chain

## Phase 1. Foundation and generator design

- `T1` `pending`
  Confirm the future package layout under `app/`:
  - `generated`
  - `raw`
  - `wrapper`
  - `router`
  - `contracts`

- `T2` `pending`
  Define the generator input model from `docs/openapi.json`:
  - operations
  - schemas
  - path/query/body parameters
  - multipart operations
  - response schemas

- `T3` `pending`
  Define the generated operation catalog schema.
  Required fields:
  - `operationId`
  - `method`
  - `path`
  - `domain`
  - `subdomain`
  - `purpose`
  - `semanticAliases`
  - `antiTriggers`
  - `pathParams`
  - `queryParams`
  - `parameterSemantics`
  - `requestBody`
  - `responseSchema`
  - `safetyClass`
  - `technicalFlowFamily`
  - `actionMarker`
  - `conformancePolicyKey`

- `T4` `pending`
  Decide how generated code and generated metadata are split.
  The raw layer must remain exact and reproducible.

- `T5` `pending`
  Define deterministic naming and regeneration rules for generated artifacts.

- `T6` `pending`
  Define the shared raw runtime interface:
  - transport
  - auth injection
  - request execution
  - error normalization
  - response normalization

## Phase 2. Raw OpenAPI wrapper generation

- `T7` `pending`
  Build the OpenAPI loader that resolves refs and extracts all `800` operations.

- `T8` `pending`
  Generate the raw operation registry keyed by exact `operationId`.

- `T9` `pending`
  Generate or emit schema artifacts for request and response handling.

- `T10` `pending`
  Generate raw callable facades for all domains.

- `T11` `pending`
  Implement raw support for path parameters.

- `T12` `pending`
  Implement raw support for query parameters.

- `T13` `pending`
  Implement raw support for JSON request bodies.

- `T14` `pending`
  Implement raw support for multipart request bodies.

- `T15` `pending`
  Implement raw support for action endpoints with `:` path markers.

- `T16` `pending`
  Derive and attach technical flow-family metadata to every raw operation.

- `T17` `pending`
  Add coverage validation that proves every OpenAPI operation is present in the generated registry with required semantic and safety metadata.

## Phase 3. Raw runtime and execution support

- `T18` `pending`
  Implement the shared Tripletex transport client.
  It must always use:
  - `tripletex_credentials.base_url`
  - Basic Auth username `0`
  - `session_token` as password

- `T19` `pending`
  Implement raw execution context models so credentials stay outside the LLM JSON.

- `T20` `pending`
  Implement structured error handling for:
  - transport failures
  - Tripletex 4xx/5xx responses
  - parameter binding errors
  - one corrected retry based on precise Tripletex validation errors when safe

- `T21` `pending`
  Implement raw response pass-through rules for:
  - `{ "value": ... }`
  - `{ "values": [...] }`
  - empty `204` responses

- `T22` `pending`
  Implement raw parameter validation from the OpenAPI metadata before dispatch.

## Phase 4. Thin `wrapper` command layer

- `T23` `pending`
  Create the hand-authored wrapper command registry from `DESC.md`.

- `T24` `pending`
  Implement alias-to-raw mappings for all `78` friendly commands.

- `T25` `pending`
  Implement shared selector resolution helpers.
  Families include:
  - employee
  - customer
  - product
  - order
  - invoice
  - travel expense
  - project
  - department
  - voucher
  - supplier invoice

- `T26` `pending`
  Implement shared reference resolution helpers.

- `T27` `pending`
  Implement reusable payload adapters for:
  - `line_item`
  - `payment_spec`
  - `posting_line`
  - `travel_details`

- `T28` `pending`
  Implement `date_window` translation into endpoint-specific query parameters.

- `T29` `pending`
  Implement wrapper command metadata:
  - purpose
  - inputs
  - raw operation mapping
  - workflow membership
  - safety class
  - verification checklist
  - conformance policy mapping

## Phase 5. Thin `wrapper` flow layer

- `T30` `pending`
  Create the flow registry for all `21` business flows from `DESC.md`.

- `T31` `pending`
  Implement each business flow as an ordered sequence of wrapper commands.

- `T32` `pending`
  Implement prerequisite resolution rules inside flows.

- `T33` `pending`
  Implement flow-level verification hooks for create/update/payment/reverse flows and conformance policies for known sandbox-sensitive families.

- `T34` `pending`
  Implement technical flow-family registry for the full raw surface and a conformance policy registry for known tricky families.

- `T35` `pending`
  Map every raw command to at least one technical flow family and optionally to a conformance policy key where needed.

## Phase 6. Router contract models

- `T36` `pending`
  Define typed internal models for the LLM JSON contract from `LLM.md`.

- `T37` `pending`
  Implement contract validation for:
  - `contractVersion`
  - section presence
  - selected flow names
  - selected command names
  - raw `operationId` existence
  - `stepOrder`

- `T38` `pending`
  Implement internal models for:
  - `requestContext`
  - `language`
  - `understanding`
  - `sources`
  - `richData`
  - `flatBridge`
  - `executionPlan`
  - `validation`
  - `completion`

- `T39` `pending`
  Define the router error model for blocked, invalid, or incomplete plans.

## Phase 7. Router binding and dispatch

- `T40` `pending`
  Implement the router entrypoint that consumes the already-produced JSON contract.

- `T41` `pending`
  Implement execution unit resolution:
  - business flow
  - friendly command alias
  - raw `operationId`

- `T42` `pending`
  Implement parameter binding from:
  - `flatBridge.flowArguments`
  - `flatBridge.commandArguments`
  - `flatBridge.fieldBag`
  - entity-linked denormalized aliases

- `T43` `pending`
  Implement `stepOrder` execution.

- `T44` `pending`
  Implement parameter defaulting only where defaults are explicitly documented by OpenAPI or `DESC.md`.

- `T45` `pending`
  Implement router handling of blocked execution:
  - missing required inputs
  - ambiguous targets
  - invalid command/flow references

- `T46` `pending`
  Implement router result aggregation and per-step trace output.

## Phase 8. HTTP integration

- `T47` `pending`
  Keep `app/main.py` thin and connect it to the router entrypoint only.

- `T48` `pending`
  Define the boundary between:
  - HTTP request model
  - solve-time credentials
  - LLM JSON payload
  - execution result

- `T49` `pending`
  Ensure the router receives credentials separately from the LLM JSON, in line with `LLM.md`.

## Phase 9. Verification and coverage

- `T50` `pending`
  Add a raw coverage audit that proves all `800` operations are generated.

- `T51` `pending`
  Add a wrapper coverage audit that proves all friendly commands in `DESC.md` are implemented.

- `T52` `pending`
  Add a flow coverage audit that proves all business flows in `DESC.md` are implemented.

- `T53` `pending`
  Add a technical flow-family audit that proves all raw operations are assigned to at least one family.

- `T54` `pending`
  Add router contract tests for the `LLM.md` JSON shape.

- `T55` `pending`
  Add end-to-end execution tests for the scenario in `EXAMPLE.md`.

- `T56` `pending`
  Add validation that router dispatch never reparses raw human prompt text.

## Phase 10. Release gates

- `T57` `pending`
  Define the generation command that rebuilds the raw wrapper from `docs/openapi.json`.

- `T58` `pending`
  Define a release gate that fails if:
  - OpenAPI coverage drops
  - wrapper coverage drops
  - flow coverage drops
  - router contract validation drifts

- `T59` `pending`
  Define the minimal documentation set needed to keep future regeneration safe:
  - generator usage
  - wrapper registry usage
  - router JSON usage

## Recommended Implementation Order

Execute tasks in this sequence:

1. `T1` to `T6`
2. `T7` to `T17`
3. `T18` to `T22`
4. `T23` to `T29`
5. `T30` to `T35`
6. `T36` to `T46`
7. `T47` to `T49`
8. `T50` to `T59`

## Exit Criteria

This task set is complete when:

- the generated raw layer covers every `operationId`
- the thin `wrapper` layer fully matches `DESC.md`
- the router fully matches `LLM.md`
- the `EXAMPLE.md` flow can run through the router without special-case logic

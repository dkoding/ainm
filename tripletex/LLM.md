# LLM Bridge Design

This document defines the LLM-facing design for the `/solve` entrypoint.

The goal is to create one strict JSON contract that bridges:

- human language
- attachment content
- multilingual normalization
- extracted facts
- selected flows
- selected commands
- command-ready argument values

The intended execution chain is:

`HUMAN -> LLM -> JSON -> FLOWS/COMMANDS -> Tripletex`

This document is based only on:

- `DESC.md`
- `docs/task-overview.html`
- `docs/task-endpoint.html`
- `docs/task-scoring.html`
- `docs/task-examples.html`
- `docs/task-sandbox.html`
- `docs/openapi.json`

## 1. Purpose

The LLM module must do three jobs at once:

1. understand the human request in any language
2. extract and normalize every usable fact from prompt and attachments
3. emit an execution-ready JSON structure that tells downstream code:
   - which `FLOWS` to run
   - which `COMMANDS` to run
   - in what order to run them
   - which arguments each flow/command should receive

The JSON must not be a thin intent label. It must be a fully populated semantic bridge.

If the user says:

- customer name is `Jason Bourne`

then the JSON should hold all of these when they are valid:

- `customerName = "Jason Bourne"`
- `customerFirstName = "Jason"`
- `customerLastName = "Bourne"`
- `customerDisplayName = "Jason Bourne"`
- any corresponding structured object for the primary customer

The same principle applies to all transferable data:

- people
- companies
- invoices
- products
- dates
- amounts
- bank entries
- travel rows
- salary lines
- ledger postings
- attachments
- identifiers
- selectors
- payload fields

## 2. Core Design Principles

### 2.1 Lossless first, convenient second

The JSON must preserve original information and also provide denormalized convenience fields.

That means the JSON should contain both:

- a rich structured representation with provenance and confidence
- a flat argument-friendly representation that is easy for flows and commands to consume

### 2.2 No guessing

The LLM may:

- translate
- normalize
- derive obvious aliases
- resolve relative dates
- split clear full names into name parts

The LLM may not:

- invent missing identifiers
- invent dates not grounded in the prompt or attachment
- invent amounts
- invent resource IDs

Missing information must be marked explicitly.

### 2.3 Multilingual by default

The prompt and attachment text may be in any language. The JSON contract must use one canonical internal language for field names and planning, while preserving source-language text.

Recommended canonical internal language:

- English for field names
- ISO formats for dates, currency codes, country codes, language codes

This does not require a manual per-language support matrix.

Natural-language understanding and normalization belong to the LLM.

The implementation requirement is that one-shot prompt composition must reliably force the same canonical JSON contract regardless of input language.

### 2.4 Whole-API ready

Per `DESC.md`, the entire `openapi.json` surface is in scope.

So the JSON must support:

- hand-authored business flows from `DESC.md` Section 6
- hand-authored friendly command aliases from `DESC.md` Section 5
- raw low-level commands by exact OpenAPI `operationId`

### 2.5 Deterministic downstream consumption

Downstream execution should not need to reinterpret free text.

The LLM must therefore output:

- selected flows
- selected commands
- selected raw operation IDs when necessary
- execution order
- argument bindings
- ambiguity flags
- completeness signals

In the happy path, one LLM call should perform the full normalization and planning pass.

That means prompt composition matters: the LLM should receive precise instructions and canonical examples of valid JSON outputs, not only abstract prose rules.

## 3. End-To-End Pipeline

The LLM bridge should be designed as the following conceptual stages.

### 3.1 Stage A: request intake

Input arrives from `/solve` as:

- `prompt`
- `files[]`
- `tripletex_credentials`

The LLM bridge should not duplicate secrets unnecessarily. It should know that Tripletex credentials exist, but the execution layer can carry the actual credentials separately.

### 3.2 Stage B: source normalization

Before semantic planning, the system should normalize:

- prompt text
- file metadata
- extracted file text
- extracted tables
- OCR output
- relative date anchors from the request environment

### 3.3 Stage C: multilingual understanding

The bridge should:

- detect primary prompt language
- detect mixed-language content when present
- translate meaning into canonical internal English
- preserve original source text
- normalize locale-specific date and number formats

### 3.4 Stage D: fact extraction

The bridge should extract:

- entities
- identifiers
- attributes
- amounts
- dates
- ranges
- references
- relations between entities
- action words such as create, delete, pay, reverse, approve, invoice

### 3.5 Stage E: planning

The bridge should:

1. select the best business flow if one exists
2. expand into command steps
3. fall back to raw OpenAPI `operationId` commands where no friendly alias exists
4. bind extracted facts into flow and command arguments

### 3.6 Stage F: validation

Before execution, the JSON should say:

- what is complete
- what is missing
- what is ambiguous
- whether execution is safe
- whether execution is blocked

## 4. JSON Contract Overview

Recommended top-level shape:

```json
{
  "contractVersion": "tripletex.llm_bridge.v1",
  "requestContext": {},
  "language": {},
  "understanding": {},
  "sources": {},
  "richData": {},
  "flatBridge": {},
  "executionPlan": {},
  "validation": {},
  "completion": {}
}
```

This is not meant as implementation code. It is the design shape the implementation should follow.

## 5. Top-Level Sections

### 5.1 `contractVersion`

Purpose:

- version the JSON contract
- allow safe evolution later

Recommended value:

- `tripletex.llm_bridge.v1`

### 5.2 `requestContext`

Purpose:

- capture solve-request metadata that matters for interpretation

Recommended fields:

- `requestId`
- `receivedAt`
- `currentDate`
- `timezone`
- `promptCharCount`
- `attachmentCount`
- `hasTripletexCredentials`
- `baseUrlPresent`
- `sessionTokenPresent`

Notes:

- do not duplicate the actual `session_token` in the bridge JSON
- keep the bridge focused on meaning and execution planning, not secret transport

### 5.3 `language`

Purpose:

- preserve multilingual context and canonical translation

Recommended fields:

- `detectedPrimaryLanguage`
- `detectedLanguages`
- `canonicalLanguage`
- `promptOriginal`
- `promptCanonical`
- `translationNotes`
- `translationConfidence`
- `relativeDateAnchor`

`relativeDateAnchor` should include:

- `currentDate`
- `timezone`
- optional `weekStart`
- optional `monthContext`

### 5.4 `understanding`

Purpose:

- capture what the user wants in business terms

Recommended fields:

- `objective`
- `intentSummary`
- `taskFamilies`
- `targetResources`
- `operations`
- `priority`
- `riskLevel`
- `ambiguities`
- `assumptions`
- `missingData`
- `attachmentRequired`

Examples of `operations` values:

- `create`
- `update`
- `delete`
- `invoice`
- `register_payment`
- `reverse`
- `correct`
- `approve`
- `search`
- `report`
- `configure`
- `other`

### 5.5 `sources`

Purpose:

- preserve the raw evidence that produced the structured facts

Recommended fields:

- `prompt`
- `attachments`

Each attachment should have:

- `attachmentId`
- `filename`
- `mimeType`
- `textOriginal`
- `textCanonical`
- `ocrConfidence`
- `tables`
- `detectedLanguages`
- `extractedFactHints`

### 5.6 `richData`

Purpose:

- store the lossless, typed, provenance-rich model

Recommended sub-sections:

- `entities`
- `relations`
- `scalarFacts`
- `evidenceIndex`

### 5.7 `flatBridge`

Purpose:

- provide immediately usable argument values for flows and commands

Recommended sub-sections:

- `primaryEntityRefs`
- `fieldBag`
- `byEntityId`
- `flowArguments`
- `commandArguments`

### 5.8 `executionPlan`

Purpose:

- define which flows and commands must run, in which order

Recommended sub-sections:

- `selectedFlows`
- `selectedCommands`
- `fallbackRawCommands`
- `stepOrder`

### 5.9 `validation`

Purpose:

- tell the executor how safe and complete the plan is

Recommended fields:

- `isExecutable`
- `blockingIssues`
- `warnings`
- `missingRequiredData`
- `highRiskActions`
- `contradictions`
- `confidenceSummary`

### 5.10 `completion`

Purpose:

- define what success means

Recommended fields:

- `completionSignals`
- `expectedArtifacts`
- `postconditions`
- `verificationHints`

## 6. Rich Data Model

The rich data model is the authoritative semantic model.

It should be lossless enough that a future executor or verifier could rebuild the plan from it.

### 6.1 Universal entity envelope

Every extracted resource-like object should use one common envelope:

```json
{
  "entityId": "customer_1",
  "family": "customer",
  "role": "primary_subject",
  "displayName": "Jason Bourne",
  "sourceMentions": [],
  "normalized": {},
  "identifiers": {},
  "selectors": {},
  "payload": {},
  "denormalizedAliases": {},
  "sourceRefs": [],
  "confidence": {}
}
```

Meaning of each area:

- `entityId`
  Stable local identifier used by plan steps
- `family`
  Resource family such as `customer`, `employee`, `invoice`, `project`, `travelExpense`, `salary`, `bank`, `ledger`, or any top-level OpenAPI family
- `role`
  Semantic role such as `primary_subject`, `counterparty`, `manager`, `employee`, `supplier`, `customer`, `payer`, `payee`, `department_manager`
- `displayName`
  Best human-readable label
- `sourceMentions`
  Raw strings seen in prompt or files
- `normalized`
  Canonical normalized values
- `identifiers`
  IDs, numbers, emails, org numbers, voucher numbers, invoice numbers, etc.
- `selectors`
  Fields suitable for search commands
- `payload`
  Fields suitable for create/update commands
- `denormalizedAliases`
  Convenience aliases such as first name, last name, full name
- `sourceRefs`
  Provenance pointers
- `confidence`
  Per-entity or per-field confidence notes

### 6.2 `normalized`

`normalized` should hold the canonical shape of the entity.

Examples:

- names split into parts when possible
- dates in ISO format
- amounts as decimal numbers
- currencies as ISO currency codes
- countries as ISO country codes
- language codes normalized

### 6.3 `identifiers`

This section should hold identifying values that may be used for lookups or exact targeting.

Examples:

- `id`
- `email`
- `employeeNumber`
- `customerNumber`
- `productNumber`
- `invoiceNumber`
- `voucherNumber`
- `organizationNumber`
- `accountNumber`
- `projectNumber`
- `departmentNumber`
- `nationalIdentityNumber`
- `iban`
- `bban`
- `kid`
- `externalReference`

### 6.4 `selectors`

This section should hold search-friendly values already aligned with `DESC.md` selector families.

Examples:

- `customer_selector`
- `employee_selector`
- `invoice_selector`
- `travel_expense_selector`

### 6.5 `payload`

This section should hold fields that are candidates for create/update payloads.

Examples:

- customer email
- project start date
- salary lines
- travel per diem rows
- voucher postings
- bank reconciliation entries

### 6.6 `relations`

The JSON must represent relations explicitly.

Examples:

- employee belongs to department
- project belongs to customer
- order belongs to customer
- invoice pays/credits order
- travel expense belongs to employee and project
- voucher postings reference accounts and dimensions
- bank statement entry refers to invoice or supplier invoice

Recommended relation envelope:

```json
{
  "relationId": "rel_1",
  "type": "belongs_to",
  "fromEntityId": "project_1",
  "toEntityId": "customer_1",
  "sourceRefs": [],
  "confidence": 0.98
}
```

### 6.7 `scalarFacts`

Some facts do not belong cleanly to one entity.

Examples:

- global date window
- top count
- month-end comparison period
- verification preference
- send-to-customer preference
- deletion urgency

These should live in `scalarFacts`.

## 7. Flat Bridge Model

The flat bridge is the convenience layer.

It exists so flows and commands do not need to inspect the full rich graph just to get obvious values.

### 7.1 Why both rich and flat

The rich model is for:

- correctness
- provenance
- auditing
- ambiguity handling

The flat model is for:

- direct flow input binding
- direct command input binding
- trivial downstream field access

### 7.2 `primaryEntityRefs`

This section should identify the main object of each relevant type.

Example:

```json
{
  "customer": "customer_1",
  "employee": "employee_1",
  "invoice": "invoice_1"
}
```

### 7.3 `fieldBag`

This is the main denormalized bag of arguments.

It should contain:

- global convenience keys
- role-specific convenience keys
- typed aliases
- pre-split name values
- normalized dates and amounts
- duplicated forms needed by flows and commands

Examples:

- `customerName`
- `customerFirstName`
- `customerLastName`
- `customerOrganizationNumber`
- `customerEmail`
- `employeeEmail`
- `projectName`
- `invoiceNumber`
- `invoiceDate`
- `paymentDate`
- `voucherDate`
- `currencyCode`
- `paidAmount`
- `departmentName`
- `departmentManagerName`

### 7.4 `byEntityId`

When multiple entities of the same type exist, use a per-entity denormalized bag.

Example:

```json
{
  "customer_1": {
    "customerName": "Jason Bourne",
    "customerFirstName": "Jason",
    "customerLastName": "Bourne"
  },
  "customer_2": {
    "customerName": "Treadstone AS"
  }
}
```

### 7.5 Alias generation rules

The bridge should generate the following classes of aliases whenever valid.

For persons:

- `FirstName`
- `MiddleName`
- `LastName`
- `FullName`
- `DisplayName`

For organizations:

- `Name`
- `LegalName`
- `DisplayName`
- `OrganizationNumber`

For dates:

- raw ISO date
- `Year`
- `Month`
- `Day`
- `Quarter`

For date ranges:

- `DateFrom`
- `DateTo`

For money:

- `Amount`
- `CurrencyCode`
- optional `AmountMinorUnits`

For addresses:

- `Street`
- `PostalCode`
- `City`
- `CountryCode`

For identifiers:

- preserve both original and canonical forms when useful

### 7.6 Primary unqualified aliases

If exactly one primary entity of a type exists, unqualified aliases are allowed.

Example:

- `customerName`
- `customerFirstName`
- `customerLastName`

If multiple entities of the same type exist and no single primary entity is obvious:

- keep only qualified aliases under `byEntityId`
- add ambiguity notes

## 8. Execution Plan Model

The JSON must contain both flow-level and command-level planning.

### 8.1 `selectedFlows`

Each flow step should include:

- `stepId`
- `flowName`
- `flowType`
  - `business_flow`
  - `technical_flow_family`
- `why`
- `inputs`
- `dependsOn`
- `expectedOutputs`
- `confidence`

Recommended envelope:

```json
{
  "stepId": "flow_1",
  "flowName": "customer.create_or_update",
  "flowType": "business_flow",
  "why": "The request is to create a customer",
  "inputs": {},
  "dependsOn": [],
  "expectedOutputs": ["customerId"],
  "confidence": 0.98
}
```

### 8.2 `selectedCommands`

Each command step should include:

- `stepId`
- `commandName`
- `commandType`
  - `friendly_alias`
  - `raw_operation`
- `operationId`
- `parentFlowStepId`
- `why`
- `inputs`
- `dependsOn`
- `expectedOutputs`
- `confidence`

Recommended envelope:

```json
{
  "stepId": "cmd_1",
  "commandName": "customer.search",
  "commandType": "friendly_alias",
  "operationId": "Customer_search",
  "parentFlowStepId": "flow_1",
  "why": "Check for an existing matching customer before create",
  "inputs": {},
  "dependsOn": [],
  "expectedOutputs": ["customerMatches"],
  "confidence": 0.95
}
```

### 8.3 `fallbackRawCommands`

This section is important for complete OpenAPI coverage.

If the request touches a domain with no hand-authored alias or business flow, the LLM should:

- select a technical flow family
- emit the exact raw `operationId`
- bind raw command inputs from the bridge

### 8.4 Binding rules

Flow and command inputs should come from:

- `fieldBag`
- `byEntityId`
- `richData.entities[*].selectors`
- `richData.entities[*].payload`
- outputs of previous steps

Every binding should be explicit.

### 8.5 Order rules

The JSON must express execution order.

Examples:

- search before update
- resolve customer before create project
- create order before invoice
- search invoice before register payment
- create travel expense before add travel rows
- resolve account and voucher type before create manual voucher

## 9. Data Families The JSON Must Support

Because the whole OpenAPI surface is in scope, the JSON must support all transferable data families, not just the example workflows.

### 9.1 Person and organization families

- employees
- customers
- suppliers
- contacts
- managers
- accountants
- auditors
- payers
- payees

### 9.2 Commercial families

- products
- orders
- order lines
- invoices
- invoice remarks
- reminders
- subscriptions
- purchase orders
- supplier invoices
- incoming invoices

### 9.3 Work and HR families

- employee profiles
- employment details
- leave of absence
- next of kin
- timesheets
- salary lines
- payroll periods
- travel expenses
- travel rows

### 9.4 Project and department families

- departments
- department managers
- projects
- project categories
- project participants
- activities

### 9.5 Accounting and banking families

- ledger accounts
- vouchers
- voucher postings
- payment types
- VAT types
- accounting dimensions
- bank reconciliation entries
- balance and result periods
- year-end steps
- SAF-T and VAT reporting inputs

### 9.6 Document and asset families

- attachments
- documents
- archive objects
- assets
- pension and related records

### 9.7 Reference and configuration families

- currencies
- product units
- rate categories
- travel zones
- company modules
- categories
- settings
- preferences
- numbering schemes

## 10. Extraction Rules

### 10.1 Names

If a name clearly refers to a person:

- keep original full text
- split into first and last name when reliable
- keep full name anyway

If splitting is ambiguous:

- keep `fullName`
- mark ambiguity
- avoid overcommitting `firstName` and `lastName`

### 10.2 Dates

Normalize all dates to ISO `YYYY-MM-DD`.

For relative dates:

- use the request’s current date and timezone
- preserve the original phrase
- preserve the normalized result

Examples:

- `today`
- `this month`
- `next month`
- `last quarter`

### 10.3 Numbers and money

The bridge should normalize:

- decimal separators
- thousands separators
- negative amounts
- currency symbols
- percentage values

Keep:

- original string
- normalized numeric value
- detected currency code when available

### 10.4 Identifiers

Normalize and preserve:

- organization numbers
- invoice numbers
- customer numbers
- employee numbers
- account numbers
- project numbers
- department numbers
- IBAN
- BBAN
- KID
- national identity numbers

### 10.5 Attachments

Attachment-derived facts must be merged into the same JSON.

Do not treat prompt facts and file facts as separate worlds.

The bridge should keep provenance for each extracted field so the executor or verifier can understand where it came from.

### 10.6 Explicit vs derived vs inferred

Each field in the rich model should be marked as one of:

- `explicit`
  directly stated
- `derived`
  mechanically derived from explicit input
- `inferred`
  strongly implied but not literally stated

Derived examples:

- `customerFirstName = Jason` from `Jason Bourne`
- `month = 3` from `2026-03-21`
- `currencyCode = NOK` from `kr`

Inferred examples should be used sparingly and clearly marked.

## 11. Validation Rules

Before the JSON is accepted downstream, these checks should pass.

### 11.1 Structural checks

- valid JSON object
- correct `contractVersion`
- no malformed dates
- no malformed amounts
- no broken entity references
- all plan steps have IDs

### 11.2 Semantic checks

- every selected flow name must exist in `DESC.md`
- every selected friendly command must exist in `DESC.md`
- every raw command must use an exact `operationId` from `openapi.json`
- every command input must be bound
- missing required data must be listed, not silently ignored

### 11.3 Safety checks

- destructive tasks marked high risk
- ambiguous targets marked clearly
- blocked execution reported as `isExecutable = false`

## 12. Recommended LLM Behavior

The LLM should be instructed to:

- output JSON only
- never return prose outside the JSON object
- extract every usable fact
- duplicate useful aliases
- preserve original evidence
- choose flows first when a business flow fits
- choose friendly command aliases second
- fall back to raw `operationId` commands third
- never invent missing required facts

## 13. Example Skeleton

Example for a simple human request:

> "Create a customer named Jason Bourne with email jason@example.org"

Recommended JSON shape:

```json
{
  "contractVersion": "tripletex.llm_bridge.v1",
  "requestContext": {
    "currentDate": "2026-03-21",
    "timezone": "Europe/Oslo",
    "attachmentCount": 0,
    "hasTripletexCredentials": true
  },
  "language": {
    "detectedPrimaryLanguage": "en",
    "detectedLanguages": ["en"],
    "canonicalLanguage": "en",
    "promptOriginal": "Create a customer named Jason Bourne with email jason@example.org",
    "promptCanonical": "Create a customer named Jason Bourne with email jason@example.org"
  },
  "understanding": {
    "objective": "Create a customer",
    "taskFamilies": ["customer.create"],
    "targetResources": ["customer"],
    "operations": ["create"],
    "riskLevel": "low",
    "ambiguities": [],
    "missingData": []
  },
  "richData": {
    "entities": {
      "customer": [
        {
          "entityId": "customer_1",
          "family": "customer",
          "role": "primary_subject",
          "displayName": "Jason Bourne",
          "sourceMentions": ["Jason Bourne"],
          "normalized": {
            "name": "Jason Bourne",
            "firstName": "Jason",
            "lastName": "Bourne",
            "email": "jason@example.org"
          },
          "identifiers": {
            "email": "jason@example.org"
          },
          "selectors": {
            "customer_selector": {
              "email": "jason@example.org",
              "name": "Jason Bourne"
            }
          },
          "payload": {
            "name": "Jason Bourne",
            "email": "jason@example.org"
          },
          "denormalizedAliases": {
            "customerName": "Jason Bourne",
            "customerFirstName": "Jason",
            "customerLastName": "Bourne",
            "customerEmail": "jason@example.org"
          }
        }
      ]
    }
  },
  "flatBridge": {
    "primaryEntityRefs": {
      "customer": "customer_1"
    },
    "fieldBag": {
      "customerName": "Jason Bourne",
      "customerFirstName": "Jason",
      "customerLastName": "Bourne",
      "customerEmail": "jason@example.org"
    },
    "byEntityId": {
      "customer_1": {
        "customerName": "Jason Bourne",
        "customerFirstName": "Jason",
        "customerLastName": "Bourne",
        "customerEmail": "jason@example.org"
      }
    }
  },
  "executionPlan": {
    "selectedFlows": [
      {
        "stepId": "flow_1",
        "flowName": "customer.create_or_update",
        "flowType": "business_flow",
        "inputs": {
          "name": "Jason Bourne",
          "email": "jason@example.org"
        },
        "dependsOn": []
      }
    ],
    "selectedCommands": [
      {
        "stepId": "cmd_1",
        "commandName": "customer.search",
        "commandType": "friendly_alias",
        "operationId": "Customer_search",
        "parentFlowStepId": "flow_1",
        "inputs": {
          "email": "jason@example.org",
          "name": "Jason Bourne"
        },
        "dependsOn": []
      },
      {
        "stepId": "cmd_2",
        "commandName": "customer.create",
        "commandType": "friendly_alias",
        "operationId": "Customer_post",
        "parentFlowStepId": "flow_1",
        "inputs": {
          "name": "Jason Bourne",
          "email": "jason@example.org"
        },
        "dependsOn": ["cmd_1"]
      }
    ]
  },
  "validation": {
    "isExecutable": true,
    "blockingIssues": [],
    "warnings": [],
    "missingRequiredData": []
  },
  "completion": {
    "completionSignals": [
      "A customer record exists with the requested name and email"
    ]
  }
}
```

## 14. Final Recommendation

The LLM bridge should produce one strict JSON object with three simultaneous layers:

1. `rich semantic model`
   - lossless, typed, provenance-aware
2. `flat execution bridge`
   - denormalized, alias-rich, command-ready
3. `ordered execution plan`
   - flows first, commands second, raw `operationId` fallback when needed

That is the cleanest way to bridge human language to the full Tripletex flow and command surface described in `DESC.md`.

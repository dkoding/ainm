# Tripletex Task-Solving Analysis

This document analyzes how to solve the NM i AI Tripletex tasks using the task docs plus the Tripletex OpenAPI spec.

It is intentionally solution-oriented, but contains no code.

## 1. What The Task Really Is

This is not just "call an accounting API from an LLM."

The real task is:

1. read a natural-language business/accounting instruction
2. infer the exact business intent
3. map that intent to a small, correct API workflow
4. execute it in a fresh Tripletex environment
5. avoid mistakes, unnecessary calls, and duplicate object creation
6. finish within 5 minutes

The competition docs make a few things explicit:

- there are 30 task types
- each task has 56 prompt variants
- prompts come in 7 languages
- each submission gets a fresh account
- scoring is field-by-field plus efficiency

That combination means the winning system must be:

- multilingual
- workflow-aware
- schema-aware
- conservative about API calls
- good at extracting structured intent from noisy prompts and attachments

## 2. What The Scoring Implies For System Design

The most important design implication is that correctness alone is not enough.

A good solver must optimize for both:

- exact state change
- minimal API footprint

The scoring model penalizes:

- extra calls
- 4xx errors
- trial-and-error behavior

This means the architecture should not be:

- "LLM blindly calls endpoints until something works"

It should instead be:

- "LLM or planner decides a precise workflow first"
- "executor performs a small number of validated steps"
- "verifier checks only what is needed"

## 3. The Right Mental Model For The Task

Each task is usually one of these patterns:

### 3.1 Create

Examples:

- create employee
- create customer
- create product
- create department
- create project

Main challenge:

- map prompt fields into the correct JSON payload
- include prerequisites if the target object depends on another entity

### 3.2 Find and update

Examples:

- add phone number to an existing customer
- change invoice email
- change project metadata

Main challenge:

- identify the target object reliably
- avoid updating the wrong one when names are ambiguous

### 3.3 Find and delete / reverse / correct

Examples:

- delete travel expense
- remove wrong entity
- reverse or correct bookkeeping

Main challenge:

- locate exact target
- understand whether deletion is legal vs. whether correction/reversal is required

### 3.4 Create a linked workflow

Examples:

- invoice for customer
- project linked to customer
- payment registration on invoice

Main challenge:

- create or resolve dependencies in the right order
- use the most efficient action endpoint when available

### 3.5 Read attachment, then execute accounting action

Examples implied by docs:

- invoice/contract/expense attached as PDF or image
- bank or ledger correction tasks derived from files

Main challenge:

- extract structured data from attachment
- normalize it into API operations

## 4. Recommended Solver Architecture

## 4.1 Stage 1: Request normalization

The solver should immediately normalize the incoming request into an internal task object:

- original prompt
- detected language
- translated or normalized instruction
- extracted entities
- extracted quantities, dates, amounts, organization numbers, invoice numbers, emails
- attachment inventory
- risk flags

This internal representation matters because prompt variants come in seven languages and likely vary in phrasing even for identical task intent.

## 4.2 Stage 2: Intent classification

Before hitting the API, the system should classify the task into:

- entity family
- operation type
- target uniqueness confidence
- prerequisite requirements

Suggested internal labels:

- `employee.create`
- `employee.update`
- `customer.create`
- `product.create`
- `invoice.create`
- `invoice.register_payment`
- `travel_expense.delete`
- `project.create`
- `department.create`
- `voucher.correct`

This single step is critical for efficiency. If the solver knows the task family up front, it can avoid broad exploration.

## 4.3 Stage 3: Attachment extraction

Attachments should be processed before planning API calls.

The output should be structured:

- vendor/customer names
- dates
- amounts and currency
- product/service descriptions
- invoice identifiers
- travel legs, employee names, locations, timestamps

If extraction confidence is low, the planner should prefer:

- searching for corroborating objects in Tripletex
- or taking the safest interpretation that avoids irreversible corruption

## 4.4 Stage 4: Workflow planning

The planner should produce a short execution plan of 1 to 5 steps, not a long chain.

The plan should answer:

- what object is the end state?
- what dependencies are required?
- which endpoint is the shortest valid path?
- what must be searched first?
- what can be inferred directly from prior responses?

Bad plan:

- search everything
- then create everything
- then re-read everything

Good plan:

- resolve just the entities required for disambiguation
- create/update/delete once
- optionally verify the single field set that matters

## 4.5 Stage 5: Deterministic execution layer

The actual executor should be conservative and deterministic:

- precise endpoint selection
- strict payload shaping
- targeted `fields`
- bounded retries
- parse validation errors

The executor should not let the LLM improvise raw HTTP behavior without schema awareness.

## 4.6 Stage 6: Minimal verification

Verification is important because competition scoring is field-based.

But verification must stay small:

- if a `POST` returns the created object, often reuse that response
- only do a follow-up `GET` when:
  - server-side mutation may normalize fields
  - the scoring-relevant field is not present in the mutation response
  - the action endpoint returns too little detail

## 5. Workflow Strategy By Task Family

## 5.1 Employees

Likely tasks:

- create employee
- set contact details
- assign admin-like or system-access-related behavior

Recommended approach:

1. extract full name, email, phone, department, admin/system-access intent
2. search by email only if task seems update-like or duplicate-risky
3. otherwise create directly
4. if admin/system-access is required, map that to exact fields or follow-up endpoint based on sandbox findings
5. verify the few scoring-relevant fields

Important open question:

- The high-level docs mention "administrator role assigned," but the exact smallest valid API payload for that should be confirmed in sandbox.

## 5.2 Customers

Likely tasks:

- create customer
- set invoice email / contact info
- update customer metadata

Recommended approach:

1. if unique identifier exists, search by that first:
   - organization number
   - email
   - exact customer name
2. if clearly absent or task explicitly says create, create customer
3. when updating, fetch exact target by ID before mutation if ambiguity exists

## 5.3 Products

Likely tasks:

- create product
- set price or VAT-related info
- connect product to later order/invoice flow

Recommended approach:

1. extract product number/name/price/VAT/unit
2. search by product number or name when update-like
3. create if task is clearly additive
4. carry returned product ID forward instead of re-querying

## 5.4 Orders and invoices

This is the most important multi-step family.

Typical cases:

- create invoice for customer
- create invoice from new order lines
- register payment
- issue credit note

Recommended workflow selection:

### Path A: Order-first invoicing

Use when the task describes:

- customer + product/service lines
- a standard sales flow

Plan:

1. resolve/create customer
2. resolve/create product if required
3. create order with lines
4. convert order using `PUT /order/{id}/:invoice`

Advantages:

- matches native Tripletex flow
- likely efficient
- cleaner for invoicing actions

### Path B: Direct invoice creation

Use when:

- task is clearly invoice-centric
- data is already structured for invoice object
- order is unnecessary overhead

Plan:

1. resolve/create customer
2. create invoice directly with `orders` or `orderLines`

### Path C: Invoice payment registration

Use:

- `PUT /invoice/{id}/:payment`

Plan:

1. locate invoice by invoice number/customer/date
2. apply payment with exact amount/date/payment type
3. verify invoice or ledger effect only if needed

### Path D: Credit-note or correction-style invoice flow

Use when:

- prompt says credit note, reverse, correct, cancel

Plan:

1. find target invoice
2. determine whether deletion is legal or whether credit-note/reversal path is required
3. prefer explicit native invoice flow over destructive guessing

## 5.5 Travel expenses

Likely tasks:

- create expense from prompt/receipt
- update dates/amounts/project
- delete wrong travel expense

Recommended approach:

1. extract employee identity, dates, project, department, payment amounts
2. search by employee/date range/state if updating or deleting
3. create/update/delete with a small number of calls

Potential difficulty:

- attachment-heavy tasks
- richer nested payloads than simpler entities

## 5.6 Projects

Likely tasks:

- create project for customer
- assign project manager
- configure invoice behavior

Recommended approach:

1. resolve/create customer
2. resolve employee for project manager if named
3. resolve department if specified
4. create project with minimal required fields

## 5.7 Departments

Likely tasks:

- create department
- assign manager
- enable accounting-related behavior

Recommended approach:

1. resolve department manager if specified
2. create department
3. if "enable module" or similar appears, map to exact config change verified in sandbox

Important note:

- This family may include UI/system-configuration assumptions not obvious from just CRUD docs.
- Sandbox exploration is especially important here.

## 5.8 Ledger / vouchers / corrections

Likely tasks:

- locate incorrect voucher
- create corrective voucher
- reverse postings
- reconcile bookkeeping state

Recommended approach:

1. search vouchers and postings with narrow filters:
   - date range
   - voucher number
   - customer
   - project
   - account
2. determine whether task requires:
   - delete
   - update
   - new correction voucher
3. execute the accounting fix
4. verify by querying voucher/posting state

This family is likely where Tier 3 difficulty concentrates.

## 6. How To Handle The Fresh-Account Constraint

Every submission starts from scratch.

This changes planning significantly:

- there is no point assuming reference data already exists
- prerequisite creation becomes normal, not exceptional

Practical implication:

The solver should maintain a small internal dependency graph:

- if invoice requested and customer not resolved -> create/resolve customer first
- if project requested and customer required -> create/resolve customer first
- if department manager named but employee missing -> create/resolve employee first

This should be explicit in the planner, not emergent.

## 7. How To Reduce API Calls

Competition scoring makes this a first-class concern.

High-value tactics:

### 7.1 Prefer exact search filters

Use:

- `organizationNumber`
- exact email
- exact invoice number
- exact voucher number

Avoid:

- broad scans by name unless necessary

### 7.2 Use `fields`

When searching, request only what is needed:

- IDs
- exact target fields for disambiguation

### 7.3 Reuse mutation responses

If `POST /customer` returns the customer object and ID, do not immediately re-fetch unless necessary.

### 7.4 Prefer action endpoints

Examples:

- `PUT /order/{id}/:invoice`
- `PUT /invoice/{id}/:payment`

These can replace longer, more error-prone workflows.

### 7.5 Bound retries

A good strategy is:

- one well-formed attempt
- if validation fails, one corrected retry based on the actual error message

Not:

- repeated mutation guesses

## 8. How To Avoid 4xx Errors

The most common avoidable sources:

### 8.1 Wrong endpoint path

Fix:

- keep a fixed registry of allowed, task-relevant endpoints

### 8.2 Missing required fields

Fix:

- schema-aware payload builder
- per-task-family required field templates

### 8.3 Ambiguous update/delete targets

Fix:

- require strong identity match before destructive operations
- if multiple matches, use more filters instead of picking the first result

### 8.4 Wrong object order

Fix:

- create dependencies first
- do not try to invoice a nonexistent customer or link a missing project manager

## 9. Multilingual Prompt Handling

The docs explicitly state prompts may arrive in:

- Norwegian
- English
- Spanish
- Portuguese
- Nynorsk
- German
- French

Implications:

- do not build a Norwegian-only prompt parser
- normalize to an internal English or Norwegian schema for downstream reasoning
- extract canonical entities independent of language

Important detail:

- field values themselves may contain Norwegian names, organizations, and domain terms
- so translation should target instruction semantics, not blindly transform business data

## 10. Attachment Handling Analysis

Attachments can contain the essential facts for a task.

The system therefore needs:

- file-type detection
- PDF extraction
- image OCR or VLM extraction
- schema normalization after extraction

Recommended internal output format for attachments:

- `document_type`
- `party_names`
- `dates`
- `amounts`
- `currency`
- `invoice_number`
- `line_items`
- `travel_segments`
- `confidence`

Low-confidence extraction should trigger:

- targeted Tripletex searches
- or a more conservative action choice

## 11. Verification Strategy

Because scoring is field-by-field, verification is valuable.

But verification should be specific:

- after create employee: verify only name/email/role-related fields
- after create customer: verify identifiers and communication fields
- after invoice flow: verify invoice existence, customer, amounts, and payment if relevant
- after correction: verify voucher/posting state

The verifier should use:

- a task-family-specific checklist
- not a generic "fetch everything"

## 12. What Should Be Learned In The Sandbox Before Writing More Code

The docs and OpenAPI are enough to build the broad architecture, but not enough to guarantee perfect task execution.

The following should be verified manually in sandbox:

### 12.1 Employee admin/system access mapping

Need to answer:

- what exact field or endpoint sets admin status?
- is `userType` sufficient?
- is a separate access/module action required?

### 12.2 Department/module enablement

Need to answer:

- does this happen through department fields?
- or through some other configuration endpoint?

### 12.3 Credit-note workflows

Need to answer:

- when should the solver use invoice action endpoints vs create corrective invoice vs voucher reversal?

### 12.4 Travel expense minimum valid payload

Need to answer:

- what is the smallest successful payload for common travel-expense creation tasks?

### 12.5 Best invoice path by task subtype

Need to answer:

- when is `POST /invoice` better?
- when is `PUT /order/{id}/:invoice` better?

## 13. Recommended Non-Code Next Steps

Before adding more implementation logic, the best next steps are:

1. Build a task-family matrix from the docs and sandbox examples.
2. For each family, identify:
   - minimal search pattern
   - minimal mutation payload
   - minimal verification query
3. Record exact "golden workflows" for:
   - employee create/update/admin
   - customer create/update
   - product create
   - order to invoice
   - invoice payment
   - travel expense create/delete
   - project create
   - department create/configure
   - voucher correction
4. Only then implement the planner/executor.

## 14. Final Assessment

The Tripletex challenge is fundamentally a structured workflow synthesis problem.

The hard parts are not:

- HTTP transport
- authentication
- generic JSON handling

The hard parts are:

- precise task interpretation across languages
- correct dependency ordering
- choosing the shortest valid native Tripletex workflow
- avoiding 4xx errors
- handling attachment-derived bookkeeping

The API is large, but the task-relevant surface is narrow enough that a strong task-family playbook should outperform a generic "open-ended API agent."

The best solver will look less like a chatbot and more like:

- a multilingual intent parser
- a workflow selector
- a schema-aware executor
- a narrow verifier

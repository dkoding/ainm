# Extended Tasks For The Tripletex Solver

This file defines the second-phase work after the base solver is stable.

Constraints for this plan:

- stay within the same approved component set
- do not introduce extra managed GCP services outside the approved list
- keep `gemini-2.5-pro` as the default model because the project has no credit pressure
- only use `Compute Engine` if there is a measured reason that `Cloud Run` cannot cover

## 1. Extended Goal

The extended version should:

- increase accuracy on edge cases and ambiguous prompts
- improve attachment understanding without adding external OCR services
- reduce wrong updates and duplicate entity creation
- improve success rate on the hardest workflow tasks
- remain competition-safe and operationally simple

## 2. Model Strategy Extensions

- [ ] add a two-pass Gemini strategy using `gemini-2.5-pro`
- [ ] use pass one for classification, extraction, and workflow planning
- [ ] use pass two for execution review before irreversible actions
- [ ] require the second pass to check target resolution, missing prerequisites, and likely API failures
- [ ] compare one-pass versus two-pass latency and success rate
- [ ] keep the second pass conditional so it is used only on risky tasks

## 3. Prompt Engineering Extensions

- [ ] create separate prompt templates for create, update, delete, invoice, payment, and attachment-heavy tasks
- [ ] create separate prompts for target resolution and payload construction
- [ ] create a prompt template for turning Tripletex API errors into a corrected next action
- [ ] use `AI Studio` to iterate the prompts against realistic examples before updating runtime prompts
- [ ] maintain a versioned prompt set so prompt regressions can be detected

## 4. Attachment Processing Extensions

- [ ] improve PDF extraction quality using stronger parsing and page-level handling
- [ ] add explicit multimodal extraction prompts for invoices, receipts, and contracts
- [ ] add attachment-specific normalization rules for dates, amounts, VAT, reference numbers, and parties
- [ ] compare direct multimodal extraction against text-first extraction for the same documents
- [ ] add confidence scoring to extracted attachment fields
- [ ] route low-confidence attachment cases into an extra planning review before execution

## 5. Hard-Case Task Coverage

- [ ] ambiguous customer resolution when multiple similar names exist
- [ ] ambiguous employee resolution when names and emails conflict
- [ ] invoice creation where prerequisite customer or product state is incomplete
- [ ] payment registration where invoice state must be confirmed first
- [ ] travel expense tasks with incomplete travel detail in text or attachment
- [ ] voucher correction tasks where delete is not legal and reversal is required
- [ ] project tasks linked to customer or department context
- [ ] cross-entity tasks that require finding, creating, and then linking objects in sequence

## 6. Entity Resolution Extensions

- [ ] add stronger matching logic that combines exact fields, normalized text, and context clues
- [ ] distinguish between "safe exact match", "probable match", and "unsafe ambiguous match"
- [ ] make destructive actions require the safe tier only
- [ ] make create actions check for likely duplicates before creating
- [ ] add family-specific disambiguation logic for invoices, customers, and travel expenses

## 7. Planner And Executor Extensions

- [ ] let the planner generate alternative workflows when multiple valid API paths exist
- [ ] score candidate workflows by correctness risk and estimated call count
- [ ] teach the executor to reject plans that exceed configured step budgets
- [ ] add a small correction loop for schema-valid but semantically wrong payloads
- [ ] add a preflight checklist for destructive actions and bookkeeping corrections
- [ ] add stricter postcondition checks for invoice and payment workflows

## 8. Efficiency Extensions

- [ ] benchmark end-to-end latency by task family
- [ ] benchmark API-call counts by task family
- [ ] remove repeated searches for entities already resolved in the same request
- [ ] compress verification on low-risk create and update flows
- [ ] test whether a better planner prompt lowers API-call counts more than executor tweaks do
- [ ] identify where `gemini-2.5-pro` materially improves accuracy enough to justify added latency

## 9. Regression And Evaluation Extensions

- [ ] create a structured evaluation set grouped by task family
- [ ] create a hard-case set with ambiguous targets, weak attachments, and partial instructions
- [ ] create multilingual evaluations across all supported prompt languages
- [ ] add scorecards for exact-state success, wrong-target rate, duplicate-creation rate, API-call count, and latency
- [ ] run regression tests after every prompt or planning change
- [ ] keep notes on which prompt variants break extraction or planning most often

## 10. Operational Extensions Within Allowed Components

- [ ] improve the Cloud Run deploy script for repeatability
- [ ] add a simple release checklist for Cloud Shell deployments
- [ ] add safe redaction rules for any local debug output
- [ ] add a manual rollback procedure using previous Cloud Run revisions
- [ ] document what to inspect first when a live submission fails

## 11. Compute Engine Reserve Tasks

These are not default tasks. Only do them if there is a measured reason.

- [ ] define the specific limit hit on Cloud Run before considering `Compute Engine`
- [ ] test whether the limit is cold starts, memory, CPU, request duration, or dependency constraints
- [ ] prove that `Compute Engine` solves that limit better than a Cloud Run configuration change
- [ ] if a VM is ever used, keep the same application contract and deployment packaging
- [ ] do not move the main solver to `Compute Engine` without benchmark evidence

## 12. Extended Completion Criteria

The extended version is complete when:

- the solver is materially stronger on ambiguous and attachment-heavy tasks
- wrong-target mutations are rare
- duplicate creation is much lower than the base version
- the hardest Tripletex workflows are handled with high confidence
- the extra logic improves outcomes enough to justify the added complexity

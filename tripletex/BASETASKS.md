# Base Tasks For The Tripletex Solver

This file defines the baseline implementation scope for a competition-ready Tripletex solver.

Constraints for this plan:

- use only the components explicitly available in the free NM i AI GCP setup
- primary runtime is `Cloud Run`
- model runtime is `Vertex AI` with Gemini
- prompt iteration can use `AI Studio`
- development and deployment can use `Cloud Shell`
- `Compute Engine` is allowed, but not part of the base path
- do not depend on `Cloud Logging`, `Secret Manager`, `Cloud Storage`, `Document AI`, or `Vision API`
- default to the smartest available Gemini model for the main path

Default model assumption:

- use `gemini-2.5-pro` as the main model for planning, extraction, and validation

## 1. Baseline Goal

The base version should:

- accept a valid NM i AI Tripletex `/solve` request
- understand the prompt in any supported language
- process included attachments well enough for common cases
- execute the correct Tripletex API workflow with minimal unnecessary calls
- return the required response inside the competition timeout

## 2. Allowed GCP Components In Scope

- `Cloud Run`
- `Vertex AI`
- `Gemini models`
- `AI Studio`
- `Cloud Shell`
- `Compute Engine` only as a reserve option if Cloud Run proves insufficient later

## 3. Explicitly Out Of Scope For Base

- `Cloud Logging`
- `Secret Manager`
- `Cloud Storage`
- `Document AI`
- `Vision API`
- background queues
- databases
- self-hosted OCR or self-hosted model servers

## 4. Base Architecture Tasks

- [ ] define the exact request contract from the competition endpoint docs
- [ ] define the exact response contract expected by the competition endpoint
- [ ] keep the service stateless so each request can run independently on Cloud Run
- [ ] make the solver use the incoming Tripletex `base_url` and `session_token` from each request
- [ ] keep all per-request execution data in memory only
- [ ] set the default model to `gemini-2.5-pro`
- [ ] keep all API execution deterministic after the planning step

## 5. Development Environment Tasks

- [ ] keep the project runnable from `Cloud Shell`
- [ ] make deployment scripts work from `Cloud Shell` without local-machine assumptions
- [ ] document the minimum local and Cloud Shell commands needed for deploy and test
- [ ] keep `.env.example` limited to configuration actually needed by the base version

## 6. Prompt And Model Tasks

- [ ] create a single high-quality system prompt for Tripletex task solving
- [ ] require structured JSON output from Gemini for task classification and extracted fields
- [ ] make the model produce an internal task object before any API execution
- [ ] make the model classify the request into a task family
- [ ] make the model identify whether attachments matter for the task
- [ ] make the model produce a short execution plan instead of free-form reasoning
- [ ] make the model flag ambiguity before destructive actions
- [ ] test the prompt in `AI Studio` before wiring final prompt versions into the app

## 7. Internal Task Representation Tasks

- [ ] define one normalized internal schema for all incoming tasks
- [ ] include original prompt, normalized prompt, detected language, extracted entities, dates, amounts, emails, IDs, and attachment metadata
- [ ] include a task-family label such as `employee.create`, `customer.update`, `invoice.create`, or `invoice.register_payment`
- [ ] include a confidence score for target resolution
- [ ] include a risk flag for destructive or ambiguous operations
- [ ] include a compact execution plan with the minimum required Tripletex actions

## 8. Attachment Handling Tasks

- [ ] support the attachment shape defined by the competition request model
- [ ] decode and inspect attachment metadata safely
- [ ] implement basic PDF text extraction
- [ ] implement image-to-model handling through Gemini multimodal input
- [ ] normalize extracted attachment content into structured fields
- [ ] separate extraction from execution so bad extraction does not immediately cause bad writes
- [ ] define fallback behavior when attachment extraction is weak or partial

## 9. Tripletex API Tasks

- [ ] map the exact endpoints needed for the likely task families
- [ ] define supported workflows for create, update, delete, invoice, payment, travel expense, project, department, and voucher tasks
- [ ] prefer precise search endpoints over broad discovery calls
- [ ] use `fields` filtering wherever it reduces payload size and improves precision
- [ ] handle Tripletex list wrappers and object wrappers consistently
- [ ] handle action endpoints correctly, especially invoicing and payment registration flows
- [ ] normalize Tripletex validation errors into planner-readable feedback

## 10. Deterministic Executor Tasks

- [ ] separate model reasoning from HTTP execution
- [ ] create a deterministic executor that takes a plan and performs exact API calls
- [ ] validate payload shape before each outbound request
- [ ] cap the maximum number of execution steps per task
- [ ] cap retries and make retries targeted rather than generic
- [ ] stop immediately on clearly wrong target resolution
- [ ] parse 4xx responses and decide whether a single corrected retry is justified
- [ ] avoid broad trial-and-error loops

## 11. Core Task-Family Coverage

- [ ] employee create tasks
- [ ] employee update tasks
- [ ] customer create tasks
- [ ] customer update tasks
- [ ] product create tasks
- [ ] product update tasks
- [ ] department create tasks
- [ ] project create tasks
- [ ] project update tasks
- [ ] order creation tasks
- [ ] invoice creation tasks
- [ ] invoice payment registration tasks
- [ ] travel expense create tasks
- [ ] travel expense update or delete tasks
- [ ] voucher correction or reversal tasks

## 12. Entity Resolution Tasks

- [ ] define search strategies for customers, employees, products, projects, invoices, and travel expenses
- [ ] prefer exact identifiers over fuzzy text matches whenever identifiers exist
- [ ] define tie-break rules when names are ambiguous
- [ ] require extra evidence before mutating a non-unique target
- [ ] avoid creating duplicates when the intended object already exists

## 13. Verification Tasks

- [ ] define when mutation responses are enough and when a follow-up read is needed
- [ ] verify only the fields that matter for scoring
- [ ] avoid full object rereads when a mutation response already contains the needed data
- [ ] define a final success criterion per task family

## 14. Efficiency Tasks

- [ ] set a hard budget for API calls per request
- [ ] minimize search breadth before creation or update
- [ ] reuse earlier API responses instead of refetching the same objects
- [ ] minimize unnecessary verification calls
- [ ] keep the execution plan short and explicit

## 15. Evaluation Tasks

- [ ] build a local request replay set from task examples and your own synthetic variants
- [ ] test multilingual prompts across the supported languages
- [ ] test attachment-heavy and attachment-free cases separately
- [ ] test wrong-target cases and ambiguous-target cases
- [ ] measure API-call counts, 4xx rate, and end-to-end latency
- [ ] compare model output quality in `AI Studio` against live runtime behavior on `Vertex AI`

## 16. Deployment Tasks

- [ ] keep the service deployable to `Cloud Run`
- [ ] configure region to `europe-north1`
- [ ] set timeout to match or exceed the competition requirement safely
- [ ] tune concurrency conservatively if one request can consume a lot of model time
- [ ] verify `/health`
- [ ] verify `/solve` against a sandbox request before submission

## 17. Competition Readiness Tasks

- [ ] confirm the live service uses the incoming Tripletex credentials, not local sandbox credentials
- [ ] confirm API key protection for your own endpoint if you keep it enabled
- [ ] confirm no secrets or session tokens are written to logs or files
- [ ] confirm the deployed URL is the one submitted in the NM i AI portal
- [ ] run at least one full end-to-end sandbox submission before competition use

## 18. Base Completion Criteria

The base version is complete when:

- the service is live on `Cloud Run`
- the model path uses `Vertex AI` with `gemini-2.5-pro`
- the solver handles the common Tripletex task families reliably
- the solver avoids obvious duplicate creation and wrong-target mutations
- the solver stays within time and API-call limits on representative test cases

# Allowed GCP Components Analysis For The Tripletex Solver

This document analyzes the Google Cloud components that are actually in scope for this project after the final restrictions.

Hard constraints:

- only use the GCP components explicitly available in the NM i AI free setup
- do not design around services that are not part of that approved set
- do not introduce overlapping infrastructure unless there is a measured reason
- because credits are not the limiting factor here, default to the smartest Gemini models rather than the cheapest ones

Approved component set:

- `Cloud Run`
- `Vertex AI`
- `Gemini models`
- `AI Studio`
- `Cloud Shell`
- `Compute Engine`

Everything else is out of scope for this document, even if it could be useful on normal GCP.

## 1. Recommended High-Level Stack

Recommended primary stack:

1. `Cloud Run` for the public `/solve` endpoint
2. `Vertex AI` for Gemini runtime access
3. `gemini-2.5-pro` as the default reasoning model
4. `AI Studio` for prompt and schema iteration
5. `Cloud Shell` for development, deploy, and operations

Reserve component:

6. `Compute Engine` only if Cloud Run proves insufficient for a measured reason

Not recommended as the primary path:

1. `Compute Engine` as the first runtime
2. cost-optimized model downgrades as a default strategy
3. introducing services outside the approved set

## 2. Final Component Decisions

## 2.1 Cloud Run

### What it is

Managed hosting for HTTP services and containers.

### Why it fits this task

The competition requires:

- a public HTTPS endpoint
- stateless request handling
- time-bounded execution

That maps directly to Cloud Run services.

### Relevant capabilities

According to Google Cloud documentation:

- every Cloud Run service gets its own HTTPS endpoint
- Cloud Run manages TLS
- Cloud Run supports request-based autoscaling
- Cloud Run can scale to zero
- Cloud Run supports revision-based rollout and rollback
- Cloud Run can run source-based deployments or container-based deployments

### How to use it efficiently

For this solver:

- deploy one stateless service for `/solve`
- keep the region in `europe-north1`
- keep the app simple and synchronous unless benchmarks show a real need for more complexity
- keep revisions small and easy to roll back
- configure timeout and concurrency conservatively for LLM-heavy requests

### What to avoid

- do not move to `Compute Engine` just to host FastAPI
- do not build extra serving layers around Cloud Run unless a specific limitation forces it

## 2.2 Vertex AI

### What it is

Managed Google Cloud platform access to Gemini and related model capabilities.

### Why it fits this task

The Tripletex task needs:

- multilingual prompt understanding
- structured extraction
- multimodal handling for attachments
- workflow planning
- interpretation of API errors
- structured outputs for deterministic execution

That is exactly the kind of work Gemini on Vertex AI is good at.

### Relevant capabilities

According to current Google Cloud documentation:

- Vertex AI offers Gemini 2.5 Pro
- Vertex AI offers Gemini 2.5 Flash
- Vertex AI offers Gemini 2.5 Flash-Lite
- Vertex AI supports multimodal input
- Vertex AI supports structured output and function-calling style workflows

### Final usage decision

Use `Vertex AI` as the production runtime for all Gemini calls.

Do not split runtime auth across multiple platforms if `Vertex AI` already works in your project.

### How to use it efficiently

- use one clean Gemini runtime path
- demand structured JSON from the model
- separate extraction, planning, and execution in the application architecture
- use the model to decide the workflow, but keep HTTP execution deterministic in Python

## 2.3 Gemini Models

### Final model policy

Because the project has no practical credit pressure, the default policy should be:

- use the smartest compatible model by default

For this project that means:

- use `gemini-2.5-pro` as the main model for planning, extraction, validation, and hard reasoning

### What this changes

This project should not start from a cost-optimized routing strategy such as:

- `flash` for most requests
- `pro` only as fallback

That type of routing can be added later only if benchmarking shows it improves latency materially without hurting accuracy.

### Practical recommendation

For the baseline solver:

- use `gemini-2.5-pro` everywhere the model is involved

For later optimization:

- benchmark whether some narrow low-risk tasks can move to `gemini-2.5-flash`
- only do that if the measured win is real and accuracy remains stable

## 2.4 AI Studio

### What it is

Browser-based environment for trying prompts, structured outputs, and Gemini behavior quickly.

### Why it is useful

AI Studio is useful for:

- prompt iteration
- extraction prompt design
- schema-output testing
- comparing prompt variants before changing runtime code

### Final usage decision

Use `AI Studio` as the experimentation surface.

Use `Vertex AI` as the production runtime.

That gives you:

- fast iteration in the browser
- stable server-side runtime in Cloud Run

### What to avoid

- do not build the production solver around AI Studio-specific runtime assumptions if Vertex AI is already working
- do not maintain two separate production Gemini call paths unless a benchmarked reason appears

## 2.5 Cloud Shell

### What it is

Google-managed browser-accessible shell and editor environment.

### Why it fits this task

Cloud Shell is especially useful here because:

- `gcloud` is already integrated with your GCP environment
- it reduces local authentication friction
- it is a practical place to deploy Cloud Run and inspect revisions
- it gives you a clean fallback when local tooling becomes inconsistent

### Relevant capabilities

According to Google documentation:

- Cloud Shell includes the Google Cloud CLI
- Cloud Shell is authenticated for the active Google account
- Cloud Shell includes a built-in editor
- Cloud Shell can be used to build, debug, and deploy cloud apps

### Best use

- use Cloud Shell for deploys and operational fixes
- keep deployment commands Cloud Shell-friendly
- use it as the default environment for release work if local `gcloud` becomes unreliable

## 2.6 Compute Engine

### What it is

Virtual machine infrastructure with full OS-level control.

### Why it is not the default

For this Tripletex solver, `Compute Engine` duplicates what `Cloud Run` and `Vertex AI` already solve well:

- public HTTP serving
- deployment simplicity
- integration with Gemini
- low operational overhead

### When it becomes justified

Only consider `Compute Engine` if benchmarking shows a concrete Cloud Run limitation such as:

- memory constraints that materially hurt task success
- runtime constraints that cannot be solved with Cloud Run configuration
- a real need for a persistent custom worker or self-hosted component

### Final usage decision

`Compute Engine` is a reserve option, not part of the baseline architecture.

## 3. Recommended Python Libraries

These are the libraries that fit the approved component set and avoid unnecessary wheel-reinvention.

## 3.1 Core service runtime

- `fastapi`
  - HTTP API and validation
- `uvicorn`
  - ASGI serving
- `pydantic`
  - request and response schemas
- `httpx` or `requests`
  - Tripletex API client

## 3.2 Gemini and Vertex AI

- `google-genai`
  - recommended Gemini SDK for Python
  - appropriate for Vertex AI runtime access

Not recommended as the forward path:

- `vertexai.generative_models`
- older `google-cloud-aiplatform` generative runtime patterns

Reason:

- Google recommends `google-genai`
- the older generative module path is being deprecated

## 3.3 Attachment and normalization helpers

- `pypdf`
  - basic PDF text extraction
- `pymupdf`
  - stronger PDF parsing and page/image access
- `python-dateutil`
  - date parsing
- `rapidfuzz`
  - entity matching and fuzzy resolution
- `orjson`
  - faster JSON serialization if needed

## 3.4 What not to add prematurely

- LangChain
- LlamaIndex
- vector databases
- queue systems
- agent frameworks with large orchestration overhead

Those may be useful later, but they are not required to solve the current Tripletex task set.

## 4. Environment Variables And Credentials

These are the configuration values justified by the restricted component set.

### Required for the baseline runtime

- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_LOCATION`
- `GEMINI_MODEL`
- `TRIPLETEX_API_KEY`
- `CLOUD_RUN_SERVICE_NAME`
- `CLOUD_RUN_REGION`

### Recommended baseline values

- `GEMINI_MODEL=gemini-2.5-pro`
- `CLOUD_RUN_REGION=europe-north1`

## 5. Final Recommendation

Use this stack first:

- `Cloud Run`
- `Vertex AI`
- `gemini-2.5-pro`
- `AI Studio`
- `Cloud Shell`

Keep this as reserve only:

- `Compute Engine`

Do not design around extra GCP services that are not part of the approved free setup.

The simplest strong architecture for this project is:

- Cloud Run for serving
- Vertex AI with Gemini Pro for reasoning
- AI Studio for prompt iteration
- Cloud Shell for deploy and ops

Sources:

- https://docs.cloud.google.com/run/docs/overview/what-is-cloud-run
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/libraries
- https://docs.cloud.google.com/shell/docs/editor-overview
- https://docs.cloud.google.com/compute/docs/overview

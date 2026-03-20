# GCP Components Analysis For The Astar Solver

This document analyzes which Google Cloud components should be used for Astar Island, which ones are optional, and which combinations would duplicate each other.

It is based on:

- the NM i AI Astar task docs
- the NM i AI Google Cloud docs
- official Google Cloud and Google AI documentation

Primary sources:

- https://app.ainm.no/docs/google-cloud/overview
- https://app.ainm.no/docs/google-cloud/deploy
- https://app.ainm.no/docs/google-cloud/services
- https://cloud.google.com/run/docs/create-jobs
- https://cloud.google.com/run/docs/execute/jobs-on-schedule
- https://cloud.google.com/run/docs/configuring/request-timeout
- https://cloud.google.com/run/docs/about-concurrency
- https://cloud.google.com/shell/docs/how-cloud-shell-works
- https://cloud.google.com/shell/docs/editor-overview
- https://cloud.google.com/python/docs/reference/storage/latest
- https://cloud.google.com/python/docs/reference/bigquery/latest
- https://cloud.google.com/python/docs/reference/secretmanager/latest
- https://cloud.google.com/python/docs/reference/logging/latest
- https://cloud.google.com/python/docs/reference/pubsub/latest
- https://cloud.google.com/vertex-ai/generative-ai/docs/sdks/overview
- https://ai.google.dev/gemini-api/docs/ai-studio-quickstart
- https://cloud.google.com/compute/docs/gpus

## 1. Recommended High-Level Stack

Recommended primary stack for Astar:

1. `Cloud Run Jobs` for round-time batch execution
2. `Cloud Scheduler` for timed or repeated job execution
3. `Cloud Storage` for artifacts and round evidence
4. `Secret Manager` for `AINM_ACCESS_TOKEN` in deployed runs
5. `Cloud Logging` for execution traces
6. `Cloud Shell` and `Cloud Shell Editor` for daily ops and deployment

Recommended optional components:

1. `BigQuery` for cross-round analytics and feature store tables
2. `Pub/Sub` only if you split orchestration into multiple workers
3. `Vertex AI Gemini` or `Google AI Studio` only for experiment assistance, summarization, or code generation, not as the primary prediction engine
4. `Compute Engine` only if you move into GPU-heavy training or long-running background infrastructure

Not recommended as the default Astar runtime path:

1. `Cloud Run service` as the main submission interface
2. `Compute Engine` before the batch workflow is proven
3. `AI Studio API keys` as the main production runtime if Vertex AI is available
4. a custom database before Cloud Storage or BigQuery is actually insufficient

## 2. Important Competition-Specific Clarification

The NM i AI generic Google Cloud deploy page still says Astar needs a public HTTPS `/solve` endpoint.

That is inconsistent with:

- the Astar task docs
- the local Astar scaffold
- the actual API contract

For Astar, the organizer submission path is:

- your code calls `https://api.ainm.no/astar-island/...`

That means:

- you do not need a public solver endpoint to submit Astar predictions
- you need a reliable internal batch runner

That is why `Cloud Run Jobs` is the right first GCP component, not a public Cloud Run service.

## 3. Component Decision Matrix

## 3.1 Cloud Run Jobs

### Description

Managed container execution for finite batch work.

### Why it fits Astar

Astar is a round worker problem:

- fetch active round
- gather observations
- build predictions
- submit tensors
- exit

That is a job, not a long-lived public service.

### Relevant capabilities

Official Cloud Run docs state:

- jobs can be structured as one task or many independent tasks
- jobs can scale up to `10,000` tasks
- tasks can run in parallel using `--parallelism`
- default task timeout is `10 minutes`
- task timeout can be extended up to `168 hours`
- jobs support environment variables and secrets
- jobs can be executed on a schedule using Cloud Scheduler

### Usage instructions

Use Cloud Run Jobs for:

- round collection
- batch simulation sampling
- periodic resubmission runs
- replaying finished rounds for analysis

Recommended first settings:

- `tasks=1`
- `parallelism=1`
- `cpu=1`
- `memory=1Gi`
- `task-timeout=900s`

Keep it single-task until you have a real reason to shard work.

### Python libraries

- no special Python SDK is required for in-container execution
- deployment can stay on `gcloud`
- if you need programmatic admin access later, `google-cloud-run` exists

### Credentials and env

Store in deployed config:

- the active `gcloud` project or `GOOGLE_CLOUD_PROJECT`

Prefer `Secret Manager` for:

- `AINM_ACCESS_TOKEN`

Prefer hard-coded defaults or CLI flags for:

- stable Astar runtime knobs such as base URL, viewport size, floor, and prior strength

In this scaffold, the Cloud Run Job deployment path intentionally hard-codes the non-secret deployment settings and looks for a fixed Secret Manager secret name, `astar-access-token`.

### Duplicate to avoid

- running the same round worker as both a Cloud Run service and a Cloud Run job
- provisioning Compute Engine just to run the same container on a timer

## 3.2 Cloud Scheduler

### Description

Managed cron-style triggering for Google Cloud targets.

### Why it fits Astar

Astar has round windows and repeated polling needs:

- start a batch job at fixed intervals
- re-run during active rounds
- trigger analysis jobs after completion

### Relevant capabilities

Official docs state:

- Cloud Run jobs can be executed on a schedule using Cloud Scheduler
- schedules use unix cron syntax
- Scheduler can invoke authenticated HTTP targets using a service account and OIDC

### Usage instructions

Use Cloud Scheduler for:

- every-10-minute active-round polling
- every-30-minute observation runs
- post-round analysis sync

If you only need one batch worker, a Scheduler -> Cloud Run Job chain is enough.

### Python libraries

- none required if you manage schedules with `gcloud`
- if you need programmatic control later, `google-cloud-scheduler` is available

### Credentials and env

You need:

- a service account in the same project
- the right invoker or execution permissions

### Duplicate to avoid

- building your own cron VM
- using Pub/Sub for simple time-based triggering when Scheduler is enough

## 3.3 Cloud Storage

### Description

Object storage for files and artifacts.

### Why it fits Astar

Astar produces file-like assets naturally:

- round detail JSON
- simulation viewport results
- prediction payloads
- submit responses
- post-round analysis dumps

Cloud Storage is the simplest persistent place for those artifacts.

### Relevant capabilities

The official Python client library is:

- `google-cloud-storage`

### Usage instructions

Use Cloud Storage for:

- raw artifact retention
- cross-run reproducibility
- sharing round evidence across teammates and workers

Recommended layout:

- `gs://<bucket>/astar/<round_id>/public/...`
- `gs://<bucket>/astar/<round_id>/team/...`
- `gs://<bucket>/astar/<round_id>/predictions/...`

### Python libraries

- `google-cloud-storage`

### Credentials and env

Use:

- `GCS_ARTIFACTS_BUCKET`

`GCS_ARTIFACTS_PREFIX` can stay hard-coded unless you actively need multiple prefixes.

In this scaffold, GCS artifact upload is exposed as an explicit CLI option on the local runner instead of a deployment-time `.env` variable.

Cloud Run and Cloud Shell should authenticate through ADC.

### Duplicate to avoid

- writing custom blob upload wrappers when `google-cloud-storage` already solves it
- putting raw JSON artifacts into BigQuery before you know you need SQL analytics

## 3.4 Secret Manager

### Description

Managed secret storage.

### Why it fits Astar

The main secret for deployed Astar automation is:

- `AINM_ACCESS_TOKEN`

This should not be hardcoded into the container image or committed to git.

### Relevant capabilities

Official docs describe Secret Manager as storing, managing, and securing application secrets.

The official Python client library is:

- `google-cloud-secret-manager`

### Usage instructions

Use Secret Manager for:

- AINM access token in Cloud Run Jobs
- any future webhook or alerting credentials

Use `.env` only for local dev.

### Python libraries

- `google-cloud-secret-manager`

### Credentials and env

Useful env:

- `ASTAR_TOKEN_SECRET_NAME`

### Duplicate to avoid

- putting live secrets into source control
- storing deployment secrets only in `.env` on Cloud Shell

## 3.5 Cloud Logging

### Description

Managed logs for Cloud Run and other GCP resources.

### Why it fits Astar

You need to debug:

- budget usage
- simulation failures
- auth issues
- submission timing
- model outputs per round

Cloud Run already emits stdout/stderr into Cloud Logging, so this comes almost for free.

### Relevant capabilities

The official Python client library is:

- `google-cloud-logging`

### Usage instructions

For the first version:

- rely on structured stdout logs from the worker

Only add the Python logging client if you need:

- custom handlers
- structured fields beyond basic stdout JSON

### Python libraries

- optional: `google-cloud-logging`

### Credentials and env

- none beyond normal project auth

### Duplicate to avoid

- building a separate logging stack before reading Cloud Logging first

## 3.6 Cloud Shell And Cloud Shell Editor

### Description

Google-managed development environment with terminal and browser editor.

### Why it fits Astar

The official docs state:

- Cloud Shell gives you `5 GB` of persistent `$HOME` storage
- it comes with the latest `gcloud` CLI and many utilities preinstalled
- `uv` is preinstalled
- Cloud Shell Editor is based on `Code OSS`
- Cloud Shell currently includes Python `3.12`

This is ideal for:

- fast deployment
- artifact inspection
- log review
- ad hoc reruns without local machine setup issues

### Usage instructions

Use Cloud Shell for:

- one-off round runs
- `gcloud` deployment
- log inspection
- rapid iteration when local GCP auth is messy

Use Cloud Shell Editor for:

- lightweight code edits
- integrated Git operations
- Cloud Code support

### Python libraries

- no extra cloud SDK needed beyond what your project requires

### Credentials and env

Cloud Shell sets:

- `GOOGLE_CLOUD_PROJECT`

and authenticates `gcloud` and ADC for you after authorization.

### Duplicate to avoid

- provisioning a separate dev VM before Cloud Shell becomes a bottleneck

## 3.7 BigQuery

### Description

Managed analytical warehouse.

### Why it is useful

BigQuery becomes valuable once you have many completed rounds and want:

- SQL over simulation samples
- aggregate error analysis from `/analysis`
- feature tables for training
- team-facing dashboards

### Relevant capabilities

The official Python client library is:

- `google-cloud-bigquery`

### Usage instructions

Do not start with BigQuery as the only artifact store.

Start with:

- raw JSON in Cloud Storage

Add BigQuery when you actually need:

- joins
- grouped analysis
- model training tables

### Python libraries

- `google-cloud-bigquery`
- optionally `pandas` or `polars` on top

### Credentials and env

- normal ADC is enough

### Duplicate to avoid

- storing the same raw artifacts in both Cloud Storage and BigQuery from day one

## 3.8 Pub/Sub

### Description

Managed messaging for decoupled workers.

### Why it is optional

Pub/Sub is only useful if you split the system into multiple independent components, such as:

- round detector
- simulation worker
- training worker
- analysis writer

For a single-worker Astar scaffold, Pub/Sub is unnecessary complexity.

### Relevant capabilities

The official Python client library is:

- `google-cloud-pubsub`

### Usage instructions

Only add Pub/Sub if:

- Cloud Scheduler -> one Cloud Run Job is no longer enough
- you want fan-out processing
- you want asynchronous post-round pipelines

### Python libraries

- `google-cloud-pubsub`

### Duplicate to avoid

- using Pub/Sub when a single job execution already solves the workflow

## 3.9 Vertex AI Gemini

### Description

Managed Gemini access inside Google Cloud.

### Why it is optional for Astar

Astar is mostly a numerical modeling task, not a natural-language planning task.

Gemini is not the primary prediction engine here.

It can still help with:

- experiment summarization
- hypothesis generation
- code generation
- post-round report writing
- qualitative interpretation of learned patterns

### Relevant capabilities

Official Vertex AI SDK docs state:

- Gemini Developer API and Vertex AI are both supported by the Gen AI SDK
- the recommended Python SDK is `google-genai`
- install with `pip install --upgrade google-genai`

Note that the NM i AI Google Cloud services page still shows a `google-cloud-aiplatform`
install example for Vertex AI. For new Gemini work, the current official Vertex SDK
guidance points to `google-genai`, so that is the better default for this repo.

### Usage instructions

Use Vertex AI only if you have a clearly bounded support use case.

Do not route the core terrain prediction problem through an LLM by default.

### Python libraries

- `google-genai`

### Duplicate to avoid

- mixing `google-genai` with older Vertex generative stacks unless you have to
- treating Gemini as a replacement for actual probabilistic modeling

## 3.10 Google AI Studio

### Description

Browser environment for trying Gemini prompts and getting starter code.

### Why it is useful

Official docs say AI Studio lets you:

- quickly try out models
- use "Get code"
- experiment with structured output
- experiment with function calling
- experiment with code execution

### Why it is not the main runtime path

For this repo, AI Studio is a prototyping tool.

If you deploy Gemini-backed helpers in GCP, Vertex AI is the cleaner production target because it stays inside the same cloud project and auth model.

### Duplicate to avoid

- using both AI Studio API keys and Vertex AI for the same production path without a reason

## 3.11 Compute Engine

### Description

General-purpose VMs, including GPU-capable instance types.

### Why it is optional

Official Compute Engine GPU docs show support for accelerator-optimized GPU machine families and GPU-oriented workloads.

This becomes relevant only if you later need:

- GPU-heavy training
- persistent background workers
- specialized native stacks that do not fit Cloud Run well

For the current scaffold, you do not need it.

### Usage instructions

Move to Compute Engine only if:

1. you have a real GPU training workload
2. Cloud Run Jobs no longer fit your runtime shape
3. you need persistent infrastructure

### Python libraries

- no special mandatory library
- keep model code portable first

### Duplicate to avoid

- using Compute Engine as your default runner while also keeping a Cloud Run Job doing the same work

## 4. Recommended Python Library Set

## 4.1 Libraries the scaffold should actually use now

- `requests` for the AINM REST API
- `numpy` for tensors and posterior blending
- `python-dotenv` for local `.env` loading
- `google-cloud-storage` for optional artifact upload

## 4.2 Libraries worth using when the solver grows

- `scipy` for statistical tooling
- `pandas` or `polars` for analysis tables
- `scikit-learn` for classical models and calibration
- `google-cloud-bigquery` for SQL analytics
- `google-cloud-secret-manager` for programmatic secret access
- `google-cloud-logging` for custom structured logging
- `google-cloud-pubsub` only if orchestration is split
- `google-genai` only for optional Gemini-assisted workflows

## 4.3 Libraries to avoid duplicating

Avoid introducing multiple libraries that solve the same problem at the same layer:

- `Cloud Run Job` plus a separate always-on `Cloud Run service` for the same batch task
- `Cloud Storage` plus a custom file sync system
- `Secret Manager` plus checked-in secret files
- `Vertex AI` plus `AI Studio` keys in the same production path
- `requests` and `httpx` both in the same small scaffold unless there is a strong reason

## 5. Final Recommendation

Build Astar around this minimal GCP stack:

1. `Cloud Run Jobs`
2. `Cloud Scheduler`
3. `Cloud Storage`
4. `Secret Manager`
5. `Cloud Logging`
6. `Cloud Shell`

Add:

7. `BigQuery`

only when cross-round analytics justify it.

Add:

8. `Compute Engine`

only when you have a proven GPU or persistent-worker requirement.

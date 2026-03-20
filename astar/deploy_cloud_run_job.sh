#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

: "${GOOGLE_CLOUD_PROJECT:?GOOGLE_CLOUD_PROJECT is required}"

JOB_NAME="${CLOUD_RUN_JOB_NAME:-astar-round-worker}"
REGION="${CLOUD_RUN_REGION:-europe-north1}"
LOCATION="${GOOGLE_CLOUD_LOCATION:-europe-north1}"
CPU="${CLOUD_RUN_JOB_CPU:-1}"
MEMORY="${CLOUD_RUN_JOB_MEMORY:-1Gi}"
TASK_TIMEOUT="${CLOUD_RUN_JOB_TASK_TIMEOUT:-900s}"
SERVICE_ACCOUNT="${CLOUD_RUN_SERVICE_ACCOUNT:-}"
IMAGE_URI="gcr.io/${GOOGLE_CLOUD_PROJECT}/${JOB_NAME}:latest"

ENV_VARS=(
  "GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT}"
  "GOOGLE_CLOUD_LOCATION=${LOCATION}"
  "AINM_BASE_URL=${AINM_BASE_URL:-https://api.ainm.no}"
  "ASTAR_ROUND_ID=${ASTAR_ROUND_ID:-}"
  "ASTAR_OUTPUT_DIR=${ASTAR_OUTPUT_DIR:-/tmp/astar-artifacts}"
  "ASTAR_SUBMIT=${ASTAR_SUBMIT:-false}"
  "ASTAR_SIMULATE=${ASTAR_SIMULATE:-false}"
  "ASTAR_QUERIES_PER_SEED=${ASTAR_QUERIES_PER_SEED:-4}"
  "ASTAR_VIEWPORT_SIZE=${ASTAR_VIEWPORT_SIZE:-15}"
  "ASTAR_PREDICTION_FLOOR=${ASTAR_PREDICTION_FLOOR:-0.01}"
  "ASTAR_OBSERVATION_PRIOR_STRENGTH=${ASTAR_OBSERVATION_PRIOR_STRENGTH:-2.0}"
  "GCS_ARTIFACTS_BUCKET=${GCS_ARTIFACTS_BUCKET:-}"
  "GCS_ARTIFACTS_PREFIX=${GCS_ARTIFACTS_PREFIX:-astar}"
)

SECRET_FLAGS=()
if [[ -n "${ASTAR_TOKEN_SECRET_NAME:-}" ]]; then
  SECRET_FLAGS+=(--set-secrets "AINM_ACCESS_TOKEN=${ASTAR_TOKEN_SECRET_NAME}:latest")
elif [[ -n "${AINM_ACCESS_TOKEN:-}" ]]; then
  ENV_VARS+=("AINM_ACCESS_TOKEN=${AINM_ACCESS_TOKEN}")
fi

SERVICE_ACCOUNT_FLAG=()
if [[ -n "${SERVICE_ACCOUNT}" ]]; then
  SERVICE_ACCOUNT_FLAG+=(--service-account "${SERVICE_ACCOUNT}")
fi

echo "Building ${IMAGE_URI}"
gcloud --quiet config set project "${GOOGLE_CLOUD_PROJECT}"
gcloud builds submit "${ROOT_DIR}" --tag "${IMAGE_URI}"

echo "Deploying Cloud Run Job ${JOB_NAME} to ${REGION}"
gcloud run jobs deploy "${JOB_NAME}" \
  --quiet \
  --project "${GOOGLE_CLOUD_PROJECT}" \
  --region "${REGION}" \
  --image "${IMAGE_URI}" \
  --cpu "${CPU}" \
  --memory "${MEMORY}" \
  --task-timeout "${TASK_TIMEOUT}" \
  --tasks 1 \
  --parallelism 1 \
  --max-retries 0 \
  --set-env-vars "$(IFS=,; echo "${ENV_VARS[*]}")" \
  "${SERVICE_ACCOUNT_FLAG[@]}" \
  "${SECRET_FLAGS[@]}"

echo "To execute now:"
echo "gcloud run jobs execute ${JOB_NAME} --region ${REGION} --project ${GOOGLE_CLOUD_PROJECT}"

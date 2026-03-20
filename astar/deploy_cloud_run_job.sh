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

PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
: "${PROJECT:?Set an active gcloud project or export GOOGLE_CLOUD_PROJECT.}"

JOB_NAME="astar-round-worker"
REGION="europe-north1"
LOCATION="europe-north1"
CPU="1"
MEMORY="1Gi"
TASK_TIMEOUT="900s"
SECRET_NAME="astar-access-token"
IMAGE_URI="gcr.io/${PROJECT}/${JOB_NAME}:latest"

ENV_VARS=(
  "GOOGLE_CLOUD_PROJECT=${PROJECT}"
  "GOOGLE_CLOUD_LOCATION=${LOCATION}"
  "AINM_BASE_URL=https://api.ainm.no"
)

if [[ -n "${AINM_ACCESS_TOKEN:-}" ]]; then
  ENV_VARS+=("AINM_ACCESS_TOKEN=${AINM_ACCESS_TOKEN}")
else
  echo "AINM_ACCESS_TOKEN is required for deployment." >&2
  echo "Set it in astar/.env before running this script." >&2
  exit 1
fi

echo "Building ${IMAGE_URI}"
gcloud --quiet config set project "${PROJECT}"
gcloud builds submit "${ROOT_DIR}" --tag "${IMAGE_URI}"

echo "Deploying Cloud Run Job ${JOB_NAME} to ${REGION}"
gcloud run jobs deploy "${JOB_NAME}" \
  --quiet \
  --project "${PROJECT}" \
  --region "${REGION}" \
  --image "${IMAGE_URI}" \
  --cpu "${CPU}" \
  --memory "${MEMORY}" \
  --task-timeout "${TASK_TIMEOUT}" \
  --tasks 1 \
  --parallelism 1 \
  --max-retries 0 \
  --set-env-vars "$(IFS=,; echo "${ENV_VARS[*]}")"

echo "To execute now:"
echo "gcloud run jobs execute ${JOB_NAME} --region ${REGION} --project ${PROJECT}"

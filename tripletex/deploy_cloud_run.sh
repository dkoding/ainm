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

SERVICE_NAME="${CLOUD_RUN_SERVICE_NAME:-tripletex-agent}"
REGION="${CLOUD_RUN_REGION:-europe-north1}"
LOCATION="${GOOGLE_CLOUD_LOCATION:-europe-north1}"
MODEL="${GEMINI_MODEL:-gemini-2.5-pro}"
MAX_STEPS="${TRIPLETEX_MAX_STEPS:-12}"
MAX_PLANNER_STEPS="${TRIPLETEX_MAX_PLANNER_STEPS:-${TRIPLETEX_MAX_STEPS:-12}}"
MAX_API_CALLS="${TRIPLETEX_MAX_API_CALLS:-${TRIPLETEX_MAX_STEPS:-12}}"
REQUEST_TIMEOUT="${TRIPLETEX_REQUEST_TIMEOUT:-30}"
ALLOW_NOOP="${TRIPLETEX_ALLOW_NOOP:-false}"
API_KEY="${TRIPLETEX_API_KEY:-}"

ENV_VARS=(
  "GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT}"
  "GOOGLE_CLOUD_LOCATION=${LOCATION}"
  "GEMINI_MODEL=${MODEL}"
  "TRIPLETEX_API_KEY=${API_KEY}"
  "TRIPLETEX_MAX_PLANNER_STEPS=${MAX_PLANNER_STEPS}"
  "TRIPLETEX_MAX_API_CALLS=${MAX_API_CALLS}"
  "TRIPLETEX_MAX_STEPS=${MAX_STEPS}"
  "TRIPLETEX_REQUEST_TIMEOUT=${REQUEST_TIMEOUT}"
  "TRIPLETEX_ALLOW_NOOP=${ALLOW_NOOP}"
)

echo "Deploying ${SERVICE_NAME} to project ${GOOGLE_CLOUD_PROJECT} in ${REGION}"

gcloud --quiet config set project "${GOOGLE_CLOUD_PROJECT}"
gcloud run deploy "${SERVICE_NAME}" \
  --quiet \
  --project "${GOOGLE_CLOUD_PROJECT}" \
  --source "${ROOT_DIR}" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 300 \
  --set-env-vars "$(IFS=,; echo "${ENV_VARS[*]}")"

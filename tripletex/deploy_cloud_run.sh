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
LOG_LEVEL="${LOG_LEVEL:-INFO}"
REQUEST_TIMEOUT="${TRIPLETEX_REQUEST_TIMEOUT:-30}"
API_KEY="${TRIPLETEX_API_KEY:-}"
WHO_AM_I_FIELDS="${TRIPLETEX_WHOAMI_FIELDS:-}"
ENV_SPEC="^##^LOG_LEVEL=${LOG_LEVEL}##TRIPLETEX_API_KEY=${API_KEY}##TRIPLETEX_REQUEST_TIMEOUT=${REQUEST_TIMEOUT}##TRIPLETEX_WHOAMI_FIELDS=${WHO_AM_I_FIELDS}"

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
  --set-env-vars "${ENV_SPEC}"

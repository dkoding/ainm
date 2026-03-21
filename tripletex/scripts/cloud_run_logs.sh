#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

SERVICE_NAME="${CLOUD_RUN_SERVICE_NAME:-tripletex-agent}"
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-}"
REGION="${CLOUD_RUN_REGION:-europe-north1}"
MODE="${1:-tail}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "GOOGLE_CLOUD_PROJECT is required." >&2
  exit 1
fi

usage() {
  cat <<EOF
Usage:
  scripts/cloud_run_logs.sh tail [LOG_FILTER]
  scripts/cloud_run_logs.sh read [LIMIT]
  scripts/cloud_run_logs.sh errors
  scripts/cloud_run_logs.sh json [LIMIT]

Defaults come from .env:
  CLOUD_RUN_SERVICE_NAME=${SERVICE_NAME}
  GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
  CLOUD_RUN_REGION=${REGION}

Examples:
  scripts/cloud_run_logs.sh tail
  scripts/cloud_run_logs.sh tail 'severity>=ERROR'
  scripts/cloud_run_logs.sh read 50
  scripts/cloud_run_logs.sh errors
  scripts/cloud_run_logs.sh json 20
EOF
}

case "${MODE}" in
  tail)
    FILTER="${2:-}"
    if [[ -n "${FILTER}" ]]; then
      exec gcloud beta run services logs tail "${SERVICE_NAME}" \
        --project "${PROJECT_ID}" \
        --region "${REGION}" \
        --log-filter "${FILTER}"
    fi
    exec gcloud beta run services logs tail "${SERVICE_NAME}" \
      --project "${PROJECT_ID}" \
      --region "${REGION}"
    ;;
  read)
    LIMIT="${2:-50}"
    exec gcloud run services logs read "${SERVICE_NAME}" \
      --project "${PROJECT_ID}" \
      --region "${REGION}" \
      --limit "${LIMIT}"
    ;;
  errors)
    exec gcloud beta run services logs tail "${SERVICE_NAME}" \
      --project "${PROJECT_ID}" \
      --region "${REGION}" \
      --log-filter 'severity>=ERROR'
    ;;
  json)
    LIMIT="${2:-50}"
    exec gcloud logging read \
      "resource.type=cloud_run_revision AND resource.labels.service_name=\"${SERVICE_NAME}\"" \
      --project "${PROJECT_ID}" \
      --limit "${LIMIT}" \
      --format json
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "Unknown mode: ${MODE}" >&2
    usage >&2
    exit 1
    ;;
esac

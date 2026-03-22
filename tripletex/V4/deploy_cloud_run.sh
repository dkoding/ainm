#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
LOG_DIR="${ROOT_DIR}/artifacts/cloud_run_logs"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

: "${GOOGLE_CLOUD_PROJECT:?GOOGLE_CLOUD_PROJECT is required}"

SERVICE_NAME="${CLOUD_RUN_SERVICE_NAME:-tripletex-agent-v4}"
REGION="${CLOUD_RUN_REGION:-europe-north1}"
GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.5-pro}"
GEMINI_TIMEOUT_SECONDS="${GEMINI_TIMEOUT_SECONDS:-3600}"
GEMINI_THINKING_BUDGET="${GEMINI_THINKING_BUDGET:-32768}"
GEMINI_MAX_OUTPUT_TOKENS="${GEMINI_MAX_OUTPUT_TOKENS:-65536}"
GEMINI_FALLBACK_MODEL="${GEMINI_FALLBACK_MODEL:-}"
GEMINI_FALLBACK_LOCATION="${GEMINI_FALLBACK_LOCATION:-${GOOGLE_CLOUD_LOCATION}}"
GEMINI_FALLBACK_TIMEOUT_SECONDS="${GEMINI_FALLBACK_TIMEOUT_SECONDS:-${GEMINI_TIMEOUT_SECONDS}}"
GEMINI_FALLBACK_THINKING_BUDGET="${GEMINI_FALLBACK_THINKING_BUDGET:-${GEMINI_THINKING_BUDGET}}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
REQUEST_TIMEOUT="${TRIPLETEX_REQUEST_TIMEOUT:-30}"
API_KEY="${TRIPLETEX_API_KEY:-}"
WHO_AM_I_FIELDS="${TRIPLETEX_WHOAMI_FIELDS:-}"
TIMEZONE="${TRIPLETEX_TIMEZONE:-Europe/Oslo}"
ENV_SPEC="^##^GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT}##GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION}##GEMINI_MODEL=${GEMINI_MODEL}##GEMINI_TIMEOUT_SECONDS=${GEMINI_TIMEOUT_SECONDS}##GEMINI_THINKING_BUDGET=${GEMINI_THINKING_BUDGET}##GEMINI_MAX_OUTPUT_TOKENS=${GEMINI_MAX_OUTPUT_TOKENS}##GEMINI_FALLBACK_MODEL=${GEMINI_FALLBACK_MODEL}##GEMINI_FALLBACK_LOCATION=${GEMINI_FALLBACK_LOCATION}##GEMINI_FALLBACK_TIMEOUT_SECONDS=${GEMINI_FALLBACK_TIMEOUT_SECONDS}##GEMINI_FALLBACK_THINKING_BUDGET=${GEMINI_FALLBACK_THINKING_BUDGET}##LOG_LEVEL=${LOG_LEVEL}##TRIPLETEX_API_KEY=${API_KEY}##TRIPLETEX_REQUEST_TIMEOUT=${REQUEST_TIMEOUT}##TRIPLETEX_WHOAMI_FIELDS=${WHO_AM_I_FIELDS}##TRIPLETEX_TIMEZONE=${TIMEZONE}"
LOG_FILE="${LOG_DIR}/${SERVICE_NAME}.log"
LOG_PID_FILE="${LOG_DIR}/${SERVICE_NAME}.pid"
LOG_TAIL_PATTERN="${ROOT_DIR}/scripts/cloud_run_logs.sh tail"


stop_existing_log_tail() {
  mkdir -p "${LOG_DIR}"

  declare -A seen_pids=()
  local pid=""

  if [[ -f "${LOG_PID_FILE}" ]]; then
    pid="$(tr -d '[:space:]' < "${LOG_PID_FILE}")"
    if [[ -n "${pid}" ]]; then
      seen_pids["${pid}"]=1
    fi
  fi

  while IFS= read -r pid; do
    if [[ -n "${pid}" ]]; then
      seen_pids["${pid}"]=1
    fi
  done < <(pgrep -f "${LOG_TAIL_PATTERN}" || true)

  for pid in "${!seen_pids[@]}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      echo "Stopping existing log tail process ${pid}"
      kill "${pid}" 2>/dev/null || true
      sleep 1
      if kill -0 "${pid}" 2>/dev/null; then
        echo "Force stopping stubborn log tail process ${pid}"
        kill -9 "${pid}" 2>/dev/null || true
      fi
    fi
  done

  rm -f "${LOG_PID_FILE}"
}


start_log_tail() {
  mkdir -p "${LOG_DIR}"
  {
    echo
    echo "[$(date -Iseconds)] Starting Cloud Run log tail"
    echo "service=${SERVICE_NAME} project=${GOOGLE_CLOUD_PROJECT} region=${REGION}"
  } >> "${LOG_FILE}"

  nohup setsid bash "${ROOT_DIR}/scripts/cloud_run_logs.sh" tail >> "${LOG_FILE}" 2>&1 < /dev/null &
  local pid=$!
  echo "${pid}" > "${LOG_PID_FILE}"
  sleep 2
  if kill -0 "${pid}" 2>/dev/null; then
    echo "Collecting Cloud Run logs in ${LOG_FILE} (pid ${pid})"
  else
    echo "Log tail process exited immediately. Check ${LOG_FILE}" >&2
    return 1
  fi
}

echo "Deploying ${SERVICE_NAME} to project ${GOOGLE_CLOUD_PROJECT} in ${REGION}"

stop_existing_log_tail
gcloud --quiet config set project "${GOOGLE_CLOUD_PROJECT}"
gcloud run deploy "${SERVICE_NAME}" \
  --quiet \
  --project "${GOOGLE_CLOUD_PROJECT}" \
  --source "${ROOT_DIR}" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 3600 \
  --set-env-vars "${ENV_SPEC}"
start_log_tail

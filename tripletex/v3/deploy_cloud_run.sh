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

SERVICE_NAME="${CLOUD_RUN_SERVICE_NAME:-tripletex-agent-v3}"
REGION="${CLOUD_RUN_REGION:-europe-north1}"
GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-${REGION}}"
GEMINI_MODEL="${V3_GEMINI_MODEL:-${GEMINI_MODEL:-gemini-2.5-pro}}"
GEMINI_TIMEOUT_SECONDS="${V3_GEMINI_TIMEOUT_SECONDS:-240}"
GEMINI_THINKING_BUDGET="${V3_GEMINI_THINKING_BUDGET:-32768}"
GEMINI_MAX_OUTPUT_TOKENS="${V3_GEMINI_MAX_OUTPUT_TOKENS:-65535}"
GEMINI_FALLBACK_MODEL="${V3_GEMINI_FALLBACK_MODEL:-}"
GEMINI_FALLBACK_LOCATION="${V3_GEMINI_FALLBACK_LOCATION:-${REGION}}"
GEMINI_FALLBACK_TIMEOUT_SECONDS="${V3_GEMINI_FALLBACK_TIMEOUT_SECONDS:-180}"
GEMINI_FALLBACK_THINKING_BUDGET="${V3_GEMINI_FALLBACK_THINKING_BUDGET:-32768}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
REQUEST_TIMEOUT="${TRIPLETEX_REQUEST_TIMEOUT:-30}"
API_KEY="${TRIPLETEX_API_KEY:-}"
WHO_AM_I_FIELDS="${TRIPLETEX_WHOAMI_FIELDS:-}"
TIMEZONE="${TRIPLETEX_TIMEZONE:-Europe/Oslo}"
RETRIEVAL_BACKEND="${TRIPLETEX_RETRIEVAL_BACKEND:-local}"
RETRIEVAL_FLOW_LIMIT="${TRIPLETEX_RETRIEVAL_FLOW_LIMIT:-12}"
RETRIEVAL_COMMAND_LIMIT="${TRIPLETEX_RETRIEVAL_COMMAND_LIMIT:-40}"
RETRIEVAL_RAW_LIMIT="${TRIPLETEX_RETRIEVAL_RAW_LIMIT:-120}"
RETRIEVAL_QUERY_TERM_LIMIT="${TRIPLETEX_RETRIEVAL_QUERY_TERM_LIMIT:-40}"
VERTEX_RAG_CORPUS="${TRIPLETEX_VERTEX_RAG_CORPUS:-}"
VERTEX_RAG_ENDPOINT="${TRIPLETEX_VERTEX_RAG_ENDPOINT:-https://aiplatform.googleapis.com}"
VERTEX_RAG_TOP_K="${TRIPLETEX_VERTEX_RAG_TOP_K:-64}"
VERTEX_RAG_TIMEOUT_SECONDS="${TRIPLETEX_VERTEX_RAG_TIMEOUT_SECONDS:-10}"
ENV_SPEC="^##^GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT}##GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION}##GEMINI_MODEL=${GEMINI_MODEL}##GEMINI_TIMEOUT_SECONDS=${GEMINI_TIMEOUT_SECONDS}##GEMINI_THINKING_BUDGET=${GEMINI_THINKING_BUDGET}##GEMINI_MAX_OUTPUT_TOKENS=${GEMINI_MAX_OUTPUT_TOKENS}##GEMINI_FALLBACK_MODEL=${GEMINI_FALLBACK_MODEL}##GEMINI_FALLBACK_LOCATION=${GEMINI_FALLBACK_LOCATION}##GEMINI_FALLBACK_TIMEOUT_SECONDS=${GEMINI_FALLBACK_TIMEOUT_SECONDS}##GEMINI_FALLBACK_THINKING_BUDGET=${GEMINI_FALLBACK_THINKING_BUDGET}##LOG_LEVEL=${LOG_LEVEL}##TRIPLETEX_API_KEY=${API_KEY}##TRIPLETEX_REQUEST_TIMEOUT=${REQUEST_TIMEOUT}##TRIPLETEX_WHOAMI_FIELDS=${WHO_AM_I_FIELDS}##TRIPLETEX_TIMEZONE=${TIMEZONE}##TRIPLETEX_RETRIEVAL_BACKEND=${RETRIEVAL_BACKEND}##TRIPLETEX_RETRIEVAL_FLOW_LIMIT=${RETRIEVAL_FLOW_LIMIT}##TRIPLETEX_RETRIEVAL_COMMAND_LIMIT=${RETRIEVAL_COMMAND_LIMIT}##TRIPLETEX_RETRIEVAL_RAW_LIMIT=${RETRIEVAL_RAW_LIMIT}##TRIPLETEX_RETRIEVAL_QUERY_TERM_LIMIT=${RETRIEVAL_QUERY_TERM_LIMIT}##TRIPLETEX_VERTEX_RAG_CORPUS=${VERTEX_RAG_CORPUS}##TRIPLETEX_VERTEX_RAG_ENDPOINT=${VERTEX_RAG_ENDPOINT}##TRIPLETEX_VERTEX_RAG_TOP_K=${VERTEX_RAG_TOP_K}##TRIPLETEX_VERTEX_RAG_TIMEOUT_SECONDS=${VERTEX_RAG_TIMEOUT_SECONDS}"
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
  --timeout 300 \
  --set-env-vars "${ENV_SPEC}"
start_log_tail

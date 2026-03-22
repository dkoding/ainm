#!/usr/bin/env bash
set -euo pipefail
export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_PAGER=

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
POLL_SECONDS="${CLOUD_RUN_LOG_POLL_SECONDS:-5}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "GOOGLE_CLOUD_PROJECT is required." >&2
  exit 1
fi

build_query() {
  local extra_filter="${1:-}"
  local query
  query="resource.type=cloud_run_revision AND resource.labels.service_name=\"${SERVICE_NAME}\""
  if [[ -n "${REGION}" ]]; then
    query="${query} AND resource.labels.location=\"${REGION}\""
  fi
  if [[ -n "${extra_filter}" ]]; then
    query="${query} AND (${extra_filter})"
  fi
  printf '%s' "${query}"
}

tail_logs() {
  local extra_filter="${1:-}"
  local state_file cursor_file base_query now cursor tmp_json
  state_file="$(mktemp)"
  cursor_file="$(mktemp)"
  trap 'rm -f "${state_file}" "${cursor_file}"' EXIT
  : > "${state_file}"
  now="$(date -u -Iseconds -d '2 minutes ago')"
  printf '%s' "${now}" > "${cursor_file}"
  base_query="$(build_query "${extra_filter}")"

  while true; do
    cursor="$(cat "${cursor_file}")"
    tmp_json="$(mktemp)"
    if gcloud logging read \
      "${base_query} AND timestamp>=\"${cursor}\"" \
      --project "${PROJECT_ID}" \
      --limit 200 \
      --order=asc \
      --format json > "${tmp_json}"; then
      python3 - "${tmp_json}" "${state_file}" "${cursor_file}" <<'PY'
import json
import sys
from pathlib import Path

payload_path = Path(sys.argv[1])
state_path = Path(sys.argv[2])
cursor_path = Path(sys.argv[3])
seen = set(state_path.read_text().splitlines()) if state_path.exists() else set()
entries = json.loads(payload_path.read_text() or "[]")
latest_timestamp = cursor_path.read_text().strip()

for entry in entries:
    timestamp = entry.get("timestamp", "")
    insert_id = entry.get("insertId", "")
    key = f"{timestamp}|{insert_id}"
    if key in seen:
        latest_timestamp = max(latest_timestamp, timestamp)
        continue
    seen.add(key)
    latest_timestamp = max(latest_timestamp, timestamp)
    revision = entry.get("resource", {}).get("labels", {}).get("revision_name", "")
    severity = entry.get("severity", "DEFAULT")
    text = entry.get("textPayload")
    if text is None:
        payload = entry.get("jsonPayload")
        if isinstance(payload, dict):
            text = payload.get("message") or json.dumps(payload, ensure_ascii=False, sort_keys=True)
        elif payload is not None:
            text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        else:
            proto = entry.get("protoPayload")
            text = json.dumps(proto, ensure_ascii=False, sort_keys=True) if proto else json.dumps(entry, ensure_ascii=False, sort_keys=True)
    print(f"{timestamp} {severity} {revision} {text}")

trimmed = sorted(seen)[-2000:]
state_path.write_text("\n".join(trimmed) + ("\n" if trimmed else ""))
cursor_path.write_text(latest_timestamp)
PY
    fi
    rm -f "${tmp_json}"
    sleep "${POLL_SECONDS}"
  done
}

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
    tail_logs "${FILTER}"
    ;;
  read)
    LIMIT="${2:-50}"
    exec gcloud run services logs read "${SERVICE_NAME}" \
      --project "${PROJECT_ID}" \
      --region "${REGION}" \
      --limit "${LIMIT}"
    ;;
  errors)
    tail_logs 'severity>=ERROR'
    ;;
  json)
    LIMIT="${2:-50}"
    exec gcloud logging read \
      "$(build_query)" \
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

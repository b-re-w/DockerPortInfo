#!/usr/bin/env bash
#
# launch_server.sh
# ------------------------------------------------------------------
# Start the DockerPortInfo FastAPI web server if needed. (primary server only)
#
#  - Does nothing if it is already running (used as a crontab keepalive).
#  - Runs uvicorn --reload to watch src/ for code changes and auto-reload.
#  - Writes logs to the logs/ folder at the project root.
#
# Example crontab entry (primary server: check liveness every minute, respawn if dead)
#   * * * * * /path/to/DockerPortInfo/scripts/launch_server.sh >> /path/to/DockerPortInfo/logs/launch.log 2>&1
# ------------------------------------------------------------------
set -uo pipefail

# cron has a minimal PATH; make sure uv / python / docker are reachable.
export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

# Load KEY=VALUE pairs from an env file WITHOUT overriding already-set variables.
load_env() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  while IFS='=' read -r key value; do
    key="${key%%[[:space:]]*}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
    if [[ -z "${!key:-}" ]]; then
      export "$key=$value"
    fi
  done < "$file"
}
load_env "${PROJECT_ROOT}/.env"
load_env "${PROJECT_ROOT}/.env.default"

HOST="${DOCKERPORTINFO_HOST:-0.0.0.0}"
PORT="${DOCKERPORTINFO_PORT:-8000}"
LOG_DIR="${PROJECT_ROOT}/logs"
LOG_FILE="${LOG_DIR}/server.log"
APP_MARKER="src.app:app"

mkdir -p "${LOG_DIR}"

# Exit if already running (prevent duplicate launches)
if pgrep -f "uvicorn.*${APP_MARKER}" >/dev/null 2>&1; then
  exit 0
fi

# Choose runner: prefer uv, fall back to python -m uvicorn
if command -v uv >/dev/null 2>&1; then
  RUNNER=(uv run uvicorn)
else
  RUNNER=(python3 -m uvicorn)
fi

echo "[$(date '+%F %T')] starting DockerPortInfo server: ${HOST}:${PORT} (runner=${RUNNER[*]})" >> "${LOG_FILE}"

nohup "${RUNNER[@]}" "${APP_MARKER}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --reload \
  --reload-dir "${PROJECT_ROOT}/src" \
  >> "${LOG_FILE}" 2>&1 &

echo "[$(date '+%F %T')] launched in background as PID $!" >> "${LOG_FILE}"

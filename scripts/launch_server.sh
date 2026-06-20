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
PORT="${DOCKERPORTINFO_PORT:-13000}"
LOG_DIR="${PROJECT_ROOT}/logs"
LOG_FILE="${LOG_DIR}/server.log"

mkdir -p "${LOG_DIR}"

# Is anything already listening on our port? (identify by port, not process name)
port_in_use() {
  if command -v ss >/dev/null 2>&1; then
    [[ -n "$(ss -ltnH "sport = :$1" 2>/dev/null)" ]]
  elif command -v fuser >/dev/null 2>&1; then
    fuser "$1/tcp" >/dev/null 2>&1
  elif command -v lsof >/dev/null 2>&1; then
    lsof -ti "tcp:$1" >/dev/null 2>&1
  else
    return 1
  fi
}

# Exit if our port is already served (prevent duplicate launches)
if port_in_use "${PORT}"; then
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

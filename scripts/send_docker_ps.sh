#!/usr/bin/env bash
#
# send_docker_ps.sh [SERVER_NAME]
# ------------------------------------------------------------------
# Send the `docker ps` output to the DockerPortInfo web server.
# Register in the crontab of BOTH primary and secondary servers to run every minute.
#
# Server name (default: primary) is provided at run time, either as the first
# argument or via DOCKERPORTINFO_SERVER_NAME.
#
# Configuration is read from <project-root>/.env (falling back to .env.default).
# Precedence: real environment variables > .env > .env.default.
#
#   DOCKERPORTINFO_SERVER_NAME : this server's name (e.g. primary, secondary)
#   DOCKERPORTINFO_WEB_URL     : web server base URL (e.g. http://168.188.127.233:13000)
#   DOCKERPORTINFO_PSK         : pre-shared key sent as the X-API-Key header
#
# Example crontab entry (secondary server)
#   * * * * * /path/to/DockerPortInfo/scripts/send_docker_ps.sh secondary >> /tmp/dpi-sender.log 2>&1
#
# Note: assumes `docker ps` runs without sudo.
# ------------------------------------------------------------------
set -uo pipefail

# cron has a minimal PATH; make sure docker / curl / uv are reachable.
export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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

SERVER_NAME="${1:-${DOCKERPORTINFO_SERVER_NAME:-primary}}"
WEB_URL="${DOCKERPORTINFO_WEB_URL:-http://127.0.0.1:13000}"
WEB_URL="${WEB_URL%/}" # strip trailing slash
PSK="${DOCKERPORTINFO_PSK:-}"

# Default (fixed-width) docker ps output - the server parser expects this format.
OUTPUT="$(docker ps 2>&1)"
if [[ $? -ne 0 ]]; then
  echo "[$(date '+%F %T')] docker ps failed: ${OUTPUT}" >&2
  exit 1
fi

HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
  -X POST "${WEB_URL}/docker/${SERVER_NAME}/" \
  -H "Content-Type: text/plain; charset=utf-8" \
  -H "X-API-Key: ${PSK}" \
  --data-binary "${OUTPUT}" \
  --max-time 15)"

if [[ "${HTTP_CODE}" == "200" ]]; then
  echo "[$(date '+%F %T')] ${SERVER_NAME} -> ${WEB_URL} sent ok (200)"
else
  echo "[$(date '+%F %T')] ${SERVER_NAME} -> ${WEB_URL} send failed (HTTP ${HTTP_CODE})" >&2
  exit 1
fi

#!/usr/bin/env bash
#
# setup.sh <primary|secondary> [options]
# ------------------------------------------------------------------
# Set up DockerPortInfo on a server (idempotent - safe to re-run).
#
#   primary    : install deps + configure .env + crontab (web server + sender)
#   secondary  : configure .env + crontab (sender only; no python deps needed)
#
# Options:
#   --psk KEY        pre-shared key (must be identical on primary & secondary)
#   --web-url URL    web server base URL the sender posts to
#                    (primary default: http://127.0.0.1:<port>)
#   --port PORT      web server port (primary, default 8000)
#   --host HOST      web server bind host (primary, default 0.0.0.0)
#   --no-cron        do not touch crontab
#   --no-start       (primary) do not start the server / send a test sample
#
# Examples:
#   ./scripts/setup.sh primary
#   ./scripts/setup.sh primary --psk "$(openssl rand -hex 24)"
#   ./scripts/setup.sh secondary --psk <same-key> --web-url http://168.188.127.233:8000
# ------------------------------------------------------------------
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

# ---------- args ----------
ROLE="${1:-}"; shift || true
PSK_ARG=""; WEB_URL_ARG=""; PORT="8000"; HOST="0.0.0.0"
DO_CRON=1; DO_START=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --psk)      PSK_ARG="$2"; shift 2 ;;
    --web-url)  WEB_URL_ARG="$2"; shift 2 ;;
    --port)     PORT="$2"; shift 2 ;;
    --host)     HOST="$2"; shift 2 ;;
    --no-cron)  DO_CRON=0; shift ;;
    --no-start) DO_START=0; shift ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 2 ;;
  esac
done

if [[ "$ROLE" != "primary" && "$ROLE" != "secondary" ]]; then
  echo "사용법: $0 <primary|secondary> [--psk KEY] [--web-url URL] [--port N] ..." >&2
  exit 2
fi

log()  { echo "[setup] $*"; }
warn() { echo "[setup][경고] $*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---------- helpers ----------
gen_key() {
  if have openssl; then openssl rand -hex 24
  elif have python3; then python3 -c "import secrets; print(secrets.token_hex(24))"
  else date +%s%N | sha256sum | head -c 48; fi
}

# set KEY=VALUE in a file (replace existing line or append)
set_env_var() {
  local key="$1" val="$2" file="$3"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    local tmp; tmp="$(mktemp)"
    grep -v "^${key}=" "$file" > "$tmp"
    echo "${key}=${val}" >> "$tmp"
    mv "$tmp" "$file"
  else
    echo "${key}=${val}" >> "$file"
  fi
}

get_env_var() { grep "^$1=" "$2" 2>/dev/null | head -n1 | cut -d= -f2-; }

# ---------- prerequisites ----------
log "역할: ${ROLE} / 프로젝트: ${PROJECT_ROOT}"
have docker || warn "docker 가 PATH 에 없습니다. (docker ps 가 sudo 없이 되는지 확인하세요)"
have curl   || { echo "[setup][오류] curl 이 필요합니다." >&2; exit 1; }
have crontab || { [[ $DO_CRON -eq 1 ]] && warn "crontab 이 없어 cron 등록을 건너뜁니다."; DO_CRON=0; }

# ---------- .env ----------
[[ -f .env ]] || { cp .env.default .env; log ".env 생성 (.env.default 복사)"; }

# PSK 결정
if [[ -n "$PSK_ARG" ]]; then
  PSK="$PSK_ARG"
else
  cur="$(get_env_var DOCKERPORTINFO_PSK .env)"
  if [[ -n "$cur" && "$cur" != "change-me-please" ]]; then
    PSK="$cur"
  elif [[ "$ROLE" == "primary" ]]; then
    PSK="$(gen_key)"; log "PSK 자동 생성 → secondary 에도 동일하게 넣으세요"
  else
    PSK="$cur"
    warn "secondary 에 PSK 가 지정되지 않았습니다. primary 와 동일한 키를 --psk 로 넘기세요."
  fi
fi
set_env_var DOCKERPORTINFO_PSK "$PSK" .env

# WEB_URL / PORT / HOST
if [[ -n "$WEB_URL_ARG" ]]; then
  set_env_var DOCKERPORTINFO_WEB_URL "$WEB_URL_ARG" .env
elif [[ "$ROLE" == "primary" ]]; then
  set_env_var DOCKERPORTINFO_WEB_URL "http://127.0.0.1:${PORT}" .env
elif [[ -z "$(get_env_var DOCKERPORTINFO_WEB_URL .env)" ]]; then
  warn "secondary 의 DOCKERPORTINFO_WEB_URL 이 비어 있습니다. --web-url http://<primary-ip>:8000 으로 지정하세요."
fi
if [[ "$ROLE" == "primary" ]]; then
  set_env_var DOCKERPORTINFO_HOST "$HOST" .env
  set_env_var DOCKERPORTINFO_PORT "$PORT" .env
fi
log ".env 구성 완료 (PSK=${PSK:0:6}…)"

# ---------- dirs / perms ----------
mkdir -p logs data
chmod +x scripts/*.sh
log "logs/, data/ 준비 및 스크립트 실행권한 부여"

# ---------- deps (primary only) ----------
if [[ "$ROLE" == "primary" ]]; then
  if have uv; then
    log "의존성 설치: uv sync"
    uv sync
  elif have python3; then
    log "uv 없음 → venv + pip 로 설치"
    [[ -d .venv ]] || python3 -m venv .venv
    ./.venv/bin/python -m pip install -q --upgrade pip
    ./.venv/bin/python -m pip install -q fastapi "uvicorn[standard]" pydantic
  else
    echo "[setup][오류] python3 또는 uv 가 필요합니다 (primary)." >&2
    exit 1
  fi
fi

# ---------- crontab ----------
if [[ $DO_CRON -eq 1 ]]; then
  MARKER="# DockerPortInfo-cron"
  base="$(crontab -l 2>/dev/null | grep -v "$MARKER")"
  {
    echo "$base"
    if [[ "$ROLE" == "primary" ]]; then
      echo "* * * * * ${PROJECT_ROOT}/scripts/launch_server.sh >> ${PROJECT_ROOT}/logs/launch.log 2>&1 ${MARKER}"
      echo "* * * * * ${PROJECT_ROOT}/scripts/send_docker_ps.sh primary >> ${PROJECT_ROOT}/logs/sender.log 2>&1 ${MARKER}"
    else
      echo "* * * * * ${PROJECT_ROOT}/scripts/send_docker_ps.sh secondary >> ${PROJECT_ROOT}/logs/sender.log 2>&1 ${MARKER}"
    fi
  } | crontab -
  log "crontab 등록 완료 (1분 주기). 확인: crontab -l | grep DockerPortInfo"
fi

# ---------- start / smoke test ----------
if [[ "$ROLE" == "primary" && $DO_START -eq 1 ]]; then
  log "웹 서버 기동 시도"
  ./scripts/launch_server.sh
  for _ in $(seq 1 20); do
    curl -s "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1 && break
    sleep 0.5
  done
  if curl -s "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
    log "웹 서버 정상 (http://${HOST}:${PORT})"
    ./scripts/send_docker_ps.sh primary || warn "초기 전송 실패 (docker ps 가능 여부 확인)"
  else
    warn "웹 서버 헬스체크 실패. logs/server.log 를 확인하세요."
  fi
fi

log "완료 ✅  (${ROLE})"
if [[ "$ROLE" == "primary" ]]; then
  echo
  echo "  웹 UI : http://<이 서버 IP>:${PORT}"
  echo "  PSK   : ${PSK}"
  echo "  ↑ 위 PSK 를 secondary 세팅에 사용하세요:"
  echo "     ./scripts/setup.sh secondary --psk ${PSK} --web-url http://<이 서버 IP>:${PORT}"
fi

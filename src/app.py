"""FastAPI web server.

All routes live under a common prefix (settings.base_path, default `/info/docker`)
so the app can sit behind one nginx `location` block.

Endpoints (BASE = base_path, e.g. /info/docker)
- GET  BASE/                  : monitoring web page
- GET  BASE/static/*          : static assets (css/js)
- GET  BASE/snapshots         : all server snapshots (JSON) - polled by the page
- GET  BASE/{server_name}     : a specific server's cleaned snapshot (JSON)
- POST BASE/{server_name}     : receive each server's raw `docker ps` text
- GET  BASE/healthz           : health check
"""

from __future__ import annotations

import hmac
import ipaddress
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .models import ServerSnapshot
from .parser import parse_docker_ps
from .store import store

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RES_DIR = _PROJECT_ROOT / "res"
_INDEX_FILE = _RES_DIR / "index.html"

BASE = settings.base_path  # "" or "/info/docker"

# Campus networks allowed to see port details.
_CAMPUS_NETS = []
for _cidr in settings.campus_cidrs.split(","):
    _cidr = _cidr.strip()
    if not _cidr:
        continue
    try:
        _CAMPUS_NETS.append(ipaddress.ip_network(_cidr, strict=False))
    except ValueError:
        pass


def _client_ip(request: Request) -> str:
    """Real client IP, honoring the X-Real-IP / X-Forwarded-For set by nginx."""
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _is_campus(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _CAMPUS_NETS)


def _public_snapshot(snap: ServerSnapshot, campus: bool) -> dict:
    """Serialize a snapshot; hide per-container port info for non-campus clients."""
    data = snap.model_dump(mode="json")
    if not campus:
        for container in data.get("containers", []):
            container["ports"] = []
            container["raw_ports"] = ""
            container["ports_hidden"] = True
    return data


def _notice(ip: str) -> str:
    return f"당신의 접속 IP는 {ip}입니다. 학외 IP의 경우 포트 정보가 비공개됩니다."


app = FastAPI(title="DockerPortInfo", version="0.1.0")

# Static resources (css/js) under the common prefix.
app.mount(f"{BASE}/static", StaticFiles(directory=str(_RES_DIR)), name="static")


@app.get(f"{BASE}/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    # Inject the base path so assets/fetches resolve under the prefix.
    html = _INDEX_FILE.read_text("utf-8").replace("__BASE__", BASE)
    return HTMLResponse(html)


@app.get(f"{BASE}/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# Declared before /{server_name} so it is not captured as a server name.
@app.get(f"{BASE}/snapshots")
def get_all(request: Request) -> JSONResponse:
    ip = _client_ip(request)
    campus = _is_campus(ip)
    return JSONResponse(
        {
            "client_ip": ip,
            "restricted": not campus,
            "notice": None if campus else _notice(ip),
            "servers": [_public_snapshot(s, campus) for s in store.all()],
        }
    )


@app.post(f"{BASE}/{{server_name}}")
async def ingest(
    server_name: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> JSONResponse:
    """Receive the raw `docker ps` text sent by cron, parse it, and store it.

    Requires the pre-shared key in the `X-API-Key` header when one is configured.
    """
    if settings.psk and not hmac.compare_digest(x_api_key or "", settings.psk):
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    raw_bytes = await request.body()
    raw = raw_bytes.decode("utf-8", errors="replace")
    keep_raw = request.query_params.get("keep_raw") in ("1", "true", "yes")
    snapshot = parse_docker_ps(server_name, raw, keep_raw=keep_raw)
    store.put(snapshot)
    return JSONResponse(
        {
            "ok": True,
            "server_name": snapshot.server_name,
            "container_count": snapshot.container_count,
            "total_containers": snapshot.total_containers,
            "updated_at": snapshot.updated_at.isoformat(),
        }
    )


@app.get(f"{BASE}/{{server_name}}")
def get_server(server_name: str, request: Request) -> JSONResponse:
    snapshot = store.get(server_name)
    if snapshot is None:
        return JSONResponse({"error": "not found", "server_name": server_name}, status_code=404)
    ip = _client_ip(request)
    campus = _is_campus(ip)
    data = _public_snapshot(snapshot, campus)
    data["client_ip"] = ip
    data["restricted"] = not campus
    data["notice"] = None if campus else _notice(ip)
    return JSONResponse(data)


if BASE:
    # Convenience redirect so the bare root still lands on the dashboard locally.
    @app.get("/")
    def _root_redirect() -> RedirectResponse:
        return RedirectResponse(f"{BASE}/")

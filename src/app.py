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
def get_all() -> dict[str, list[ServerSnapshot]]:
    return {"servers": store.all()}


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


@app.get(f"{BASE}/{{server_name}}", response_model=ServerSnapshot)
def get_server(server_name: str) -> ServerSnapshot | JSONResponse:
    snapshot = store.get(server_name)
    if snapshot is None:
        return JSONResponse({"error": "not found", "server_name": server_name}, status_code=404)
    return snapshot


if BASE:
    # Convenience redirect so the bare root still lands on the dashboard locally.
    @app.get("/")
    def _root_redirect() -> RedirectResponse:
        return RedirectResponse(f"{BASE}/")

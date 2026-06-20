"""FastAPI web server.

Endpoints
- GET  /                         : monitoring web page
- POST /docker/{server_name}/    : receive each server's raw `docker ps` text
- GET  /docker/{server_name}/    : a specific server's cleaned snapshot (JSON)
- GET  /api/snapshots            : all server snapshots (JSON) - polled by the page
- GET  /healthz                  : health check
"""

from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .models import ServerSnapshot
from .parser import parse_docker_ps
from .store import store

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RES_DIR = _PROJECT_ROOT / "res"

app = FastAPI(title="DockerPortInfo", version="0.1.0")

# Static resources (css/js)
app.mount("/static", StaticFiles(directory=str(_RES_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_RES_DIR / "index.html")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/docker/{server_name}/")
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


@app.get("/docker/{server_name}/", response_model=ServerSnapshot)
def get_server(server_name: str) -> ServerSnapshot | JSONResponse:
    snapshot = store.get(server_name)
    if snapshot is None:
        return JSONResponse({"error": "not found", "server_name": server_name}, status_code=404)
    return snapshot


@app.get("/api/snapshots")
def get_all() -> dict[str, list[ServerSnapshot]]:
    return {"servers": store.all()}

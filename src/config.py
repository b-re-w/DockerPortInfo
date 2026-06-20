"""Project configuration loaded from .env (overriding .env.default).

Precedence (highest first): real environment variables > .env > .env.default.
"""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            data[key] = value
    return data


class Settings:
    def __init__(self) -> None:
        merged = {
            **_load_env_file(_PROJECT_ROOT / ".env.default"),
            **_load_env_file(_PROJECT_ROOT / ".env"),
        }

        def get(key: str, fallback: str = "") -> str:
            return os.environ.get(key, merged.get(key, fallback))

        # Pre-shared key required on the ingest endpoint.
        # Empty value => authentication disabled (development only).
        self.psk: str = get("DOCKERPORTINFO_PSK", "")

        # Common URL prefix for every route (must match the nginx location).
        # Normalized to a single leading slash and no trailing slash; "" = root.
        raw_base = get("DOCKERPORTINFO_BASE_PATH", "/info/docker")
        base = "/" + raw_base.strip().strip("/")
        self.base_path: str = "" if base == "/" else base


settings = Settings()

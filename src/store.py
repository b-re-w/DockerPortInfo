"""In-memory store mapping server name -> latest snapshot.

When uvicorn --reload reloads the code the memory is cleared, so we also
persist to disk (data/<server>.json) to restore the last value after a
reload/restart.
"""

from __future__ import annotations

import threading
from pathlib import Path

from .models import ServerSnapshot

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"


class SnapshotStore:
    def __init__(self, data_dir: Path = _DATA_DIR) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._snapshots: dict[str, ServerSnapshot] = {}
        self._load_all()

    def _path_for(self, server_name: str) -> Path:
        safe = "".join(c for c in server_name if c.isalnum() or c in ("-", "_"))
        return self._data_dir / f"{safe or 'unknown'}.json"

    def _load_all(self) -> None:
        for path in self._data_dir.glob("*.json"):
            try:
                snap = ServerSnapshot.model_validate_json(path.read_text("utf-8"))
                self._snapshots[snap.server_name] = snap
            except Exception:
                # Ignore corrupted files
                continue

    def put(self, snapshot: ServerSnapshot) -> None:
        with self._lock:
            self._snapshots[snapshot.server_name] = snapshot
            try:
                self._path_for(snapshot.server_name).write_text(
                    snapshot.model_dump_json(indent=2), encoding="utf-8"
                )
            except Exception:
                pass

    def get(self, server_name: str) -> ServerSnapshot | None:
        with self._lock:
            return self._snapshots.get(server_name)

    def all(self) -> list[ServerSnapshot]:
        with self._lock:
            return sorted(self._snapshots.values(), key=lambda s: s.server_name)


store = SnapshotStore()

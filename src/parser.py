"""Convert raw `docker ps` text into a cleaned-up data type (ServerSnapshot).

The default `docker ps` output is fixed-width columns (left-aligned by header
position with space padding), so we parse robustly by finding each column's
start offset from the header line and slicing the data lines accordingly.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .models import ContainerInfo, ImageInfo, PortMapping, ServerSnapshot

BACKENDAI_MARKER = "cr.backend.ai"

# Column headers of the default `docker ps` output (order preserved)
_HEADERS = ["CONTAINER ID", "IMAGE", "COMMAND", "CREATED", "STATUS", "PORTS", "NAMES"]

# "168.188.127.233:30726->8180/tcp" / "[::]:3000->3000/tcp" / "0.0.0.0:9000-9001->9000-9001/tcp"
_PORT_MAPPED = re.compile(
    r"^(?:(?P<ip>\[?[0-9a-fA-F:.\]]+):)?"
    r"(?P<host>\d+(?:-\d+)?)->(?P<container>\d+(?:-\d+)?)/(?P<proto>\w+)$"
)
# "2380/tcp" - a port that is only exposed, not mapped
_PORT_EXPOSED = re.compile(r"^(?P<container>\d+(?:-\d+)?)/(?P<proto>\w+)$")


def _split_columns(header: str) -> list[tuple[str, int, int | None]]:
    """Build a list of (column_name, start_offset, end_offset) from the header line."""
    found = [(h, header.find(h)) for h in _HEADERS]
    found = [(name, off) for name, off in found if off >= 0]
    found.sort(key=lambda x: x[1])
    ranges: list[tuple[str, int, int | None]] = []
    for i, (name, off) in enumerate(found):
        end = found[i + 1][1] if i + 1 < len(found) else None
        ranges.append((name, off, end))
    return ranges


def _slice_row(line: str, ranges: list[tuple[str, int, int | None]]) -> dict[str, str]:
    row: dict[str, str] = {}
    for name, start, end in ranges:
        value = line[start:end] if end is not None else line[start:]
        row[name] = value.strip()
    return row


def parse_image(image: str) -> ImageInfo:
    """Decompose an image string.

    e.g. cr.backend.ai/multiarch/python:3.12-ubuntu24.04-cuda12.6.1
         -> language=python, language_version=3.12, ubuntu=24.04, cuda=12.6
    """
    repo, tag = image, ""
    last_slash = image.rfind("/")
    last_colon = image.rfind(":")
    # The tag-separating ':' must come after the last '/' (to distinguish a registry port)
    if last_colon > last_slash:
        repo, tag = image[:last_colon], image[last_colon + 1 :]

    info = ImageInfo(
        raw_image=image,
        repo=repo,
        raw_tag=tag or None,
        is_backendai=BACKENDAI_MARKER in image,
    )

    info.language = repo.rsplit("/", 1)[-1] or None

    if tag:
        m_ver = re.match(r"(\d+(?:\.\d+)*)", tag)
        if m_ver:
            info.language_version = m_ver.group(1)
        m_ubuntu = re.search(r"ubuntu(\d+(?:\.\d+)*)", tag)
        if m_ubuntu:
            info.ubuntu = m_ubuntu.group(1)
        m_cuda = re.search(r"cuda(\d+(?:\.\d+)*)", tag)
        if m_cuda:
            info.cuda_full = m_cuda.group(1)
            parts = m_cuda.group(1).split(".")
            info.cuda = ".".join(parts[:2])
    return info


def parse_ports(ports_str: str) -> list[PortMapping]:
    """Convert the PORTS column string into a list of mappings."""
    result: list[PortMapping] = []
    if not ports_str:
        return result
    for part in ports_str.split(","):
        part = part.strip()
        if not part:
            continue
        m = _PORT_MAPPED.match(part)
        if m:
            result.append(
                PortMapping(
                    container_port=m.group("container"),
                    host_port=m.group("host"),
                    host_ip=m.group("ip"),
                    proto=m.group("proto"),
                    raw=part,
                )
            )
            continue
        m2 = _PORT_EXPOSED.match(part)
        if m2:
            result.append(
                PortMapping(
                    container_port=m2.group("container"),
                    host_port=None,
                    host_ip=None,
                    proto=m2.group("proto"),
                    raw=part,
                )
            )
    return result


def parse_docker_ps(
    server_name: str, raw: str, keep_raw: bool = False
) -> ServerSnapshot:
    """Convert raw `docker ps` text into a ServerSnapshot."""
    lines = [ln for ln in raw.splitlines() if ln.strip()]

    header_idx = None
    for i, ln in enumerate(lines):
        if "CONTAINER ID" in ln and "IMAGE" in ln and "NAMES" in ln:
            header_idx = i
            break

    containers: list[ContainerInfo] = []
    total_seen = 0
    if header_idx is not None:
        ranges = _split_columns(lines[header_idx])
        for ln in lines[header_idx + 1 :]:
            row = _slice_row(ln, ranges)
            image_raw = row.get("IMAGE", "")
            if not image_raw:
                continue
            total_seen += 1
            # Only keep cr.backend.ai images; ignore infra containers (redis, etcd, ...)
            if BACKENDAI_MARKER not in image_raw:
                continue
            containers.append(
                ContainerInfo(
                    container_id=row.get("CONTAINER ID", ""),
                    names=row.get("NAMES", ""),
                    command=row.get("COMMAND", ""),
                    created=row.get("CREATED", ""),
                    status=row.get("STATUS", ""),
                    image=parse_image(image_raw),
                    ports=parse_ports(row.get("PORTS", "")),
                    raw_ports=row.get("PORTS", ""),
                )
            )

    return ServerSnapshot(
        server_name=server_name,
        updated_at=datetime.now(timezone.utc),
        container_count=len(containers),
        total_containers=total_seen,
        containers=containers,
        raw=raw if keep_raw else None,
    )

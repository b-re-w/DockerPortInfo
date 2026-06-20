"""Data types the web server stores and returns."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PortMapping(BaseModel):
    """A single container-port <-> host-port mapping."""

    container_port: str = Field(..., description="Container-internal port (e.g. 8180)")
    host_port: str | None = Field(None, description="Port mapped on the host (e.g. 30726)")
    host_ip: str | None = Field(None, description="Bound host IP")
    proto: str = Field("tcp", description="Protocol")
    raw: str = Field("", description="Original port notation")


class ImageInfo(BaseModel):
    """An image tag decomposed into human-readable information."""

    raw_image: str = Field(..., description="Original full image name")
    repo: str | None = Field(None, description="Repository path without the tag")
    raw_tag: str | None = Field(None, description="Original tag string")
    is_backendai: bool = Field(False, description="Whether this is a cr.backend.ai image")
    language: str | None = Field(None, description="Runtime language (e.g. python)")
    language_version: str | None = Field(None, description="Language version (e.g. 3.12)")
    ubuntu: str | None = Field(None, description="Ubuntu version (e.g. 24.04)")
    cuda: str | None = Field(None, description="CUDA major.minor (e.g. 12.6)")
    cuda_full: str | None = Field(None, description="Full CUDA version (e.g. 12.6.1)")


class ContainerInfo(BaseModel):
    """Cleaned-up information for a single container."""

    container_id: str
    names: str = ""
    command: str = ""
    created: str = ""
    status: str = ""
    image: ImageInfo
    ports: list[PortMapping] = Field(default_factory=list)
    raw_ports: str = ""


class ServerSnapshot(BaseModel):
    """Latest snapshot for a single server. Stored keyed by server name."""

    server_name: str
    updated_at: datetime
    container_count: int = Field(0, description="Number of cr.backend.ai containers (stored)")
    total_containers: int = Field(0, description="Total containers seen in docker ps (incl. infra)")
    containers: list[ContainerInfo] = Field(default_factory=list)
    raw: str | None = Field(None, description="Received raw `docker ps` output (for debugging)")

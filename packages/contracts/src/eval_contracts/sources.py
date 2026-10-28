"""Immutable loaded source contract shared by dataset consumers."""

from pathlib import Path

from pydantic import Field

from .schema_base import StrictModel

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class ResolvedSource(StrictModel):
    logical_path: str
    filesystem_path: Path
    sha256: str = Field(pattern=SHA256_PATTERN)
    content: bytes

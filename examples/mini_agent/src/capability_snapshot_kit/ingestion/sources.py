"""Read only explicitly selected local sources and verify their content."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .models import FactDocument, SourceReference

MAX_SOURCE_BYTES = 1_000_000
MAX_TOTAL_BYTES = 8_000_000


def read_source(root: Path, relative: str) -> bytes:
    SourceReference(path=relative, sha256="0" * 64, kind="code")
    resolved_root = root.resolve(strict=True)
    path = (resolved_root / relative).resolve(strict=True)
    if not path.is_relative_to(resolved_root):
        raise ValueError(f"source outside root: {relative}")
    if not path.is_file():
        raise ValueError(f"source is not a regular file: {relative}")
    with path.open("rb") as stream:
        content = stream.read(MAX_SOURCE_BYTES + 1)
    if len(content) > MAX_SOURCE_BYTES:
        raise ValueError(f"source too large: {relative}")
    return content


def source_reference(root: Path, relative: str, kind: str = "code") -> SourceReference:
    return SourceReference(
        path=relative,
        sha256=hashlib.sha256(read_source(root, relative)).hexdigest(),
        kind=kind,
    )


def check_sources(document: FactDocument, root: Path) -> None:
    total = 0
    for source in document.sources.values():
        content = read_source(root, source.path)
        total += len(content)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("total source size exceeds limit")
        if hashlib.sha256(content).hexdigest() != source.sha256:
            raise ValueError(f"source hash mismatch: {source.path}")

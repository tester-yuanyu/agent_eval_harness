"""Trusted loading and hashing for Suite-local sources and contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from .models import (
    ContractReference,
    DatasetSource,
    ResolvedContract,
    ResolvedSource,
)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ContractStoreError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        evidence_refs: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.evidence_refs = list(evidence_refs or [])


class ContractStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)

    def _read(self, logical_path: str) -> tuple[Path, bytes]:
        candidate = PurePosixPath(logical_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ContractStoreError(
                "SOURCE_PATH_OUTSIDE_ROOT",
                f"source {logical_path!r} resolves outside the Suite root",
                evidence_refs=[logical_path],
            )
        unresolved = self.root / logical_path
        try:
            resolved = unresolved.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ContractStoreError(
                "SOURCE_NOT_FOUND",
                f"source {logical_path!r} does not exist",
                evidence_refs=[logical_path],
            ) from exc
        if not resolved.is_relative_to(self.root):
            raise ContractStoreError(
                "SOURCE_PATH_OUTSIDE_ROOT",
                f"source {logical_path!r} resolves outside the Suite root",
                evidence_refs=[logical_path],
            )
        if not resolved.is_file():
            raise ContractStoreError(
                "SOURCE_NOT_FOUND",
                f"source {logical_path!r} is not a file",
                evidence_refs=[logical_path],
            )
        return resolved, resolved.read_bytes()

    def resolve_source(self, source: DatasetSource) -> ResolvedSource:
        resolved, content = self._read(source.path)
        actual = sha256_bytes(content)
        if actual != source.sha256:
            raise ContractStoreError(
                "SOURCE_FINGERPRINT_MISMATCH",
                f"source {source.path!r} SHA-256 does not match its declaration",
                evidence_refs=[source.path],
            )
        return ResolvedSource(
            logical_path=source.path,
            filesystem_path=resolved,
            sha256=actual,
            content=content,
        )

    def load_contract(self, reference: ContractReference) -> ResolvedContract:
        source = self.resolve_source(
            DatasetSource(path=reference.path, sha256=reference.sha256)
        )
        try:
            content = json.loads(source.content)
            if not isinstance(content, dict):
                raise TypeError("contract root must be a JSON object")
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise ContractStoreError(
                "CONTRACT_INVALID_JSON",
                f"contract {reference.path!r} is not a JSON object",
                evidence_refs=[reference.path],
            ) from exc
        return ResolvedContract(
            contract_id=reference.contract_id,
            version=reference.version,
            logical_path=reference.path,
            sha256=source.sha256,
            content=content,
        )

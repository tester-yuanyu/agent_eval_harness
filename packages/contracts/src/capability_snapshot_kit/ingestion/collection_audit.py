"""采集范围与来源失效 sidecar；不扩展 v3 bundle 或事实文档。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator

from capability_snapshot_kit.base import ProtocolModel

from .models import FactDocument, SourceReference
from .sources import MAX_TOTAL_BYTES, read_source


class CollectionScope(ProtocolModel):
    """调用者显式列出的采集范围，不表示自动发现全部 Agent 能力。"""

    requested_sources: list[str] = Field(default_factory=list)
    expected_fact_ids: list[str] = Field(default_factory=list)
    omissions: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        for path in self.requested_sources:
            SourceReference(path=path, sha256="0" * 64, kind="code")
        for values in (self.requested_sources, self.expected_fact_ids):
            if len(values) != len(set(values)) or any(not v.strip() for v in values):
                raise ValueError("scope entries must be unique and nonempty")
        if not set(self.omissions) <= set(self.requested_sources):
            raise ValueError("omissions must refer to requested sources")
        if any(not reason.strip() for reason in self.omissions.values()):
            raise ValueError("omission reasons must be nonempty")
        return self


def audit_collection(
    document: FactDocument,
    source_root: Path,
    *,
    scope: dict | CollectionScope | None = None,
) -> dict:
    """Read only bound files, then invalidate precisely their dependent facts.

    'unchanged' means declared source bytes still match, not runtime verification.
    Missing/changed sources invalidate; unreadable/unbound sources remain unknown.
    Completeness is measured against the caller's declared inventory only.
    """
    declared = CollectionScope.model_validate(scope) if scope is not None else None
    source_rows, cache = {}, {}
    total = 0
    for source_id, source in sorted(document.sources.items()):
        if source.path not in cache:
            try:
                content = read_source(source_root, source.path)
                total += len(content)
                if total > MAX_TOTAL_BYTES:
                    raise ValueError("total source size exceeds limit")
                cache[source.path] = (hashlib.sha256(content).hexdigest(), None)
            except FileNotFoundError:
                cache[source.path] = (None, "missing")
            except (OSError, ValueError) as exc:
                # Do not echo exception paths or source contents into the sidecar.
                cache[source.path] = (None, type(exc).__name__)
        observed_hash, error = cache[source.path]
        state = (
            "missing"
            if error == "missing"
            else "unreadable"
            if error
            else "unchanged"
            if observed_hash == source.sha256
            else "changed"
        )
        source_rows[source_id] = {
            "path": source.path,
            "expected_sha256": source.sha256,
            "observed_sha256": observed_hash,
            "state": state,
            "error_type": error,
        }
    fact_rows = {}
    for ident in sorted(document.fact_index()):
        origins = document.origins.get(ident, [])
        changed = [
            key
            for key in origins
            if source_rows[key]["state"] in {"changed", "missing"}
        ]
        unknown = [key for key in origins if source_rows[key]["state"] == "unreadable"]
        fact_rows[ident] = {
            "source_ids": origins,
            "changed_source_ids": changed,
            "unknown_source_ids": unknown,
            "validity": "invalidated"
            if changed
            else "unknown"
            if unknown or not origins
            else "unchanged",
            "reason": "source_changed_or_missing"
            if changed
            else "source_unverified"
            if unknown or not origins
            else "bound_source_bytes_match",
        }
    collected = {s.path for s in document.sources.values()}
    omissions, missing_facts, outside = [], [], []
    if declared is not None:
        if set(declared.omissions) & collected:
            raise ValueError("collected source cannot also be declared omitted")
        omissions = [
            {"path": path, "reason": declared.omissions.get(path, "unknown")}
            for path in sorted(set(declared.requested_sources) - collected)
        ]
        missing_facts = sorted(set(declared.expected_fact_ids) - set(fact_rows))
        outside = sorted(collected - set(declared.requested_sources))
    return {
        "audit_version": "1.0",
        "audit_kind": "collection_scope_and_source_invalidation",
        "scope": declared.model_dump(mode="json") if declared is not None else None,
        "collection_completeness": (
            "unknown"
            if declared is None
            else "incomplete_within_declared_scope"
            if omissions or missing_facts
            else "accounted_within_declared_scope"
        ),
        "global_completeness": "unknown",
        "execution_verified": False,
        "source_omissions": omissions,
        "missing_fact_ids": missing_facts,
        "sources_outside_declared_scope": outside,
        "sources": source_rows,
        "facts": fact_rows,
        "note": "采集范围核算与来源字节匹配不证明能力完整、事实语义正确或运行通过。",
    }

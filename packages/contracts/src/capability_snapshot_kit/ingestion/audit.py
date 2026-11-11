"""只读声明/采集差异协议；不推断支持状态或采集的全局完整性。"""

from __future__ import annotations

from .models import FactDocument


def audit_documents(
    runtime: FactDocument | None, candidate: FactDocument | None
) -> dict:
    if runtime is None and candidate is None:
        raise ValueError("provide a runtime or candidate document")
    indexes = {
        name: doc.fact_index() if doc is not None else {}
        for name, doc in [("runtime", runtime), ("candidate", candidate)]
    }
    compared = runtime is not None and candidate is not None
    left, right = indexes["runtime"], indexes["candidate"]
    return {
        "audit_version": "1.0",
        "scope": "provided_facts_and_source_bindings_only",
        "execution_verified": False,
        "collection_completeness": "unknown",
        "inputs": {
            name: "provided" if doc is not None else "not_provided"
            for name, doc in [("runtime", runtime), ("candidate", candidate)]
        },
        "comparison_performed": compared,
        "fact_counts": {name: len(index) for name, index in indexes.items()},
        "runtime_only": sorted(left.keys() - right.keys()) if compared else [],
        "candidate_only": sorted(right.keys() - left.keys()) if compared else [],
        "conflicts": sorted(
            key for key in left.keys() & right.keys() if left[key] != right[key]
        ),
        "missing_sources": {
            name: sorted(key for key in indexes[name] if not doc.origins.get(key))
            if doc is not None
            else []
            for name, doc in [("runtime", runtime), ("candidate", candidate)]
        },
    }

"""Keep configured facts separate from unverified semantic declarations."""

from __future__ import annotations

from typing import Any

from capability_snapshot_kit.hashing import sha256_json

from .models import FactDocument


def reconcile(
    runtime: FactDocument | None,
    candidate: FactDocument | None,
) -> tuple[FactDocument, dict[str, Any], list[dict[str, Any]]]:
    if runtime is None and candidate is None:
        raise ValueError("provide a collector or candidate document")
    runtime_index = runtime.fact_index() if runtime else {}
    candidate_index = candidate.fact_index() if candidate else {}
    if candidate and runtime and candidate.agent != runtime.agent:
        raise ValueError("conflicting Agent identity, configuration or schema")
    for key, fact in candidate_index.items():
        if key.startswith("tool.") and key not in runtime_index:
            raise ValueError(f"candidate cannot add registered tool: {key}")
        if key in runtime_index and fact != runtime_index[key]:
            raise ValueError(f"conflicting fact: {key}")

    index = {**candidate_index, **runtime_index}
    base = runtime if runtime is not None else candidate
    assert base is not None
    payload: dict[str, Any] = {
        "agent": base.agent.model_dump(mode="json"),
        "modules": [],
        "intents": [],
        "tools": [],
        "evidence": [],
        "sources": {},
        "origins": {},
    }
    for name, document in (("collector", runtime), ("candidate", candidate)):
        if document is None:
            continue
        for source_id, source in document.sources.items():
            payload["sources"][f"{name}/{source_id}"] = source.model_dump(mode="json")
        for fact_id, source_ids in document.origins.items():
            payload["origins"].setdefault(fact_id, []).extend(
                f"{name}/{source_id}" for source_id in source_ids
            )

    facts_report: dict[str, Any] = {}
    gaps: list[dict[str, Any]] = []
    groups = {
        "module": "modules",
        "intent": "intents",
        "tool": "tools",
        "evidence": "evidence",
    }
    for key, fact in sorted(index.items()):
        configured = key in runtime_index
        effective = fact.model_dump(mode="json")
        claim_records = []
        claims = (
            [effective["availability"]]
            if key.startswith("evidence.")
            else effective.get("capabilities", [])
        )
        for claim in claims:
            original_status = claim["support_status"]
            if not configured:
                claim["support_status"] = "unknown"
                claim["reason"] = (
                    "Unverified declaration; no configured collector fact."
                )
            claim_records.append(
                {
                    "capability_key": claim["capability_key"],
                    "declared_status": original_status,
                    "effective_status": claim["support_status"],
                }
            )
            if claim["support_status"] != "supported":
                gaps.append(
                    {
                        "code": (
                            "UNVERIFIED_DECLARATION"
                            if not configured
                            else "CAPABILITY_" + claim["support_status"].upper()
                        ),
                        "fact_id": key,
                        "capability_key": claim["capability_key"],
                        "reason": claim["reason"],
                    }
                )
        origins = payload["origins"].get(key, [])
        if not origins:
            gaps.append({"code": "MISSING_SOURCE", "fact_id": key})
        if key.startswith("intent."):
            tool = effective.get("required_tool_name")
            if tool is not None and f"tool.{tool}" not in runtime_index:
                gaps.append(
                    {
                        "code": "REQUIRED_TOOL_NOT_REGISTERED",
                        "fact_id": key,
                        "tool_name": tool,
                    }
                )
        facts_report[key] = {
            "basis": "configured" if configured else "declared",
            "source_ids": sorted(origins),
            "claims": claim_records,
            "effective_fact_sha256": sha256_json(effective),
        }
        prefix = key.split(".")[0]
        if prefix != "agent":
            payload[groups[prefix]].append(effective)

    return (
        FactDocument.model_validate(payload),
        {
            "execution_verified": False,
            "meaning": "Configured means a trusted collector declared the current "
            "configuration; source hashes do not prove behavior.",
            "facts": facts_report,
        },
        gaps,
    )

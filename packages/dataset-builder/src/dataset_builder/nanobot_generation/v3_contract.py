"""Reviewed execution-contract mapping; no arbitrary revision may reuse oracles."""

import hashlib
import json
from pathlib import Path

from .inputs import bind_source

CONTRACT_SHA256 = "95e9330f2042b325df451363e4aae5492158f0bdfb141c3e016ba15e47ec958c"
MCP_BLOCKER = "nanobot:CONDITIONAL_MCP_BOUNDARY_UNRESOLVED:chain.end_to_end"
EXCEPTION_BLOCKER = "nanobot:EXCEPTION_OBSERVER_NOT_IMPLEMENTED:evidence.run_exception"


def catalog(data):
    if data["files_sha256"].get("execution_contract.json") != CONTRACT_SHA256:
        raise ValueError("execution contract changed; explicit oracle review required")
    rows = json.loads((Path(__file__).parent / "execution_catalog_v3.json").read_text())
    return rows


def case_id(row):
    key = "execution:" + row["key"]
    return (
        "nanobot:"
        + row["target_id"]
        + ":"
        + hashlib.sha256(key.encode()).hexdigest()[:16]
    )


def required_blocker_ids(row):
    result = ["nanobot:RUNTIME_BINDING_REQUIRED:" + row["target_id"]]
    if any(p.startswith("/exceptions") for p in row["contract_keys"]):
        result.append(EXCEPTION_BLOCKER)
    return result


def validate_completeness(data, cases, blockers):
    rows = catalog(data)
    expected = {case_id(row) for row in rows}
    if not expected <= {c["case_id"] for c in cases}:
        raise ValueError("reviewed execution contract candidates missing")
    required = {MCP_BLOCKER, EXCEPTION_BLOCKER}
    for row in rows:
        required.update(required_blocker_ids(row))
    if not required <= {b["blocker_id"] for b in blockers}:
        raise ValueError("required execution contract blockers missing")
    return expected


def append_cases(data, add, blocker, ref):
    # The general v2 boundary issue is narrowed, not silently declared solved.
    blocker(
        "CONDITIONAL_MCP_BOUNDARY_UNRESOLVED",
        "chain.end_to_end",
        "Foreground internals are now allowed, but configured MCP connect is "
        "included while module.mcp remains prohibited. Offline cases explicitly "
        "use mcp_provider=None.",
        [
            ref("boundary.conversation", "/prohibited_module_ids"),
            bind_source(data, "execution_contract.json", pointer="/boundary/included"),
        ],
        "Clarify the configured MCP path; retain this gap for that conditional "
        "path only.",
    )
    exception_bid = blocker(
        "EXCEPTION_OBSERVER_NOT_IMPLEMENTED",
        "evidence.run_exception",
        "Exception/cancellation semantics are declared, but the evaluator-owned "
        "capture envelope is not implemented by the exporter.",
        [
            ref("evidence.run_exception", "/availability"),
            bind_source(
                data,
                "execution_contract.json",
                pointer="/exceptions/capture_implemented_by_exporter",
            ),
        ],
        "Implement and validate evaluator-owned exception and cancellation "
        "capture without fabricating native RunResult.",
    )
    add(
        "missing_exception_observer",
        "evidence.run_exception",
        "blocked_obligation",
        "missing_observer",
        "异常与取消捕获器尚未实现",
        {"operation": "bind_exception_observer"},
        [],
        [ref("evidence.run_exception", "/availability")],
        execution_readiness="blocked",
        source_basis="missing_contract",
        blocker_ids=[exception_bid],
    )
    for row in catalog(data):
        target = row["target_id"]
        refs = [bind_source(data, **source) for source in row["sources"]]
        for pointer in row["contract_keys"]:
            source = bind_source(data, "execution_contract.json", pointer=pointer)
            if source not in refs:
                refs.append(source)
        bid = blocker(
            "RUNTIME_BINDING_REQUIRED",
            target,
            "Expected contract behavior is specified; isolated fixture, runner "
            "and observation binding are still required. No execution or "
            "business acceptance has been verified.",
            [bind_source(data, "execution_contract.json", pointer="/remaining_gaps")],
            "Implement the explicit fixture and observation interface, then "
            "execute and review; do not guess business outcomes.",
        )
        bids = [bid]
        if any(p.startswith("/exceptions") for p in row["contract_keys"]):
            bids.append(exception_bid)
        add(
            "execution:" + row["key"],
            target,
            "behavior_candidate",
            row["category"],
            row["title"],
            row["input"],
            row["checks"],
            refs,
            layer=row["layer"],
            source_basis="execution_contract",
            execution_readiness="blocked",
            preconditions=row["preconditions"],
            runner_requirements=row["requirements"],
            blocker_ids=bids,
        )


def validate_mapped_case(data, case):
    rows = {case_id(row): row for row in catalog(data)}
    row = rows.get(case.case_id)
    if row is None:
        raise ValueError("unreviewed execution contract candidate")
    if (
        case.target_id != row["target_id"]
        or case.layer != row["layer"]
        or case.kind != "behavior_candidate"
        or case.source_basis != "execution_contract"
        or case.execution_readiness != "blocked"
        or case.blocker_ids != required_blocker_ids(row)
    ):
        raise ValueError("execution contract identity or blocking constraints changed")
    if (
        case.input != row["input"]
        or case.oracle != {"checks": row["checks"]}
        or case.preconditions != row["preconditions"]
        or case.runner_requirements != row["requirements"]
    ):
        raise ValueError("execution contract oracle or fixture mapping changed")
    actual = [r.model_dump(exclude_none=True) for r in case.source_refs]
    for source in row["sources"]:
        if bind_source(data, **source) not in actual:
            raise ValueError("missing execution source binding")
    for pointer in row["contract_keys"]:
        if bind_source(data, "execution_contract.json", pointer=pointer) not in actual:
            raise ValueError("missing contract predicate basis")

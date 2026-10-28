"""Static integrity and candidate checks; never executes target code."""

import json
from collections import Counter

from jsonschema import Draft202012Validator

from ..full_generation.inventory import pointer_value
from .cases import support
from .inputs import bind_source, safe_path
from .models import Candidate


def validate_cases(data, cases, blockers):
    issues = []
    ids = [c["case_id"] for c in cases]
    if len(ids) != len(set(ids)):
        issues.append("duplicate case_id")
    bids = [b["blocker_id"] for b in blockers]
    if len(bids) != len(set(bids)):
        issues.append("duplicate blocker_id")
    if {c["target_id"] for c in cases} != set(data["artifacts"]):
        issues.append("snapshot coverage incomplete")
    for blocker in blockers:
        if blocker["target_id"] not in data["artifacts"]:
            issues.append("unknown blocker target")
    for raw in cases:
        try:
            c = Candidate.model_validate(raw)
            if not c.case_id.startswith("nanobot:" + c.target_id + ":"):
                raise ValueError("case namespace mismatch")
            expected_status = support(data["artifacts"][c.target_id]["payload"])
            if c.support_status != expected_status:
                raise ValueError("capability support status changed")
            for ref in c.source_refs:
                bound = bind_source(
                    data, ref.path, pointer=ref.pointer, anchor=ref.anchor
                )
                if bound != ref.model_dump(exclude_none=True):
                    raise ValueError("source binding mismatch")
            if not set(c.blocker_ids) <= set(bids):
                raise ValueError("dangling blocker")
            checks = c.oracle.get("checks", [])
            if c.kind != "blocked_obligation" and not checks:
                raise ValueError("non-obligation missing checks")
            for check in checks:
                if set(check) != {"subject", "operator", "expected"}:
                    raise ValueError("malformed predicate")
                if check["operator"] not in {
                    "equals",
                    "contains",
                    "not_contains",
                    "ends_with",
                    "schema_valid",
                }:
                    raise ValueError("undefined predicate")
            if c.kind in {"schema_contract", "contract_check"}:
                if c.execution_readiness != "static_only":
                    raise ValueError("contract is static only")
            if c.kind == "blocked_obligation" and c.execution_readiness != "blocked":
                raise ValueError("obligation must stay blocked")
            if c.kind == "schema_contract":
                ref = c.input["schema_ref"]
                if ref not in raw["source_refs"]:
                    raise ValueError("unbound schema input")
                schema = pointer_value(
                    json.loads(safe_path(data["source_root"], ref["path"]).read_text()),
                    ref["pointer"],
                )
                actual = Draft202012Validator(schema).is_valid(c.input["instance"])
                if checks != [
                    {
                        "subject": "schema_validation.valid",
                        "operator": "equals",
                        "expected": actual,
                    }
                ]:
                    raise ValueError("schema oracle contradicts source")
                if c.input["invoke_handler"] is not False:
                    raise ValueError("schema test must not invoke tool")
            if c.kind == "contract_check":
                ref = c.input["source_ref"]
                if ref not in raw["source_refs"]:
                    raise ValueError("unbound declaration input")
                expected = pointer_value(
                    json.loads(safe_path(data["source_root"], ref["path"]).read_text()),
                    ref["pointer"],
                )
                if checks != [
                    {
                        "subject": "declared_value",
                        "operator": "equals",
                        "expected": expected,
                    }
                ]:
                    raise ValueError("declaration mismatch")
            if c.kind == "behavior_candidate":
                if (
                    c.support_status != "supported"
                    and c.execution_readiness != "blocked"
                ):
                    raise ValueError("unknown behavior must remain blocked")
                if not c.preconditions or not c.runner_requirements:
                    raise ValueError(
                        "behavior requires fixtures and adapter requirements"
                    )
                if c.source_basis == "implementation_derived":
                    if not any(
                        ref.path.startswith("sources/") and ref.anchor
                        for ref in c.source_refs
                    ):
                        raise ValueError(
                            "implementation-derived case lacks source anchor"
                        )
                    if not any(ref.path.startswith("bundle/") for ref in c.source_refs):
                        raise ValueError("behavior lacks snapshot binding")
                calls = []
                if c.input["operation"] == "invoke_tool":
                    calls = [c.input]
                elif c.input["operation"] == "tool_sequence":
                    calls = c.input["steps"]
                for call in calls:
                    name = call["tool_name"]
                    schema = data["artifacts"]["tool." + name]["parameter_schema"]
                    Draft202012Validator(schema).validate(call["arguments"])
                if c.layer == "end_to_end" and c.execution_readiness != "blocked":
                    raise ValueError("unresolved conversation boundary")
        except Exception as exc:
            issues.append(f"{raw.get('case_id')}: {exc}")
    for blocker in blockers:
        for ref in blocker["source_refs"]:
            try:
                if (
                    bind_source(
                        data, ref["path"], ref.get("pointer"), ref.get("anchor")
                    )
                    != ref
                ):
                    raise ValueError("blocker source mismatch")
            except Exception as exc:
                issues.append(f"{blocker['blocker_id']}: {exc}")
    return {
        "valid": not issues,
        "issues": issues,
        "runtime_execution": "NOT_RUN",
        "approval": "PENDING",
        "agent_id": "nanobot",
        "bundle_sha256": data["bundle_sha256"],
        "snapshot_count": len(data["artifacts"]),
        "primary_target_count": len(data["primary_targets"]),
        "case_count": len(cases),
        "counts_by_kind": dict(Counter(c["kind"] for c in cases)),
        "counts_by_layer": dict(Counter(c["layer"] for c in cases)),
        "counts_by_readiness": dict(Counter(c["execution_readiness"] for c in cases)),
        "blocker_count": len(blockers),
        "evalcase_count": 0,
        "validation_scope": (
            "source integrity, strict candidate"
            " protocol, schema expectations, re"
            "ferences and coverage; no Agent or"
            " business execution"
        ),
    }

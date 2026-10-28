"""Validate definitions and evaluator compatibility without running the Agent."""

import hashlib
import json
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from eval_contracts import load_dataset, validate_dataset
from eval_contracts.capabilities import (
    CapabilityBundle,
    CapabilityDocument,
    CapabilityRegistry,
)
from eval_contracts.schemas import EvalCase
from eval_contracts.tool_catalog import ToolCatalog, ToolContract
from jsonschema import Draft202012Validator

from .inventory import source_ref, verify_sources
from .models import Blocker, ContractCase, GenerationResult


def collect_blockers(result):
    found = {b.blocker_id: b for b in result.blockers}
    for c in result.cases:
        for bid in c.blocker_ids:
            if bid not in found and bid == "BINDING-" + c.slot_id:
                found[bid] = Blocker(
                    blocker_id=bid,
                    affected_slot_ids=[c.slot_id],
                    reason=c.payload["oracle"].get(
                        "unresolved", "Concrete runtime binding is unavailable."
                    ),
                    source_refs=c.payload["source_refs"],
                    required_action=(
                        "Define explicit stimulus and predicate bin"
                        "dings before execution."
                    ),
                )
    return list(found.values())


def evaluator_context(inv):
    docs = []
    contracts = {}
    for ident, artifact in inv.artifacts.items():
        d = artifact["payload"]
        docs.append(
            CapabilityDocument(
                snapshot_id=ident,
                snapshot_type=d["snapshot_type"],
                snapshot_format_version=d["snapshot_format_version"],
                contract_version=d["contract_version"],
                snapshot_sha256=artifact["snapshot_sha256"],
                module_id=d.get("module_id"),
                capability_id=d.get("capability_id"),
                payload=d,
            )
        )
        if d["snapshot_type"] == "tool":
            # Explicit v3 -> legacy catalog translation for static validation.
            # This is not a runtime registry factory or a mutation of the Bundle.
            name = d["tool_name"]
            contracts[name] = ToolContract(
                name=name,
                operation="write" if d.get("side_effects") else "read",
                fault_modes=frozenset(),
            )
    registry = CapabilityRegistry(
        CapabilityBundle(
            root=inv.bundle_path,
            provider_id="mini_agent",
            bundle_format_version="3.0",
            capability_bundle_sha256=inv.bundle_sha256,
            documents=tuple(docs),
        )
    )
    catalog = ToolCatalog(
        profiles={"full_fixture": frozenset(contracts)}, tools=contracts
    )
    return registry, catalog


def validate_generation(result: GenerationResult) -> dict:
    issues = []
    inv = result.inventory
    try:
        verify_sources(inv)
    except (ValueError, OSError) as exc:
        issues.append(str(exc))
    slots = {s.slot_id: s for s in result.slots}
    if len(slots) != len(result.slots):
        issues.append("duplicate slot_id")
    blockers = collect_blockers(result)
    by_blocker = {b.blocker_id: b for b in blockers}
    for b in blockers:
        if set(b.affected_slot_ids) - set(slots):
            issues.append(f"dangling blocker slots: {b.blocker_id}")
    cases_by_slot = Counter(c.slot_id for c in result.cases)
    for s in result.slots:
        if not cases_by_slot[s.slot_id] and not s.blocker_ids:
            issues.append("uncovered slot: " + s.slot_id)
    ids = [c.payload.get("case_id") for c in result.cases]
    if len(set(ids)) != len(ids):
        issues.append("duplicate case_id")
    evaluator_cases = []
    execution_keys = set()
    for c in result.cases:
        s = slots.get(c.slot_id)
        if s is None:
            issues.append("dangling case slot: " + c.slot_id)
            continue
        try:
            for bid in c.blocker_ids:
                if bid not in by_blocker:
                    raise ValueError("unknown blocker: " + bid)
            for ref in s.source_refs:
                if source_ref(inv, ref.snapshot_id, ref.pointer) != ref:
                    raise ValueError("source binding mismatch")
            if c.dataset_format == "eval_case":
                case = EvalCase.model_validate(c.payload)
                key = (
                    case.test_scope,
                    case.target,
                    case.task_id,
                    case.execution.user_input,
                )
                if key in execution_keys:
                    raise ValueError("duplicate input within same target/task")
                execution_keys.add(key)
                serialized = json.dumps(case.execution.model_dump()).lower()
                if any(
                    x in serialized
                    for x in ("oracle", "expected_", "标准答案", "case_id")
                ):
                    raise ValueError("execution leakage")
                expected = case.oracle.expected_module_output
                if expected:
                    d = inv.artifacts["intent." + expected["intent"]]["payload"]
                    Draft202012Validator(d["parameters_schema"]).validate(
                        expected["parameters"]
                    )
                    if set(expected["missing_parameters"]) - set(
                        d["parameter_semantics"]["missing_parameters"]
                    ):
                        raise ValueError("unknown missing parameter")
                    if not any(
                        expected["status"] == rule.get("status")
                        and expected["next_action"] == rule.get("next_action")
                        for rule in d["decision_rules"].values()
                        if isinstance(rule, dict)
                    ):
                        raise ValueError("decision/action mismatch")
                evaluator_cases.append(case)
            else:
                case = ContractCase.model_validate(c.payload)
                if case.slot_id != c.slot_id or case.target_id != s.target_id:
                    raise ValueError("contract target/slot mismatch")
                for ref in case.source_refs:
                    if source_ref(inv, ref.snapshot_id, ref.pointer) != ref:
                        raise ValueError("contract source mismatch")
                if not case.oracle.get("checks") and c.execution_readiness != "blocked":
                    raise ValueError("non-blocked contract requires checks")
                for check in case.oracle.get("checks", []):
                    if check["op"] not in {
                        "schema_valid",
                        "equals",
                        "subset",
                        "sequence",
                        "count",
                        "unchanged",
                    }:
                        raise ValueError("undefined predicate")
                if "arguments_schema_valid" in case.oracle:
                    d = inv.artifacts[s.target_id]["payload"]
                    schema = d.get("function_schema", {}).get(
                        "parameters", d.get("parameters_schema")
                    )
                    actual = Draft202012Validator(schema).is_valid(
                        case.input["arguments"]
                    )
                    if actual != case.oracle["arguments_schema_valid"]:
                        raise ValueError("parameter oracle contradicts schema")
                if (
                    "arguments" in case.input
                    and case.input.get("operation") == "invoke_tool"
                ):
                    schema = inv.artifacts[s.target_id]["payload"]["function_schema"][
                        "parameters"
                    ]
                    Draft202012Validator(schema).validate(case.input["arguments"])
        except Exception as exc:
            issues.append(f"{c.payload.get('case_id')}: {exc}")
    try:
        registry, catalog = evaluator_context(inv)
        with TemporaryDirectory(prefix="full-eval-validate-") as td:
            path = Path(td) / "draft.jsonl"
            path.write_text(
                "".join(
                    json.dumps(c.model_dump(mode="json"), ensure_ascii=False) + "\n"
                    for c in evaluator_cases
                )
            )
            path.with_suffix(".manifest.json").write_text(
                json.dumps(
                    {
                        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "state": "DRAFT",
                        "dataset_version": "full-fixture-1.0",
                        "execution_profiles": {
                            "full_fixture": {
                                "allowed_tools": sorted(
                                    v["payload"]["tool_name"]
                                    for v in inv.artifacts.values()
                                    if v["payload"]["snapshot_type"] == "tool"
                                )
                            }
                        },
                    }
                )
            )
            bundle = load_dataset(path)
            report = validate_dataset(bundle, capabilities=registry, tools=catalog)
            issues.extend(
                f"{i.case_id}: {i.field_path}: {i.message}" for i in report.issues
            )
    except Exception as exc:
        issues.append(f"evaluator validation unavailable: {exc}")
    targets = {t["snapshot_id"] for t in inv.targets}
    if {s.target_id for s in result.slots} != targets:
        issues.append("target inventory does not match plan")
    return {
        "valid": not issues,
        "issues": issues,
        "runtime_execution": "NOT_RUN",
        "approval": "PENDING",
        "coverage": {
            "target_count": len(targets),
            "slot_count": len(slots),
            "accounted_slot_count": sum(
                bool(cases_by_slot[s])
                or any(s in b.affected_slot_ids for b in blockers)
                for s in slots
            ),
        },
        "counts": {
            "dataset_format": dict(Counter(c.dataset_format for c in result.cases)),
            "execution_readiness": dict(
                Counter(c.execution_readiness for c in result.cases)
            ),
            "coverage_mode": dict(Counter(c.coverage_mode for c in result.cases)),
        },
        "compatibility": (
            "EvalCase validation uses explicit source-d"
            "erived v3 ToolCatalog translation; runtime"
            " binding is separate."
        ),
    }

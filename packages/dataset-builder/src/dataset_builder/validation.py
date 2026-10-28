"""Contract, evaluator, quality, and aggregate validation gates."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from eval_contracts import load_dataset, validate_dataset
from eval_contracts.capabilities import (
    CapabilityBundle as RuntimeCapabilityBundle,
)
from eval_contracts.capabilities import (
    CapabilityDocument,
    CapabilityRegistry,
)
from eval_contracts.schemas import EvalCase
from eval_contracts.tool_catalog import ToolCatalog, ToolContract
from pydantic import ValidationError

from .capability_bundle import CapabilityBundleError
from .coverage import coverage_gate, duplicate_gate
from .leakage import leakage_gate
from .schemas import GateResult, ValidationSummary
from .source_pack import sha256_file
from .suite_definition import SuiteDefinition


def evaluator_gate(
    path: Path, suite: SuiteDefinition
) -> tuple[GateResult, list[EvalCase]]:
    try:
        bundle = load_dataset(path)
        runtime_suite = _generation_bound_suite(suite, path)
        capabilities, tools = _runtime_contracts(runtime_suite, bundle.cases)
        report = validate_dataset(bundle, capabilities=capabilities, tools=tools)
    except Exception as exc:
        return GateResult(name="evaluator", passed=False, issues=[str(exc)]), []
    issues = [
        f"{issue.case_id}:{issue.field_path}: {issue.message}"
        for issue in report.issues
    ]
    expected_count = suite.coverage_plan["case_count"]
    if bundle.total_count != expected_count:
        issues.append(
            f"evaluator loaded {bundle.total_count}, expected {expected_count}"
        )
    if bundle.schema_versions != ["1.0"]:
        issues.append(f"unexpected schema versions {bundle.schema_versions}")
    return (
        GateResult(
            name="evaluator",
            passed=report.valid and not issues,
            issues=issues,
            details={
                "dataset_sha256": bundle.sha256,
                "total_count": bundle.total_count,
                "schema_versions": bundle.schema_versions,
                "validator_valid": report.valid,
            },
        ),
        bundle.cases,
    )


def _runtime_contracts(
    suite: SuiteDefinition, cases: list[EvalCase]
) -> tuple[CapabilityRegistry | None, ToolCatalog]:
    source = suite.validated_capability_bundle
    documents = tuple(
        CapabilityDocument(
            snapshot_id=item.snapshot_id,
            snapshot_type=item.snapshot_type,
            snapshot_format_version=item.snapshot_format_version,
            contract_version=item.contract_version,
            snapshot_sha256=item.snapshot_sha256,
            module_id=item.payload.get("module_id"),
            capability_id=item.payload.get("capability_id"),
            payload=dict(item.payload),
        )
        for item in source.artifacts
    )
    capabilities = CapabilityRegistry(
        RuntimeCapabilityBundle(
            root=str(suite.suite_dir),
            provider_id=suite.target_agent,
            bundle_format_version="3.0",
            capability_bundle_sha256=source.capability_bundle_sha256,
            documents=documents,
        )
    )
    profile_tools: dict[str, set[str]] = {}
    write_tools: set[str] = set()
    for case in cases:
        names = set(case.execution.allowed_tools or [])
        names.update(case.execution.fault_injection)
        names.update(item.name for item in case.oracle.expected_tool_calls)
        names.update(case.oracle.forbidden_tools)
        profile_tools.setdefault(case.execution.tool_profile, set()).update(names)
        if case.cleanup is not None or case.execution.user_responses:
            write_tools.update(names)
    contracts = {
        name: ToolContract(
            name=name,
            operation="write" if name in write_tools else "read",
            fault_modes=frozenset(
                {"normal", "empty_result", "error", "timeout", "commit_then_timeout"}
            ),
        )
        for name in set().union(*profile_tools.values())
    }
    return capabilities, ToolCatalog(
        profiles={name: frozenset(tools) for name, tools in profile_tools.items()},
        tools=contracts,
    )


def _generation_bound_suite(suite: SuiteDefinition, draft: Path) -> SuiteDefinition:
    bundle_root = draft.parent / "capability_bundle"
    if not bundle_root.is_dir():
        raise CapabilityBundleError(["generation_capability_bundle_missing"])
    return replace(suite, capability_bundle_path=bundle_root)


def quality_gate(cases: list[EvalCase], suite: SuiteDefinition) -> GateResult:
    issues: list[str] = []
    policy = suite.quality_policy
    excluded = tuple(policy.forbidden_phrases + policy.sensitive_phrases)
    for case in cases:
        text = case.execution.user_input.strip()
        if len(text) < policy.minimum_input_length:
            issues.append(f"{case.case_id}: input is too short to be unambiguous")
        lowered = text.casefold()
        if any(value.casefold() in lowered for value in excluded):
            issues.append(f"{case.case_id}: excluded, unsafe, or live-data scenario")
        intent = case.oracle.expected_module_output["intent"]
        if (
            any(marker in text for marker in policy.compound_markers)
            and intent in policy.compound_forbidden_intents
        ):
            issues.append(f"{case.case_id}: possible compound intent")
    return GateResult(name="quality", passed=not issues, issues=issues)


def capability_snapshot_gate(suite: SuiteDefinition, draft: Path) -> GateResult | None:
    bundle_root = draft.parent / "capability_bundle"
    manifest_path = draft.parent / "generation_manifest.json"
    issues: list[str] = []
    details: dict[str, Any] = {
        "generated_bundle_sha256": None,
        "current_bundle_sha256": None,
        "generated_ir_sha256": None,
        "current_ir_sha256": None,
        "impacted_slots": [],
        "impacted_seeds": [],
        "changed_bindings": [],
    }
    try:
        if not manifest_path.is_file():
            raise CapabilityBundleError(["generation_manifest_missing"])
        manifest = json.loads(manifest_path.read_text())
        raw_hash = manifest.get("raw_response_sha256")
        raw_path = draft.parent / "raw_response.json"
        if raw_hash is not None:
            if not raw_path.is_file() or sha256_file(raw_path) != raw_hash:
                issues.append("generation raw response hash mismatch or file missing")
        elif manifest.get("generation_mode") == "deepeval":
            issues.append("DeepEval raw response hash missing")
        request_path = draft.parent / "generation_request.json"
        if not request_path.is_file():
            raise CapabilityBundleError(["generation_request_missing"])
        request = json.loads(request_path.read_text())
        generated_suite = replace(suite, capability_bundle_path=bundle_root)
        generated = generated_suite.validated_capability_bundle
        generated_ir = generated_suite.capability_ir
        current = suite.validated_capability_bundle
        current_ir = suite.capability_ir
        details["generated_bundle_sha256"] = generated.capability_bundle_sha256
        details["current_bundle_sha256"] = current.capability_bundle_sha256
        details["generated_ir_sha256"] = generated_ir.canonical_sha256
        details["current_ir_sha256"] = current_ir.canonical_sha256
        if manifest.get("source_manifest") != request.get("source_manifest"):
            issues.append("generation source manifest binding mismatch")
        if manifest.get("execution_profiles") != request.get("execution_profiles"):
            issues.append("generation execution profile binding mismatch")
        expected_profiles = {
            name: profile.model_dump(mode="json")
            for name, profile in suite.config.execution_profiles.items()
        }
        if request.get("execution_profiles") != expected_profiles:
            issues.append("generation request execution profiles differ from suite")
        expected = {
            "profile_binding": request.get("profile_binding"),
            "trusted_schema_bindings": request.get("trusted_schema_bindings"),
            "adapter_binding": request.get("adapter_binding"),
            "capability_ir_binding": request.get("capability_ir_binding"),
            "capability_selection": request.get("capability_selection"),
            "capability_source_artifacts": request.get(
                "capability_source_artifacts"
            ),
            "capability_bundle_sha256": request.get(
                "capability_bundle_sha256"
            ),
            "agent_snapshot_sha256": request.get("agent_snapshot_sha256"),
        }
        for name, value in expected.items():
            if manifest.get(name) != value:
                issues.append(f"generation manifest {name} binding mismatch")
                details["changed_bindings"].append(name)
        current_bindings = {
            "profile_binding": {
                "profile_id": suite.capability_profile.profile.profile_id,
                "profile_version": suite.capability_profile.profile.protocol_version,
                "path": str(suite.capability_profile.path),
                "sha256": suite.capability_profile.sha256,
            },
            "trusted_schema_bindings": [
                {
                    "schema_id": item.schema_id,
                    "relative_path": item.relative_path,
                    "sha256": item.sha256,
                }
                for item in current.schema_bindings
            ],
            "adapter_binding": {
                "protocol": suite.capability_adapter_registration.key.protocol,
                "version": suite.capability_adapter_registration.key.version,
                "implementation_sha256": (
                    suite.capability_adapter_registration.implementation_sha256
                ),
            },
            "capability_ir_binding": {
                "schema_version": current_ir.schema_version,
                "sha256": current_ir.canonical_sha256,
            },
            "capability_selection": current_ir.selection.model_dump(mode="json"),
            "capability_source_artifacts": [
                item.model_dump(mode="json")
                for item in current_ir.source_artifacts
            ],
            "capability_bundle_sha256": current.capability_bundle_sha256,
            "agent_snapshot_sha256": current.root.snapshot_sha256,
        }
        for name, value in current_bindings.items():
            if request.get(name) != value:
                issues.append(f"current {name} differs from generation binding")
                details["changed_bindings"].append(name)
        if generated_ir.canonical_sha256 != request.get(
            "capability_ir_binding", {}
        ).get("sha256"):
            issues.append("generated Capability IR hash mismatch")
            details["changed_bindings"].append("generated_capability_ir")
        if issues:
            details["impacted_slots"] = [
                slot["slot_id"] for slot in suite.coverage_plan["slots"]
            ]
            details["impacted_seeds"] = details["impacted_slots"]
    except (
        CapabilityBundleError,
        ValidationError,
        OSError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
    ) as exc:
        issues.append(f"generation snapshot binding invalid: {exc}")
    return GateResult(
        name="capability_snapshot",
        passed=not issues,
        issues=issues,
        details=details,
    )


def write_jsonl(cases: list[EvalCase], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "\n".join(
            json.dumps(
                case.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            for case in cases
        )
        + "\n"
    )
    path.write_text(content)


def validate_draft_file(suite: SuiteDefinition, draft: Path) -> ValidationSummary:
    evaluator, cases = evaluator_gate(draft, suite)
    enabled = (
        set(suite.policy_set.validation.config.enabled_gates)
        if suite.policy_set is not None
        else {
            "evaluator",
            "capability_snapshot",
            "contract",
            "coverage",
            "duplicate",
            "leakage",
            "quality",
        }
    )
    gates = [evaluator] if "evaluator" in enabled else []
    snapshot_gate = (
        capability_snapshot_gate(suite, draft)
        if "capability_snapshot" in enabled
        else None
    )
    if snapshot_gate is not None:
        gates.append(snapshot_gate)
    if cases:
        contract_suite = _generation_bound_suite(suite, draft)
        if "contract" in enabled:
            contract_issues: list[str] = []
            for validator in suite.validators:
                try:
                    contract_issues.extend(validator(cases, contract_suite))
                except (CapabilityBundleError, ValidationError) as exc:
                    contract_issues.append(
                        f"generation capability contract unavailable: {exc}"
                    )
            gates.append(
                GateResult(
                    name="contract",
                    passed=not contract_issues,
                    issues=contract_issues,
                )
            )
        if "coverage" in enabled:
            gates.append(coverage_gate(cases, suite))
        if "duplicate" in enabled:
            gates.append(duplicate_gate(cases))
        if "leakage" in enabled:
            gates.append(leakage_gate(cases))
        if "quality" in enabled:
            gates.append(quality_gate(cases, suite))
    valid = bool(gates) and all(gate.passed for gate in gates)
    stale = snapshot_gate is not None and not snapshot_gate.passed
    return ValidationSummary(
        state="VALIDATED" if valid else ("STALE" if stale else "DRAFT"),
        valid=valid,
        draft_sha256=sha256_file(draft),
        case_count=len(cases),
        gates=gates,
    )


def dump_report(report: Any, path: Path) -> None:
    path.write_text(report.model_dump_json(indent=2))

"""Cross-field validation against explicit frozen capability contracts."""

from __future__ import annotations

from pathlib import Path

from jsonschema import Draft202012Validator

from .assertions import ASSERTION_SCOPES
from .capabilities import CapabilityRegistry
from .capability_loader import load_capability_bundle
from .evidence_requirements import evidence_requirement_issues
from .observation_assertions import ObservationCheckConfig
from .schemas import DatasetBundle, ValidationIssue, ValidationReport
from .tool_catalog import ToolCatalog, ToolCatalogError
from .turn_assertions import TurnCheckConfig


def validate_dataset(
    dataset: DatasetBundle,
    capabilities: CapabilityRegistry | None = None,
    tools: ToolCatalog | None = None,
    *,
    environment_state_available: bool = False,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    if capabilities is None and dataset.capability_bundle_path is not None:
        try:
            bundle = load_capability_bundle(Path(dataset.capability_bundle_path))
            if bundle.capability_bundle_sha256 != dataset.capability_bundle_sha256:
                raise ToolCatalogError("dataset capability bundle hash mismatch")
            capabilities = CapabilityRegistry(bundle)
        except (OSError, ValueError) as exc:
            issues.append(
                ValidationIssue(
                    case_id=None,
                    field_path="capability_bundle",
                    message=f"capability bundle unavailable: {exc}",
                )
            )
    if tools is None and capabilities is not None:
        try:
            tools = ToolCatalog.from_registry(
                capabilities,
                profiles=dataset.execution_profiles,
            )
        except ToolCatalogError as exc:
            issues.append(
                ValidationIssue(
                    case_id=None,
                    field_path="capability_bundle.tool_catalog",
                    message=str(exc),
                )
            )
    if tools is None:
        issues.append(
            ValidationIssue(
                case_id=None,
                field_path="capability_bundle.tool_catalog",
                message="tool catalog is required for dataset validation",
            )
        )
        return ValidationReport(valid=False, issues=issues)

    for case in dataset.cases:

        def add(field: str, message: str, *, case_id: str = case.case_id) -> None:
            issues.append(
                ValidationIssue(case_id=case_id, field_path=field, message=message)
            )

        oracle = case.oracle
        if capabilities is not None:
            for message in evidence_requirement_issues(
                case,
                capabilities,
                environment_state_available=environment_state_available,
            ):
                add("oracle.evaluation.checks", message)
        execution = case.execution
        observation_only = all(
            check.name == "observations_match" for check in oracle.evaluation.checks
        )
        if (
            not observation_only
            and case.test_scope == "module"
            and oracle.expected_module_output is None
        ):
            add("oracle.expected_module_output", "module requires expected output")
        if not observation_only and case.test_scope == "link" and not (
            oracle.expected_tool_calls or oracle.forbidden_tools
        ):
            add("oracle", "link requires expected or forbidden tool constraints")
        if (
            not observation_only
            and case.test_scope == "end_to_end"
            and oracle.goal_state is None
        ):
            add("oracle.goal_state", "end_to_end requires goal_state")
        try:
            available = tools.tools_for_profile(execution.tool_profile)
        except KeyError:
            add(
                "execution.tool_profile",
                f"unknown tool profile {execution.tool_profile!r}",
            )
            available = frozenset()
        for tool in execution.allowed_tools or []:
            if tool not in available:
                add("execution.allowed_tools", f"tool {tool!r} is outside profile")
        referenced = [item.name for item in oracle.expected_tool_calls]
        referenced.extend(oracle.forbidden_tools)
        for tool in referenced:
            if tool not in available:
                add("oracle", f"tool {tool!r} is outside profile")
        for tool, mode in execution.fault_injection.items():
            if tool not in available:
                add("execution.fault_injection", f"unknown profile tool {tool!r}")
                continue
            try:
                contract = tools.get_tool(tool)
            except KeyError:
                add("execution.fault_injection", f"unknown tool {tool!r}")
                continue
            if mode not in contract.fault_modes:
                add(
                    "execution.fault_injection",
                    f"tool {tool!r} does not support fault mode {mode!r}",
                )
        expected = oracle.expected_module_output or {}
        if expected and capabilities is not None:
            try:
                module = capabilities.get_module(case.target)
                schema = module.payload["output_schema"]
                Draft202012Validator(schema).validate(expected)
            except Exception as exc:
                add(
                    "oracle.expected_module_output",
                    f"invalid public intent output: {exc}",
                )
        writes = any(
            tools.get_tool(name).operation == "write"
            for name in (call.name for call in oracle.expected_tool_calls)
            if name in available
        )
        if writes and (not execution.user_responses or case.cleanup is None):
            add("execution.user_responses", "write case requires responses and cleanup")
        for check in oracle.evaluation.checks:
            if check.name == "observations_match":
                try:
                    observation = ObservationCheckConfig.model_validate(check.config)
                    if (
                        observation.channel == "independent"
                        and not environment_state_available
                        and capabilities is None
                    ):
                        add(
                            "oracle.evaluation.checks",
                            "observations_match: independent environment evidence "
                            "is unavailable",
                        )
                except ValueError as exc:
                    add(
                        "oracle.evaluation.checks",
                        f"invalid observations_match config: {exc}",
                    )
            if check.name == "turns_match":
                try:
                    TurnCheckConfig.model_validate(check.config)
                except ValueError as exc:
                    add(
                        "oracle.evaluation.checks", f"invalid turns_match config: {exc}"
                    )
            scopes = ASSERTION_SCOPES.get(check.name)
            if scopes is None:
                add("oracle.evaluation.checks", f"unsupported assertion {check.name!r}")
            elif case.test_scope not in scopes:
                add(
                    "oracle.evaluation.checks",
                    f"assertion {check.name!r} does not support {case.test_scope}",
                )
    return ValidationReport(valid=not issues, issues=issues)

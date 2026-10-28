"""Coverage and duplicate analysis."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from eval_contracts.schemas import EvalCase

from .intent_validation import resolve_json_pointer
from .scenario_requirements import scenario_issues
from .schemas import GateResult
from .suite_definition import SuiteDefinition


def _distribution_key(payload: dict[str, Any], pointers: list[str]):
    values = tuple(resolve_json_pointer(payload, pointer) for pointer in pointers)
    return values[0] if len(values) == 1 else values


def _serialize_distribution(counter: Counter) -> dict[str, int]:
    return {
        (
            "/".join(str(part) for part in key)
            if isinstance(key, tuple)
            else str(key)
        ): count
        for key, count in sorted(counter.items(), key=lambda item: str(item[0]))
    }


def coverage_gate(cases: list[EvalCase], suite: SuiteDefinition) -> GateResult:
    plan = suite.coverage_plan
    issues: list[str] = []
    details: dict[str, Any] = {"case_count": len(cases)}
    if len(cases) != plan["case_count"]:
        issues.append(f"expected {plan['case_count']} cases, found {len(cases)}")

    case_payloads = [case.model_dump(mode="json") for case in cases]
    for distribution in suite.coverage_config.distribution_fields:
        actual = Counter(
            _distribution_key(payload, distribution.case_pointers)
            for payload in case_payloads
        )
        if distribution.plan_field is None:
            expected = Counter(
                (
                    tuple(slot[field] for field in distribution.slot_fields)
                    if len(distribution.slot_fields) > 1
                    else slot[distribution.slot_fields[0]]
                )
                for slot in plan["slots"]
            )
        else:
            declared = plan.get(distribution.plan_field)
            if not isinstance(declared, dict):
                issues.append(
                    f"{distribution.report_name} is required in coverage plan"
                )
                expected = Counter()
            else:
                expected = Counter(declared)

        if distribution.case_pointers == ["/scenario_type"]:
            mapped = suite.compilation_config.scenario_type_map
            allowed = {
                mapped.get(value, value)
                for value in suite.candidate_protocol_config.allowed_scenario_types
            }
            declared = plan.get(distribution.plan_field or "")
            if not isinstance(declared, dict) or set(declared) != allowed:
                issues.append(
                    "scenario type distribution is required with all "
                    "supported values"
                )
        if actual != expected:
            label = (
                "scenario type distribution"
                if distribution.case_pointers == ["/scenario_type"]
                else distribution.report_name
            )
            issues.append(
                f"{label} mismatch: "
                f"actual={dict(actual)} expected={dict(expected)}"
            )
        details[distribution.report_name] = _serialize_distribution(actual)

    intents = {
        case.oracle.expected_module_output["intent"] for case in cases
    }
    found = sorted(intents & set(suite.validation_config.forbidden_intents))
    if found:
        issues.append(f"forbidden intents present: {found}")
    issues.extend(scenario_issues(cases, suite))
    return GateResult(
        name="coverage",
        passed=not issues,
        issues=issues,
        details=details,
    )


def _normalized(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold())


def duplicate_gate(cases: list[EvalCase]) -> GateResult:
    case_ids = [case.case_id for case in cases]
    inputs = [case.execution.user_input for case in cases]
    normalized = [_normalized(item) for item in inputs]
    exact = sorted(item for item, count in Counter(inputs).items() if count > 1)
    norm = sorted(
        item for item, count in Counter(normalized).items() if count > 1
    )
    duplicate_ids = sorted(
        item for item, count in Counter(case_ids).items() if count > 1
    )
    issues = []
    if duplicate_ids:
        issues.append(f"duplicate case_id: {duplicate_ids}")
    if exact:
        issues.append(f"exact duplicate inputs: {exact}")
    return GateResult(
        name="duplicate",
        passed=not issues,
        issues=issues,
        details={"normalized_near_duplicates": norm},
    )

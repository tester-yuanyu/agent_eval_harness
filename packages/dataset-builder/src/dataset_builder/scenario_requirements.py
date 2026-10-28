"""Bounded, source-backed acceptance checks; not a natural-language oracle."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .intent_validation import (
    _label_prefix,
    resolve_json_pointer,
    validate_module_intent_contract,
)


class ScenarioRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    description: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    input_must_match: list[str] = Field(default_factory=list)
    input_must_not_match: list[str] = Field(default_factory=list)
    parameter_keys: list[str] | None = None
    parameter_values: dict[str, Any] = Field(default_factory=dict)
    values_pattern: str | None = None
    distinct_values: int | None = Field(default=None, ge=1)
    minimum_distinct_values: int | None = Field(default=None, ge=1)
    minimum_value_occurrences: int | None = Field(default=None, ge=1)
    use_last_value_for: str | None = None
    require_parameter_grounding: bool = True
    oracle_gaps: dict[Literal["missing_parameters"], str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_patterns(self):
        for pattern in self.input_must_match + self.input_must_not_match:
            re.compile(pattern)
        if self.values_pattern is not None:
            compiled = re.compile(self.values_pattern)
            if compiled.groups:
                raise ValueError("values_pattern must not contain capture groups")
        elif any(
            value is not None
            for value in (
                self.distinct_values,
                self.minimum_distinct_values,
                self.minimum_value_occurrences,
                self.use_last_value_for,
            )
        ):
            raise ValueError("value checks require values_pattern")
        return self


def load_requirements(suite) -> dict[str, ScenarioRequirement]:
    plan = suite.coverage_plan
    version = plan.get("scenario_requirements_version")
    if version is None:
        if any("acceptance" in slot for slot in plan["slots"]):
            raise ValueError("acceptance requires scenario_requirements_version")
        return {}
    if version != "1.0":
        raise ValueError("unsupported scenario_requirements_version")
    payload = suite.capability_ir.model_dump(mode="json")
    result = {}
    for slot in plan["slots"]:
        try:
            requirement = ScenarioRequirement.model_validate(slot.get("acceptance"))
            for pointer in requirement.evidence_refs:
                if not pointer.startswith("/"):
                    raise ValueError("evidence_refs must be IR JSON pointers")
                resolve_json_pointer(payload, pointer)
            names = set(payload["parameters_schema"].get("properties", {}))
            referenced = set(requirement.parameter_keys or []) | set(
                requirement.parameter_values
            )
            if requirement.use_last_value_for:
                referenced.add(requirement.use_last_value_for)
            if referenced - names:
                raise ValueError("requirement references unknown parameters")
            if slot["slot_id"] in result:
                raise ValueError("duplicate slot requirement")
            result[slot["slot_id"]] = requirement
        except (ValueError, re.error) as exc:
            raise ValueError(
                f"slot {slot['slot_id']}: invalid acceptance: {exc}"
            ) from exc
    return result


def check_requirement(
    text: str, parameters: dict | None, requirement: ScenarioRequirement
) -> list[str]:
    issues = []
    for pattern in requirement.input_must_match:
        if not re.search(pattern, text, re.IGNORECASE):
            issues.append(f"input must match {pattern!r}")
    for pattern in requirement.input_must_not_match:
        if re.search(pattern, text, re.IGNORECASE):
            issues.append(f"input must not match {pattern!r}")
    if (
        parameters is not None
        and requirement.parameter_keys is not None
        and set(parameters) != set(requirement.parameter_keys)
    ):
        issues.append(f"parameter keys must equal {requirement.parameter_keys}")
    for name, expected in (
        requirement.parameter_values.items() if parameters is not None else []
    ):
        if parameters.get(name) != expected:
            issues.append(
                f"{name} does not satisfy selected boundary value {expected!r}"
            )
    if parameters is not None and requirement.require_parameter_grounding:
        for name, value in parameters.items():
            token = re.escape(str(value))
            boundary = (
                r"[0-9.+-]"
                if isinstance(value, int) or str(value).isdigit()
                else r"[A-Za-z0-9_@.+-]"
            )
            if not re.search(f"(?<!{boundary}){token}(?!{boundary})", text):
                issues.append(f"{name}: value is not grounded in input")
    if requirement.values_pattern:
        values = re.findall(requirement.values_pattern, text, re.IGNORECASE)
        if (
            requirement.distinct_values is not None
            and len(set(values)) != requirement.distinct_values
        ):
            issues.append(
                f"expected {requirement.distinct_values} distinct input values"
            )
        if (
            requirement.minimum_distinct_values is not None
            and len(set(values)) < requirement.minimum_distinct_values
        ):
            issues.append(
                f"expected at least {requirement.minimum_distinct_values} "
                "distinct input values"
            )
        if (
            requirement.minimum_value_occurrences is not None
            and len(values) < requirement.minimum_value_occurrences
        ):
            issues.append(
                f"expected at least {requirement.minimum_value_occurrences} "
                "input value occurrences"
            )
        if parameters is not None and requirement.use_last_value_for:
            actual = parameters.get(requirement.use_last_value_for)
            if not values or str(actual) != values[-1]:
                issues.append(
                    f"{requirement.use_last_value_for}: must use final input value"
                )
    return issues


def scenario_issues(cases, suite, *, include_contract_gaps: bool = True) -> list[str]:
    requirements = load_requirements(suite)
    if not requirements:
        return []
    prefix = _label_prefix(suite, "slot", "slot_id")
    if prefix is None:
        raise ValueError("scenario requirements need a slot label binding")
    issues = []
    for case in cases:
        labels = [
            label.removeprefix(prefix)
            for label in case.labels
            if label.startswith(prefix)
        ]
        if len(labels) != 1 or labels[0] not in requirements:
            issues.append(f"{case.case_id}: missing or unknown scenario requirement")
            continue
        requirement = requirements[labels[0]]
        if include_contract_gaps:
            issues.extend(
                f"{case.case_id}: unresolved oracle contract {field}: {reason}"
                for field, reason in requirement.oracle_gaps.items()
            )
        expected = case.oracle.expected_module_output or {}
        parameters = expected.get("parameters", {})
        if not isinstance(parameters, dict):
            issues.append(f"{case.case_id}: parameters must be an object")
            continue
        issues.extend(
            f"{case.case_id}: {issue}"
            for issue in check_requirement(
                case.execution.user_input, parameters, requirement
            )
        )
    return issues


def candidate_issues(candidate: dict, suite, slot: dict) -> list[str]:
    from .intent_compiler import compile_intent_candidates

    issues = []
    for field, planned in (
        ("slot_id", "slot_id"),
        ("expected_intent", "intent"),
        ("expected_status", "status"),
        ("scenario_type", "scenario_type"),
        ("rule_refs", "rule_refs"),
    ):
        if candidate.get(field) != slot.get(planned):
            issues.append(f"{field} does not match coverage slot")
    if issues:
        return issues
    try:
        batch = suite.batch_type.model_validate({"candidates": [candidate]})
        parameters = json.loads(candidate["expected_parameters_json"])
        if not isinstance(parameters, dict):
            return ["expected parameters must be an object"]
        cases = compile_intent_candidates(batch.candidates, suite, allow_partial=True)
    except (ValueError, TypeError) as exc:
        return [str(exc)]
    return validate_module_intent_contract(
        cases, suite, require_all_slots=False
    ) + scenario_issues(cases, suite, include_contract_gaps=False)

"""Configuration and capability-driven validation for module intent cases."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from eval_framework.schemas import EvalCase
from jsonschema import Draft202012Validator

if TYPE_CHECKING:
    from .suite_definition import SuiteDefinition


def resolve_json_pointer(payload: dict[str, Any], pointer: str) -> Any:
    value: Any = payload
    for raw_part in pointer.lstrip("/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"JSON pointer {pointer!r} does not exist")
        value = value[part]
    return value


def validate_parameters(
    parameters: dict[str, Any],
    schema: dict[str, Any],
    *,
    omit_null: bool,
) -> list[str]:
    issues: list[str] = []
    if omit_null:
        for name, value in parameters.items():
            if value is None:
                issues.append(f"{name} must be omitted instead of null")
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(parameters), key=lambda item: list(item.path))
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path)
        prefix = f"{location}: " if location else ""
        issues.append(f"{prefix}{error.message}")
    return issues


def _snapshot_payloads(suite: SuiteDefinition) -> dict[str, dict[str, Any]]:
    ir = suite.capability_ir
    return {
        ir.intent.snapshot_id: {
            "contract_version": ir.intent.contract_version,
            "parameters_schema": ir.parameters_schema,
            "decision_rules": ir.decision_rules,
            "parameter_semantics": ir.parameter_semantics,
            "missing_parameters": ir.parameter_semantics.get(
                "missing_parameters", []
            ),
            "semantic_rules": ir.semantic_rules,
        }
    }


def _label_prefix(suite: SuiteDefinition, source: str, field: str | None = None):
    matches = [
        item.prefix
        for item in suite.compilation_config.labels
        if item.source == source and (field is None or item.field == field)
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f"multiple {source!r} label instructions configured")
    return matches[0]


def validate_module_intent_contract(
    cases: list[EvalCase], suite: SuiteDefinition, *, require_all_slots: bool = True
) -> list[str]:
    issues: list[str] = []
    config = suite.validation_config
    snapshots = _snapshot_payloads(suite)
    decision_protocol: dict[str, str] = {}
    if config.decision_protocol is not None:
        reference = config.decision_protocol
        try:
            raw_protocol = resolve_json_pointer(
                snapshots[reference.snapshot_id], reference.pointer
            )
            if "complete" in raw_protocol and "incomplete" in raw_protocol:
                decision_protocol = {
                    rule["status"]: rule["next_action"]
                    for rule in raw_protocol.values()
                    if isinstance(rule, dict)
                    and "status" in rule
                    and "next_action" in rule
                }
            else:
                decision_protocol = raw_protocol
        except KeyError as exc:
            raise ValueError(
                f"unknown decision protocol snapshot {reference.snapshot_id!r}"
            ) from exc

    slot_prefix = _label_prefix(suite, "slot", "slot_id")
    rule_prefix = _label_prefix(suite, "rule_refs")
    planned_by_label = (
        {
            f"{slot_prefix}{slot['slot_id']}": slot
            for slot in suite.coverage_plan["slots"]
        }
        if slot_prefix is not None
        else {}
    )
    observed_slots: Counter[str] = Counter()

    for case in cases:
        expected = case.oracle.expected_module_output or {}
        prefix = case.case_id
        intent = expected.get("intent")
        status = expected.get("status")
        action = expected.get("next_action")
        parameters = expected.get("parameters", {})
        missing = expected.get("missing_parameters", [])

        if intent in config.forbidden_intents:
            issues.append(f"{prefix}: forbidden intent {intent!r}")
        expected_action = decision_protocol.get(status)
        if expected_action is not None and action != expected_action:
            issues.append(f"{prefix}: status/next_action mismatch")

        if not isinstance(parameters, dict):
            issues.append(f"{prefix}: parameters must be an object")
            continue
        leaked = set(parameters) & set(config.execution_parameter_names)
        if leaked:
            issues.append(f"{prefix}: execution fields in parameters {sorted(leaked)}")

        capability_id = config.capability_by_intent.get(intent)
        if capability_id is not None:
            try:
                capability = snapshots[capability_id]
            except KeyError as exc:
                raise ValueError(
                    f"unknown capability snapshot {capability_id!r}"
                ) from exc
            schema = resolve_json_pointer(capability, config.parameters_schema_pointer)
            issues.extend(
                f"{prefix}: {issue}"
                for issue in validate_parameters(
                    parameters,
                    schema,
                    omit_null=config.omit_null_parameters,
                )
            )
            vocabulary = set(
                resolve_json_pointer(capability, config.missing_parameters_pointer)
            )
            unknown_missing = set(missing) - vocabulary
            if unknown_missing:
                issues.append(
                    f"{prefix}: unknown missing parameters {sorted(unknown_missing)}"
                )
        else:
            allowed = set(config.allowed_parameters_by_intent.get(intent, []))
            unknown = set(parameters) - allowed
            if unknown:
                issues.append(f"{prefix}: unknown parameters {sorted(unknown)}")

        rule = config.status_rules.get(status)
        if rule is None:
            issues.append(f"{prefix}: unsupported status {status!r}")
        else:
            present_count = sum(value is not None for value in parameters.values())
            if present_count < rule.minimum_parameter_count:
                issues.append(
                    f"{prefix}: status {status} requires at least "
                    f"{rule.minimum_parameter_count} parameters"
                )
            if rule.missing_parameters == "empty" and missing:
                issues.append(f"{prefix}: complete decision has missing parameters")
            if rule.missing_parameters == "non_empty" and not missing:
                issues.append(f"{prefix}: clarification needs missing_parameters")

        if planned_by_label:
            slot_labels = [
                label for label in case.labels if label.startswith(slot_prefix or "")
            ]
            if len(slot_labels) != 1:
                issues.append(f"{prefix}: exactly one slot label is required")
            for slot_label in slot_labels:
                slot = planned_by_label.get(slot_label)
                if slot is None:
                    issues.append(f"{prefix}: unknown slot label {slot_label}")
                    continue
                observed_slots[slot_label] += 1
                if (
                    config.require_slot_scenario_match
                    and case.scenario_type != slot.get("scenario_type")
                ):
                    issues.append(
                        f"{prefix}: scenario_type does not match coverage slot"
                    )
                if config.require_rule_refs_match:
                    expected_refs = slot.get("rule_refs", [])
                    observed_refs = [
                        label.removeprefix(rule_prefix or "")
                        for label in case.labels
                        if rule_prefix and label.startswith(rule_prefix)
                    ]
                    if observed_refs != expected_refs:
                        issues.append(f"{prefix}: rule_refs do not match coverage plan")

    duplicates = sorted(label for label, count in observed_slots.items() if count > 1)
    if duplicates:
        issues.append(f"duplicate slot labels {duplicates}")
    missing_slots = sorted(set(planned_by_label) - set(observed_slots))
    if require_all_slots and missing_slots:
        issues.append(f"missing slot labels {missing_slots}")
    return issues

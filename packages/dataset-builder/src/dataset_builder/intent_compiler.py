"""Configuration-driven compilation for module-intent evaluation cases."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from eval_framework.schemas import EvalCase
from pydantic import BaseModel

from .capability_ir import SupportStatus

if TYPE_CHECKING:
    from .suite_definition import SuiteDefinition


def _resolve_json_pointer(payload: Any, pointer: str) -> Any:
    value = payload
    for raw_part in pointer.lstrip("/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"JSON pointer {pointer!r} does not exist")
        value = value[part]
    return value


def _snapshot_payload(suite: SuiteDefinition, snapshot_id: str) -> dict:
    ir = suite.capability_ir
    if snapshot_id != ir.intent.snapshot_id:
        raise ValueError(f"snapshot {snapshot_id!r} is not exposed by Capability IR")
    return {
        "contract_version": ir.intent.contract_version,
        "parameters_schema": ir.parameters_schema,
        "decision_rules": ir.decision_rules,
        "parameter_semantics": ir.parameter_semantics,
        "missing_parameters": ir.parameter_semantics.get(
            "missing_parameters", []
        ),
        "semantic_rules": ir.semantic_rules,
    }


def render_case_labels(
    candidate: BaseModel,
    slot: dict[str, Any],
    suite: SuiteDefinition,
) -> list[str]:
    labels: list[str] = []
    for instruction in suite.compilation_config.labels:
        values: list[Any]
        if instruction.source == "literal":
            values = [instruction.value]
        elif instruction.source == "candidate":
            values = [getattr(candidate, instruction.field or "")]
        elif instruction.source == "slot":
            field = instruction.field or ""
            if field not in slot:
                raise ValueError(
                    f"slot {slot.get('slot_id')!r} has no field {field!r}"
                )
            values = [slot[field]]
        elif instruction.source == "rule_refs":
            values = list(getattr(candidate, "rule_refs", []))
        elif instruction.source == "coverage_tags":
            values = list(candidate.coverage_tags)
        elif instruction.source == "snapshot":
            payload = _snapshot_payload(suite, instruction.snapshot_id or "")
            values = [_resolve_json_pointer(payload, instruction.pointer or "")]
        else:  # pragma: no cover - SuiteConfig makes this unreachable.
            raise ValueError(f"unsupported label source {instruction.source!r}")
        for value in values:
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"label instruction {instruction.source!r} produced "
                    f"invalid value {value!r}"
                )
            labels.append(f"{instruction.prefix}{value}")
    return list(dict.fromkeys(labels))


def build_execution(
    candidate: BaseModel, suite: SuiteDefinition
) -> dict[str, Any]:
    config = suite.compilation_config
    defaults = config.execution
    return {
        "user_input": candidate.user_input,
        "user_responses": list(
            config.user_responses_by_intent.get(candidate.expected_intent, [])
        ),
        "tool_profile": defaults.tool_profile,
        "allowed_tools": defaults.allowed_tools,
        "fault_injection": defaults.fault_injection,
        "max_steps": defaults.max_steps,
        "timeout_seconds": defaults.timeout_seconds,
    }


def build_cleanup(
    candidate: BaseModel, suite: SuiteDefinition
) -> dict[str, Any] | None:
    configured = suite.compilation_config.cleanup_by_intent.get(
        candidate.expected_intent
    )
    return dict(configured) if configured is not None else None


def compile_intent_candidates(
    candidates: list[BaseModel], suite: SuiteDefinition, *, allow_partial: bool = False
) -> list[EvalCase]:
    if suite.capability_ir.support_status is not SupportStatus.SUPPORTED:
        raise ValueError(
            "cannot compile positive oracles from "
            f"{suite.capability_ir.support_status.value} Capability IR"
        )
    config = suite.compilation_config
    by_slot = {candidate.slot_id: candidate for candidate in candidates}
    output: list[EvalCase] = []
    for index, slot in enumerate(suite.coverage_plan["slots"], start=1):
        if allow_partial and slot["slot_id"] not in by_slot:
            continue
        candidate = by_slot[slot["slot_id"]]
        try:
            task_id = config.task_ids[candidate.expected_intent]
        except KeyError as exc:
            raise ValueError(
                f"no task_id configured for intent {candidate.expected_intent!r}"
            ) from exc
        scenario_type = config.scenario_type_map.get(
            candidate.scenario_type, candidate.scenario_type
        )
        value = {
            "schema_version": "1.0",
            "case_id": (
                f"{config.case_id_prefix}"
                f"{index:0{config.case_id_width}d}"
            ),
            "task_id": task_id,
            "scenario_type": scenario_type,
            "test_scope": suite.test_scope,
            "target": suite.target,
            "execution": build_execution(candidate, suite),
            "oracle": {
                "expected_module_output": {
                    "intent": candidate.expected_intent,
                    "status": candidate.expected_status,
                    "next_action": candidate.expected_next_action,
                    "parameters": json.loads(candidate.expected_parameters_json),
                    "missing_parameters": candidate.missing_parameters,
                    "reason": config.oracle_reason,
                },
                "expected_agent_status": None,
                "expected_tool_calls": [],
                "forbidden_tools": [],
                "goal_state": None,
                "process_constraints": {},
                "expected_response": None,
                "evaluation": {
                    "checks": [
                        item.model_dump(mode="json")
                        for item in config.assertions
                    ]
                },
            },
            "labels": render_case_labels(candidate, slot, suite),
            "cleanup": build_cleanup(candidate, suite),
        }
        output.append(EvalCase.model_validate(value))
    return output

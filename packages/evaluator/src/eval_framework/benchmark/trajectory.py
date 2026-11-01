"""DeepEval metrics over saved, independently captured execution evidence.

Structural tool validity is a diagnostic, not semantic argument correctness.
Private task checkpoints supply the latter without reaching the Agent. Missing
measurements remain unscored; final state never substitutes for a turn snapshot.
"""

from __future__ import annotations

from importlib.metadata import version
from typing import Any

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

TRAJECTORY_VERSION = "file-tools-trajectory-v1"


class TrajectoryMetric(BaseMetric):
    """Run a deterministic, evidence-backed result through DeepEval's API."""

    threshold = 1.0
    async_mode = False
    strict_mode = True
    include_reason = True
    verbose_mode = False
    evaluation_model = "deterministic-trajectory-checkpoint"

    def __init__(self, name: str) -> None:
        self.name = name

    @property
    def __name__(self) -> str:
        return self.name

    def measure(self, test_case: LLMTestCase, **_kwargs: Any) -> float:
        evidence = test_case.metadata or {}
        self.score = float(evidence["passed"])
        self.reason = evidence["reason"]
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case: LLMTestCase, **kwargs: Any) -> float:
        return self.measure(test_case, **kwargs)


def _record(
    name: str,
    passed: bool | None,
    reason: str,
    *,
    scope: str,
    event_id: str | None = None,
    formal: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    result = {
        "name": name,
        "backend": "deepeval",
        "version": TRAJECTORY_VERSION,
        "library_version": version("deepeval"),
        "implementation": "TrajectoryMetric",
        "formal": formal,
        "scope": scope,
        "event_id": event_id,
        "threshold": 1.0,
        "score": None,
        "success": None,
        "reason": reason,
        "status": "MISSING" if passed is None else "SCORED",
        **extra,
    }
    if passed is not None:
        metric = TrajectoryMetric(name)
        metric.measure(
            LLMTestCase(
                input=name,
                actual_output=reason,
                metadata={"passed": passed, "reason": reason},
            )
        )
        result.update(score=metric.score, success=metric.is_successful())
    return result


def _subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _subset(value, actual[key])
            for key, value in expected.items()
        )
    # Booleans are not numeric arguments, despite Python's True == 1.
    return type(expected) is type(actual) and expected == actual


def _valid_snapshot(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(path, str) and isinstance(content, str)
        for path, content in value.items()
    )


def _has_external_reference(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            (key == "$ref" and not str(item).startswith("#"))
            or _has_external_reference(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_has_external_reference(item) for item in value)
    return False


def _schema_result(event: dict[str, Any]) -> tuple[bool | None, str]:
    schema = event.get("tool_schema")
    if not isinstance(schema, dict) or _has_external_reference(schema):
        return None, "Recorded local tool parameter schema is unavailable"
    try:
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(event.get("input")))
    except SchemaError as exc:
        return None, f"Recorded tool schema is invalid: {exc.message}"
    if errors:
        return False, "; ".join(error.message for error in errors[:5])
    return True, "Arguments satisfy the recorded structural schema; semantics untested"


def score_trajectory(
    task: dict[str, Any], observation: dict[str, Any]
) -> list[dict[str, Any]]:
    """Score each tool attempt and explicitly declared private checkpoints.

    A complete trace with no required call is a measured failure. An incomplete
    trace with no such call is missing evidence. Checkpoint argument subsets and
    dependency pairs permit additional arguments/calls and legitimate retries.
    """
    events = observation.get("events")
    if not isinstance(events, list):
        events = []
    if any(
        not isinstance(event, dict)
        or not isinstance(event.get("id"), str)
        or not event["id"]
        for event in events
    ) or len({event["id"] for event in events}) != len(events):
        return [
            _record(
                "trajectory_evidence",
                None,
                "Recorded events lack unique, nonempty event identifiers",
                scope="task",
                formal=any(cp.get("required") for cp in task.get("checkpoints", [])),
            )
        ]
    turns = [event for event in events if event.get("type") == "turn"]
    turn_numbers = {
        event["id"]: event.get("turn", index + 1) for index, event in enumerate(turns)
    }
    tools = [event for event in events if event.get("type") == "tool"]
    complete = observation.get("evidence_complete") is True and not any(
        event.get("incomplete") for event in events
    )
    records: list[dict[str, Any]] = []
    for event in tools:
        allowed = event.get("name") in task.get("allowed_tools", [])
        records.append(
            _record(
                "tool_allowed",
                allowed,
                "Tool is allowed" if allowed else "Tool is outside the task allowlist",
                scope="tool",
                event_id=event["id"],
            )
        )
        passed, reason = _schema_result(event)
        records.append(
            _record(
                "tool_schema",
                passed,
                reason,
                scope="tool",
                event_id=event["id"],
                semantics="Structural validity only; not semantic argument correctness",
            )
        )

    for checkpoint in task.get("checkpoints", []):
        name = "checkpoint:" + checkpoint["id"]
        common = {
            "formal": checkpoint["required"],
            "checkpoint_id": checkpoint["id"],
            "checkpoint_kind": checkpoint["kind"],
        }
        target_turn = checkpoint.get("turn")
        selected = [
            event
            for event in tools
            if target_turn is None
            or event.get("turn", turn_numbers.get(event.get("parent_id")))
            == target_turn
        ]
        if checkpoint["kind"] == "turn_files":
            matching_turn = next(
                (event for event in turns if turn_numbers[event["id"]] == target_turn),
                None,
            )
            observed_turns = observation.get("turns") or []
            turn = (
                observed_turns[target_turn - 1]
                if 0 < target_turn <= len(observed_turns)
                else {}
            )
            snapshot = turn.get("snapshot")
            if snapshot is None and matching_turn is not None:
                snapshot = matching_turn.get("snapshot")
            event_id = matching_turn["id"] if matching_turn else None
            if not _valid_snapshot(snapshot) or event_id is None:
                records.append(
                    _record(
                        name,
                        None,
                        "Required turn snapshot or linked turn event is missing",
                        scope="turn" if event_id else "task",
                        event_id=event_id,
                        intended_scope="turn",
                        **common,
                    )
                )
                continue
            mismatches = [
                path
                for path, content in checkpoint["expected_files"].items()
                if snapshot.get(path) != content
            ]
            records.append(
                _record(
                    name,
                    not mismatches,
                    "Turn state matches expected files"
                    if not mismatches
                    else "Turn file mismatch: " + ", ".join(mismatches),
                    scope="turn",
                    event_id=event_id,
                    evidence_ids=[event_id],
                    **common,
                )
            )
        elif checkpoint["kind"] == "tool_args":
            attempts = [
                event for event in selected if event["name"] == checkpoint["tool"]
            ]
            matching = [
                event
                for event in attempts
                if event.get("execution_started") is not False
                and event.get("end_time")
                and not event.get("incomplete")
                and _subset(
                    checkpoint["arguments"],
                    event.get("normalized_input", event.get("input")),
                )
            ]
            anchor = matching[-1] if matching else attempts[-1] if attempts else None
            passed = True if matching else False if complete else None
            records.append(
                _record(
                    name,
                    passed,
                    "Observed argument subset matches checkpoint"
                    if matching
                    else "No executed call matches required arguments"
                    if complete
                    else "Incomplete trace cannot establish the required call",
                    scope="tool" if anchor else "task",
                    event_id=anchor["id"] if anchor else None,
                    intended_scope="tool",
                    evidence_ids=[event["id"] for event in attempts],
                    **common,
                )
            )
        elif checkpoint["kind"] == "tool_order":
            executed = [
                event
                for event in selected
                if event.get("execution_started") is not False
                and event.get("end_time")
                and not event.get("incomplete")
            ]
            pair = next(
                (
                    (before, after)
                    for index, before in enumerate(executed)
                    if before["name"] == checkpoint["before"]
                    for after in executed[index + 1 :]
                    if after["name"] == checkpoint["after"]
                ),
                None,
            )
            passed = True if pair else False if complete else None
            records.append(
                _record(
                    name,
                    passed,
                    "Required tool execution order observed"
                    if pair
                    else "Required tool execution order absent"
                    if complete
                    else "Incomplete trace cannot establish the required order",
                    scope="chain" if pair else "task",
                    event_id=pair[1]["id"] if pair else None,
                    intended_scope="chain",
                    semantics="Recorded call order; not semantic data provenance",
                    evidence_ids=[event["id"] for event in pair] if pair else [],
                    **common,
                )
            )
        else:
            raise ValueError(f"unsupported checkpoint kind: {checkpoint['kind']}")
    return records

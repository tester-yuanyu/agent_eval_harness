"""Private DeepEval assertions against complete, independently captured evidence."""

from __future__ import annotations

import json
import math
from typing import Any

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from .core_tasks import safe_relative_path, validate_core_task

SCORING_VERSION = "nanobot-core-deepeval-v1"
_MISSING = object()


def _at(value: Any, path: list) -> Any:
    for part in path:
        if isinstance(value, dict) and isinstance(part, str) and part in value:
            value = value[part]
        elif isinstance(value, list) and type(part) is int and 0 <= part < len(value):
            value = value[part]
        else:
            return _MISSING
    return value


def _equal(actual: Any, expected: Any) -> bool:
    return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(
        expected, sort_keys=True, allow_nan=False
    )


def _subset(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            k in actual and _subset(actual[k], v) for k, v in expected.items()
        )
    return _equal(actual, expected)


def _matches(actual: Any, kind: str, expected: Any) -> bool:
    if actual is _MISSING:
        return False
    if kind == "any_file_contains":
        return isinstance(actual, dict) and any(
            isinstance(v, str) and expected in v for v in actual.values()
        )
    if kind == "equals":
        return _equal(actual, expected)
    if kind == "subset":
        return _subset(actual, expected)
    if kind == "length":
        return isinstance(actual, (dict, list, str)) and len(actual) == expected
    if kind in ("contains", "not_contains"):
        if isinstance(actual, str) and isinstance(expected, str):
            found = expected in actual
        elif isinstance(actual, list):
            found = any(_equal(item, expected) for item in actual)
        else:
            return False
        return found if kind == "contains" else not found
    return False


class CoreAssertionsMetric(BaseMetric):
    threshold = 1.0
    async_mode = False
    strict_mode = True
    include_reason = True
    verbose_mode = False
    evaluation_model = "deterministic-core-oracle"

    @property
    def __name__(self) -> str:
        return "core_assertions"

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        metadata = test_case.metadata or {}
        task, observation = metadata["task"], metadata["observation"]
        events = {event["id"]: event for event in observation["events"]}
        failures = []
        expected_errors = {
            a["event"]
            for a in task["oracle"]["assertions"]
            if "event" in a and a["path"] == ["error", "type"] and a["kind"] == "equals"
        }
        for identifier, event in events.items():
            if event["error"] is not None and identifier not in expected_errors:
                failures.append(
                    f"{identifier}: unexpected exception {event['error']['type']}"
                )
        self.checks = []
        for index, assertion in enumerate(task["oracle"]["assertions"]):
            root = (
                events[assertion["event"]]
                if "event" in assertion
                else observation[assertion["scope"]]
            )
            if (
                assertion["kind"] == "any_file_contains"
                and assertion.get("scope") == "session_files"
            ):
                # Requests/configuration/logs are not persistence evidence.
                root = {
                    path: text
                    for path, text in root.items()
                    if path.startswith("sessions/") and path.endswith(".jsonl")
                }
            passed = _matches(
                _at(root, assertion["path"]), assertion["kind"], assertion["value"]
            )
            self.checks.append({"index": index, "passed": passed})
            if not passed:
                failures.append(
                    f"assertion {index}: "
                    f"{assertion.get('event', assertion.get('scope'))} "
                    f"{assertion['path']} {assertion['kind']} failed"
                )
        self.score = float(not failures)
        self.success = not failures
        self.reason = (
            "; ".join(failures) or "All independent component assertions passed"
        )
        return self.score

    async def a_measure(
        self, test_case: LLMTestCase, *args: Any, **kwargs: Any
    ) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)


def _evidence_problem(task: dict, observation: dict) -> str | None:
    if observation.get("execution_kind") != "real_core_module":
        return "Missing real core execution marker"
    if (
        observation.get("status") != "completed"
        or observation.get("evidence_complete") is not True
    ):
        return "Execution or independent evidence incomplete"
    if observation.get("errors") != []:
        return "Missing clean execution errors list"
    if (
        not isinstance(observation.get("runtime_identity"), dict)
        or not observation["runtime_identity"]
    ):
        return "Runtime identity missing"
    if observation.get("usage") != {}:
        return "Core execution must not report model usage"
    for key in ("before_files", "final_files", "session_files"):
        files = observation.get(key)
        if not isinstance(files, dict) or any(
            not safe_relative_path(p) or not isinstance(v, str)
            for p, v in files.items()
        ):
            return f"{key} snapshot absent or malformed"
    if observation["before_files"] != task["fixtures"]:
        return "Initial snapshot differs from frozen fixtures"
    events = observation.get("events")
    if not isinstance(events, list) or len(events) != len(task["operations"]):
        return "Operation event count mismatch"
    last_end = -math.inf
    for expected, event in zip(task["operations"], events, strict=True):
        if (
            not isinstance(event, dict)
            or not {
                "id",
                "type",
                "operation",
                "input",
                "output",
                "error",
                "start_time",
                "end_time",
                "incomplete",
            }
            <= event.keys()
        ):
            return "Operation event fields missing"
        if event["type"] != "module" or event["incomplete"] is not False:
            return "Incomplete or wrong event type"
        if any(
            not _equal(event[key], expected[key])
            for key in ("id", "operation", "input")
        ):
            return "Event does not bind to requested operation"
        start, end = event["start_time"], event["end_time"]
        if (
            any(
                type(t) not in (int, float) or not math.isfinite(t)
                for t in (start, end)
            )
            or end < start
            or start < last_end
        ):
            return "Invalid event time ordering"
        last_end = end
        error = event["error"]
        if error is not None and (
            not isinstance(error, dict)
            or set(error) != {"type", "message"}
            or not all(isinstance(v, str) for v in error.values())
            or event["output"] is not None
        ):
            return "Malformed exception evidence"
    return None


def score_core_task(task: dict, observation: dict) -> dict:
    result = {
        "validity": "VALID",
        "verdict": "FAIL",
        "metrics": [],
        "diagnostics": [],
        "scoring_version": SCORING_VERSION,
    }
    try:
        validate_core_task(task)
        json.dumps(observation, allow_nan=False)
        if not isinstance(observation, dict):
            raise ValueError("Observation must be an object")
    except (ValueError, TypeError) as exc:
        result.update(validity="INVALID", verdict="INVALID", diagnostics=[str(exc)])
        return result
    if observation.get("status") == "error" or observation.get("errors"):
        result.update(
            validity="INVALID",
            verdict="INVALID",
            diagnostics=["Fatal worker/runtime error"],
        )
        return result
    problem = _evidence_problem(task, observation)
    if problem:
        result.update(
            validity="INCONCLUSIVE", verdict="INCONCLUSIVE", diagnostics=[problem]
        )
        return result
    metric = CoreAssertionsMetric()
    metric.measure(
        LLMTestCase(
            input="Offline component execution",
            actual_output="Recorded evidence",
            metadata={"task": task, "observation": observation},
        )
    )
    result["metrics"] = [
        {
            "name": metric.__name__,
            "score": metric.score,
            "threshold": metric.threshold,
            "success": metric.success,
            "reason": metric.reason,
            "formal": True,
            "checks": metric.checks,
        }
    ]
    result["verdict"] = "PASS" if metric.success else "FAIL"
    return result

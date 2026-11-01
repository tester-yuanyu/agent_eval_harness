"""Grader v2.1 policy for the frozen file-tools-v2 missing-primary family.

This changes grading only, never frozen tasks or their execution inputs. The
published prompt explicitly requires a missing-primary error, then a successful
fallback read, then writing recovered.txt. Its original argument checkpoints
only established presence. This named domain policy closes that gap without
inferring dependencies for unrelated tasks or grading private model reasoning.
The two read selectors come from the existing private checkpoint declarations.
Final contents remain the responsibility of the independent file-state oracle.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

REVIEW_RECOVERY_VERSION = "file-tools-recovery-policy-v2.1"


def _times(event: dict[str, Any]) -> tuple[datetime, datetime] | None:
    try:
        start = datetime.fromisoformat(event["start_time"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(event["end_time"].replace("Z", "+00:00"))
        if start.tzinfo is None or end.tzinfo is None or end < start:
            return None
        return start, end
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def _error(event: dict[str, Any]) -> bool | None:
    flags = [event[key] for key in ("is_error", "tool_error") if key in event]
    if not flags or any(type(flag) is not bool for flag in flags):
        return None
    if len(set(flags)) != 1:
        return None
    return flags[0] or bool(event.get("error"))


def score_recovery_policy(
    task: dict[str, Any], observation: dict[str, Any]
) -> list[dict[str, Any]]:
    """Score the declared recovery dependency from complete recorded tool results.

    Calls may be separated by other tools and failed attempts may be retried.
    Both journal order and completed-result timestamps must establish dependency
    order. Incomplete evidence is unscored, never a successful inferred recovery.
    """
    if (
        task.get("family") != "chain/recover_missing"
        or not str(task.get("id", "")).startswith(
            "file-tools-v2/chain/recover_missing/"
        )
        or task.get("evaluation_level") != "chain"
        or task.get("execution_mode") != "agent"
    ):
        return []

    # Import lazily so trajectory can call this policy without an import cycle.
    from .trajectory import _record, _subset

    events = observation.get("events")
    events = events if isinstance(events, list) else []
    valid_ids = all(
        isinstance(event, dict)
        and isinstance(event.get("id"), str)
        and bool(event["id"])
        for event in events
    )
    valid_ids = valid_ids and len({event["id"] for event in events}) == len(events)
    tools = (
        [event for event in events if event.get("type") == "tool"] if valid_ids else []
    )
    destinations = [
        event
        for event in tools
        if event.get("name") in {"write_file", "edit_file"}
        and isinstance(event.get("normalized_input", event.get("input")), dict)
        and event.get("normalized_input", event.get("input")).get("path")
        == "recovered.txt"
    ]

    def result(passed, reason, evidence=()):
        anchor = (
            evidence[-1]
            if evidence
            else destinations[-1]
            if destinations
            else tools[-1]
            if tools
            else None
        )
        return [
            _record(
                "checkpoint:missing-primary-recovery",
                passed,
                reason,
                scope="chain" if anchor else "task",
                event_id=anchor["id"] if anchor else None,
                intended_scope="chain",
                formal=True,
                version=REVIEW_RECOVERY_VERSION,
                checkpoint_id="missing-primary-recovery",
                checkpoint_kind="published_family_recovery_policy",
                evidence_ids=[event["id"] for event in evidence],
                semantics=(
                    "Observed missing-primary error before successful fallback read "
                    "and destination write"
                ),
            )
        ]

    if (
        not events
        or not valid_ids
        or observation.get("evidence_complete") is not True
        or any(event.get("incomplete") for event in events)
    ):
        return result(
            None, "Complete execution evidence with unique event IDs is required"
        )

    points = task.get("checkpoints", [])
    selectors = []
    for identifier in ("attempt-primary", "use-fallback"):
        selected = [point for point in points if point.get("id") == identifier]
        if (
            len(selected) != 1
            or selected[0].get("kind") != "tool_args"
            or selected[0].get("tool") != "read_file"
            or selected[0].get("required") is not True
            or not isinstance(selected[0].get("arguments"), dict)
            or not isinstance(selected[0]["arguments"].get("path"), str)
        ):
            return result(
                None, f"Required private selector {identifier} is unavailable"
            )
        selectors.append(selected[0])

    timings = {}
    for event in tools:
        timing = _times(event)
        if (
            timing is None
            or not isinstance(event.get("output"), str)
            or not isinstance(event.get("normalized_input", event.get("input")), dict)
            or type(event.get("execution_started")) is not bool
            or _error(event) is None
        ):
            return result(None, "Tool execution/result/timing evidence is incomplete")
        timings[event["id"]] = timing

    def matches(event, selector):
        return (
            event.get("name") == selector["tool"]
            and event["execution_started"]
            and ("turn" not in selector or event.get("turn") == selector["turn"])
            and _subset(
                selector["arguments"], event.get("normalized_input", event.get("input"))
            )
        )

    primary, fallback = selectors
    for primary_index, first in enumerate(tools):
        if not (
            matches(first, primary)
            and _error(first)
            and "file not found" in first["output"].casefold()
        ):
            continue
        for fallback_index in range(primary_index + 1, len(tools)):
            second = tools[fallback_index]
            if not (
                matches(second, fallback)
                and _error(second) is False
                and timings[first["id"]][1] <= timings[second["id"]][0]
            ):
                continue
            for third in tools[fallback_index + 1 :]:
                arguments = third.get("normalized_input", third.get("input"))
                if (
                    third.get("name") in {"write_file", "edit_file"}
                    and arguments.get("path") == "recovered.txt"
                    and third["execution_started"]
                    and _error(third) is False
                    and timings[second["id"]][1] <= timings[third["id"]][0]
                ):
                    return result(
                        True,
                        "Observed missing-primary error, successful fallback read, "
                        "and successful destination write in dependency order",
                        (first, second, third),
                    )
    return result(
        False,
        "No observed missing-primary error followed by successful fallback read "
        "and destination write in dependency order",
    )

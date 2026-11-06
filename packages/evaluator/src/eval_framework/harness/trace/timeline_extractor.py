"""Inspect timeline to shared Trace and the existing Scorer observation envelope."""

from __future__ import annotations

from typing import Any

from eval_contracts.trace import StepTrace, TaskTrace, TurnTrace
from inspect_ai.event import InfoEvent, ModelEvent, ToolEvent

from ..tracer import aggregate_usage, model_evidence


def business_events(events: list[Any]) -> list[InfoEvent]:
    return [e for e in events if isinstance(e, InfoEvent) and e.source == "harness.v1"]


async def extract_timeline(task_id: str, events: list[Any]) -> dict[str, Any]:
    info = business_events(events)
    starts = [e for e in info if e.data["kind"] == "turn_start"]
    ends = {e.data["turn"]: e for e in info if e.data["kind"] == "turn_end"}
    route_starts = [e for e in info if e.data["kind"] == "route_start"]
    route_ends = {
        e.data["route_id"]: e.data for e in info if e.data["kind"] == "route_end"
    }
    stop = next(
        (e.data["reason"] for e in reversed(info) if e.data["kind"] == "stop"),
        "incomplete",
    )
    before = next(
        (e.data["snapshot"] for e in info if e.data["kind"] == "initial_state"), None
    )
    final = next(
        (e.data["snapshot"] for e in reversed(info) if e.data["kind"] == "final_state"),
        None,
    )
    turn_events = [
        {
            "id": e.uuid,
            "type": "turn",
            "name": f"turn-{e.data['turn']}",
            "turn": e.data["turn"],
            "input": e.data["input"],
            "output": ends[e.data["turn"]].data["output"]
            if e.data["turn"] in ends
            else None,
            "start_time": e.timestamp.isoformat(),
            "end_time": ends[e.data["turn"]].timestamp.isoformat()
            if e.data["turn"] in ends
            else None,
            "source": "inspect_ai.InfoEvent",
        }
        for e in starts
    ]
    generations = await model_evidence(events, turn_events)
    tools = []
    for event in events:
        if not isinstance(event, ToolEvent):
            continue
        start = next(
            (
                e.data
                for e in reversed(route_starts)
                if e.data["call_id"] == event.id and e.timestamp <= event.timestamp
            ),
            {},
        )
        end = route_ends.get(start.get("route_id"), {})
        turn = next((t for t in turn_events if t["turn"] == start.get("turn")), {})
        tools.append(
            {
                "id": event.uuid,
                "type": "tool",
                "name": event.function,
                "native_event_id": event.uuid,
                "tool_call_id": event.id,
                "source": "inspect_ai.ToolEvent",
                "parent_id": turn.get("id"),
                "turn": start.get("turn"),
                "input": event.arguments,
                "normalized_input": event.arguments,
                "output": event.result,
                "error": event.error.message if event.error else None,
                "tool_error": event.error is not None,
                "is_error": event.error is not None,
                "validation_code": start.get("validation_code"),
                "tool_schema": start.get("schema"),
                "before_files": start.get("before"),
                "after_files": end.get("after"),
                "execution_started": end.get("execution_started", False),
                "start_time": event.timestamp.isoformat(),
                "end_time": event.completed.isoformat() if event.completed else None,
                "incomplete": event.pending is True
                or event.completed is None
                or not end,
            }
        )
    trace_turns = [
        TurnTrace(
            id=e.uuid,
            index=e.data["turn"],
            input=e.data["input"],
            output=ends[e.data["turn"]].data["output"]
            if e.data["turn"] in ends
            else None,
            snapshot=ends[e.data["turn"]].data["snapshot"]
            if e.data["turn"] in ends
            else None,
            steps=[
                StepTrace(
                    id=s["id"],
                    kind=s["type"],
                    native_event_id=s["native_event_id"],
                    data=s,
                )
                for s in sorted(generations + tools, key=lambda s: s["start_time"])
                if s.get("turn") == e.data["turn"]
            ],
        )
        for e in starts
    ]
    errors = [
        {
            "kind": e.data["kind_of_error"],
            "code": e.data["code"],
            "message": e.data["message"],
        }
        for e in info
        if e.data["kind"] == "execution_error"
    ]
    if stop != "completed" and not errors:
        errors.append({"kind": "agent", "code": stop, "message": stop})
    stop_data = next((e.data for e in reversed(info) if e.data["kind"] == "stop"), {})
    # In this native model path every step must have an authoritative ModelEvent.
    # Count declarations prevent deleted model/tool groups from looking complete.
    expected_steps = stop_data.get("steps")
    expected_tools = stop_data.get("tool_calls")
    complete = (
        stop == "completed"
        and not errors
        and before is not None
        and final is not None
        and bool(trace_turns)
        and all(t.output is not None and t.snapshot is not None for t in trace_turns)
        and not any(e.get("incomplete") for e in generations + tools)
        and type(expected_steps) is int
        and expected_steps > 0
        and len(generations) == expected_steps
        and all(any(s.kind == "generation" for s in t.steps) for t in trace_turns)
        and sum(len(t.steps) for t in trace_turns) == len(generations) + len(tools)
        and type(expected_tools) is int
        and len(tools) == len(route_starts) == len(route_ends) == expected_tools
    )
    trace = TaskTrace(
        task_id=task_id,
        status="completed" if stop == "completed" else "error",
        stop_reason=stop,
        before_state=before,
        final_state=final,
        turns=trace_turns,
        evidence_complete=complete,
    )
    return {
        "status": trace.status,
        "stop_reason": stop,
        "errors": errors,
        "before_files": before,
        "final_files": final,
        "turns": [
            {"input": t.input, "output": t.output, "snapshot": t.snapshot}
            for t in trace_turns
            if t.output is not None
        ],
        "events": sorted(
            turn_events + generations + tools, key=lambda e: e["start_time"]
        ),
        "usage": aggregate_usage(generations),
        "evidence_complete": complete,
        "trace": trace.model_dump(mode="json"),
        "native_events": {
            "model": sum(isinstance(e, ModelEvent) for e in events),
            "tool": len(tools),
        },
    }

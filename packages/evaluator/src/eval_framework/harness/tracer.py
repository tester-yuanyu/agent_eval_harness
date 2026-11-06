"""Compatibility evidence projections over Inspect and independent file events."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any


def apply_native_limits(observation: dict, events: Sequence[Any]) -> None:
    """Finalize cancellation provenance after Inspect publishes its limit event."""
    from inspect_ai.event import SampleLimitEvent

    for event in events:
        if isinstance(event, SampleLimitEvent) and event.type in {
            "token",
            "message",
            "time",
        }:
            observation["status"] = "timeout" if event.type == "time" else "error"
            observation["stop_reason"] = f"{event.type}_limit"
            observation["evidence_complete"] = False
            errors = observation.setdefault("errors", [])
            errors[:] = [
                error for error in errors if error.get("code") != "CancelledError"
            ]
            errors.append(
                {
                    "kind": "agent",
                    "code": observation["stop_reason"],
                    "message": event.message,
                    "native_event_id": event.uuid,
                }
            )


async def model_evidence(events: Sequence[Any], file_events: list[dict]) -> list[dict]:
    """Compatibility projection of native ModelEvent, not a second model logger."""
    from inspect_ai.event import ModelEvent
    from inspect_ai.model import messages_to_openai

    turns = [item for item in file_events if item.get("type") == "turn"]
    result = []
    for event in events:
        if not isinstance(event, ModelEvent):
            continue
        started = event.timestamp.isoformat()
        turn = next(
            (item for item in reversed(turns) if item["start_time"] <= started), {}
        )
        output = event.output
        message = output.message if output and output.choices else None
        usage = output.usage if output else None
        result.append(
            {
                "id": event.uuid,
                "type": "generation",
                "name": event.model,
                "model": event.model,
                "response_model": output.model if output else None,
                "source": "inspect_ai.ModelEvent",
                "native_event_id": event.uuid,
                "start_time": started,
                "end_time": event.completed.isoformat() if event.completed else None,
                "parent_id": turn.get("id"),
                "turn": turn.get("turn"),
                "input": {
                    "messages": [
                        {
                            key: value
                            for key, value in message.items()
                            if key
                            in {"role", "content", "tool_calls", "tool_call_id", "name"}
                        }
                        for message in await messages_to_openai(event.input)
                    ],
                    "tools": [
                        {
                            "type": "function",
                            "function": tool.model_dump(mode="json", exclude_none=True),
                        }
                        for tool in event.tools
                    ],
                    "model": event.model,
                },
                "output": {
                    "content": message.text if message else None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "name": call.function,
                            "arguments": call.arguments,
                        }
                        for call in (message.tool_calls or [])
                    ]
                    if message
                    else [],
                    "finish_reason": output.stop_reason if output else None,
                },
                "usage": {
                    "prompt_tokens": usage.input_tokens,
                    "completion_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens,
                }
                if usage
                else {},
                "error": event.error,
                "incomplete": event.pending is True or event.completed is None,
            }
        )
    return result


def aggregate_usage(generations: list[dict]) -> dict:
    if not generations:
        return {}
    return {
        key: sum(item["usage"][key] for item in generations)
        if all(isinstance(item["usage"].get(key), (int, float)) for item in generations)
        else None
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }


def evidence_is_complete(result: dict, task: dict, mode: str) -> bool:
    if result["status"] != "completed" or not isinstance(result["final_files"], dict):
        return False
    events = result["events"]
    if any(event.get("incomplete") for event in events):
        return False
    turns = [event for event in events if event["type"] == "turn"]
    tools = [event for event in events if event["type"] == "tool"]
    if len(turns) != len(result["turns"]) or not turns:
        return False
    if any(not isinstance(turn.get("snapshot"), dict) for turn in result["turns"]):
        return False
    for event in tools:
        if not isinstance(event.get("after_files"), dict):
            return False
        if event.get("execution_started", True) and not isinstance(
            event.get("before_files"), dict
        ):
            return False
    if mode == "module" and len(tools) != len(task["module_calls"]):
        return False
    if (
        mode == "decision"
        and sum(event["type"] == "generation" for event in events) != 1
    ):
        return False
    return True


def read_file_events(raw: str) -> list[dict]:
    """Retain the latest persisted version of each event, including partials."""
    entries = {}
    for line in raw.splitlines():
        try:
            event = json.loads(line)
            if not isinstance(event, dict) or not isinstance(event.get("id"), str):
                continue
            entries[event["id"]] = event
        except ValueError:
            continue
    result = list(entries.values())
    for event in result:
        event["source"] = "nanobot.file_evidence"
        if event.get("end_time") is None:
            event["incomplete"] = True
    return result

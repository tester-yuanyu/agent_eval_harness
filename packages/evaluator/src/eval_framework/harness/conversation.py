"""Minimal framework conversation loop for synchronous external Agent callbacks.

Existing target Agent loops remain in their independent workers. This loop owns
only public messages, tool dispatch and environment lifetime, never scoring.
"""

from __future__ import annotations

import errno
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .router import InvalidToolCall, ToolRouter


def _tool_failure_kind(error: Exception) -> str:
    if isinstance(error, InvalidToolCall):
        return "agent"
    if isinstance(error, OSError):
        if error.errno in {
            errno.ENOENT,
            errno.ENOTDIR,
            errno.EISDIR,
            errno.EEXIST,
            errno.ENAMETOOLONG,
            errno.ELOOP,
        }:
            return "agent"
        # Storage exhaustion, I/O failures, read-only mounts and other OS
        # failures are infrastructure faults, not evidence of Agent failure.
        return "environment"
    return "harness"


def _error_record(error: Exception, kind: str) -> dict[str, Any]:
    record = {"kind": kind, "code": type(error).__name__, "message": str(error)}
    if isinstance(error, OSError) and error.errno is not None:
        record["errno"] = error.errno
    return record


def run_conversation(
    agent: Any,
    *,
    environment: Any,
    initial_state: dict[str, str],
    simulator: Any,
    router: ToolRouter | None = None,
    max_steps: int = 40,
) -> dict[str, Any]:
    """Run public messages with a bounded number of Agent callback invocations.

    ``max_steps`` counts callback invocations, including those returning tool
    calls. Tools finish before another callback or fixed followup is supplied.
    The caller supplies a bare file map, never the private task specification.
    """
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError("max_steps must be a positive integer")
    router = router or ToolRouter(environment)
    history, events, turns = [], [], []
    result = {
        "status": "completed",
        "events": events,
        "turns": turns,
        "usage": {},
        "errors": [],
        "before_files": None,
        "final_files": None,
        "execution_kind": "framework_conversation",
        "evidence_complete": False,
    }
    steps = 0
    phase = "environment"

    def snapshot(*, final: bool = False) -> dict:
        nonlocal phase
        previous = phase
        phase = "environment"
        measured = environment.final_state() if final else environment.snapshot()
        phase = previous
        return measured

    try:
        environment.reset(initial_state)
        result["before_files"] = snapshot()
        while True:
            phase = "harness"
            if simulator.should_terminate(history):
                break
            message = simulator.next_message(history)
            if (
                not isinstance(message, dict)
                or message.get("role") != "user"
                or not isinstance(message.get("content"), str)
            ):
                raise ValueError("UserSimulator must supply a public user message")
            history.append(deepcopy(message))
            turn = {
                "id": uuid4().hex,
                "type": "turn",
                "input": message["content"],
                "start_time": datetime.now(UTC).isoformat(),
            }
            events.append(turn)
            while True:
                if steps >= max_steps:
                    result.update(
                        status="error", stop_reason="max_steps", evidence_complete=False
                    )
                    result["errors"].append(
                        {
                            "kind": "agent",
                            "code": "max_steps",
                            "message": "Agent callback invocation limit exceeded",
                        }
                    )
                    return {**result, "final_files": snapshot(final=True)}
                steps += 1
                phase = "agent"
                response = agent(deepcopy(history))
                if not isinstance(response, dict) or not isinstance(
                    response.get("content", ""), str
                ):
                    raise ValueError(
                        "Agent callback must return a public response mapping"
                    )
                calls = response.get("tool_calls", [])
                if not isinstance(calls, list):
                    raise ValueError("tool_calls must be a list")
                history.append(
                    {
                        "role": "assistant",
                        "content": response.get("content", ""),
                        "tool_calls": deepcopy(calls),
                    }
                )
                for call in calls:
                    phase = "harness"
                    try:
                        action = router.parse(call)
                    except InvalidToolCall:
                        phase = "agent"
                        raise
                    event = {
                        "id": uuid4().hex,
                        "type": "tool",
                        "name": action["name"],
                        "input": deepcopy(action["arguments"]),
                        "parent_id": turn["id"],
                        "start_time": datetime.now(UTC).isoformat(),
                        "end_time": None,
                        "incomplete": True,
                        "execution_started": True,
                        "before_files": snapshot(),
                    }
                    events.append(event)
                    try:
                        output = router.dispatch(action, environment)
                        event["output"] = deepcopy(output)
                        event["after_files"] = snapshot()
                    except Exception as exc:
                        kind = (
                            "environment"
                            if phase == "environment"
                            else _tool_failure_kind(exc)
                        )
                        event.update(
                            error=_error_record(exc, kind),
                            incomplete=True,
                            end_time=datetime.now(UTC).isoformat(),
                        )
                        try:
                            event["after_files"] = snapshot()
                        except Exception as snapshot_error:
                            event["after_snapshot_errors"] = [
                                _error_record(snapshot_error, "evidence")
                            ]
                        phase = kind
                        raise
                    event.update(
                        end_time=datetime.now(UTC).isoformat(), incomplete=False
                    )
                    history.append(
                        {
                            "role": "tool",
                            "name": action["name"],
                            "content": deepcopy(output),
                        }
                    )
                if not calls:
                    turn_files = snapshot()
                    turn.update(
                        output=response.get("content", ""),
                        snapshot=turn_files,
                        end_time=datetime.now(UTC).isoformat(),
                    )
                    turns.append(
                        {
                            "input": message["content"],
                            "output": response.get("content", ""),
                            "snapshot": turn_files,
                        }
                    )
                    break
        return {
            **result,
            "final_files": snapshot(final=True),
            "evidence_complete": True,
        }
    except Exception as exc:
        result.update(
            status="timeout" if isinstance(exc, TimeoutError) else "error",
            stop_reason=type(exc).__name__,
            evidence_complete=False,
        )
        result["errors"].append(_error_record(exc, phase))
        if result["before_files"] is not None:
            try:
                result["final_files"] = snapshot(final=True)
            except Exception as snapshot_error:
                result["errors"].append(
                    {
                        "kind": "evidence",
                        "code": "snapshot_failed",
                        "message": str(snapshot_error),
                    }
                )
        return result
    finally:
        environment.teardown()

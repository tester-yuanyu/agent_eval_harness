"""Execute isolated real nanobot ToolRegistry boundaries without a model provider."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .nanobot_runtime import EXECUTION_KEYS, FILE_TOOLS, runtime_identity


def module_execution_projection(task: dict[str, Any]) -> dict[str, Any]:
    unexpected = set(task) - EXECUTION_KEYS - {"module_calls"}
    if unexpected:
        raise ValueError(f"non-execution module fields: {sorted(unexpected)}")
    calls = task.get("module_calls")
    allowed = task.get("allowed_tools", list(FILE_TOOLS))
    if not isinstance(allowed, list) or not allowed or not set(allowed) <= FILE_TOOLS:
        raise ValueError("module execution permits only filesystem tools")
    if not isinstance(calls, list) or not calls or len(calls) > 40:
        raise ValueError("module execution requires 1 to 40 calls")
    for call in calls:
        if (
            not isinstance(call, dict)
            or set(call) != {"name", "arguments"}
            or call["name"] not in allowed
            or not isinstance(call["arguments"], dict)
        ):
            raise ValueError(
                "module calls require supported names and argument objects"
            )
    if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
        raise ValueError("module prompt must be nonempty")
    if task.get("followups"):
        raise ValueError("module execution is a single fixed request")
    return json.loads(json.dumps(task, ensure_ascii=False))


def module_identity(config: dict[str, Any]) -> dict[str, Any]:
    identity = runtime_identity({"sandbox": "local", **config, "model": None})
    identity.update(
        adapter_version="nanobot-module-v1", model=None, execution_kind="real_module"
    )
    return identity


async def execute_module_task(
    task: dict[str, Any], *, config: dict[str, Any], workspace: Path | None = None
) -> dict[str, Any]:
    from .inspect_runtime import execute_boundary

    return await execute_boundary(
        module_execution_projection(task),
        config=config,
        workspace=workspace,
        mode="module",
        identity=module_identity(config),
    )

"""Isolated single-model decision adapter; generated tool calls are never executed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .nanobot_runtime import EXECUTION_KEYS, FILE_TOOLS, runtime_identity


def decision_execution_projection(task: dict[str, Any]) -> dict[str, Any]:
    unexpected = set(task) - EXECUTION_KEYS - {"decision_context"}
    if unexpected:
        raise ValueError(f"non-execution decision fields: {sorted(unexpected)}")
    allowed = task.get("allowed_tools", list(FILE_TOOLS))
    if (
        not isinstance(allowed, list)
        or not allowed
        or any(name not in FILE_TOOLS for name in allowed)
    ):
        raise ValueError("decision execution permits only filesystem tool schemas")
    if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
        raise ValueError("decision prompt must be nonempty text")
    if not isinstance(task.get("decision_context", ""), str) or task.get("followups"):
        raise ValueError("decision execution requires public text context and one turn")
    return json.loads(json.dumps(task, ensure_ascii=False))


def decision_identity(config: dict[str, Any]) -> dict[str, Any]:
    identity = runtime_identity(config)
    identity.update(
        adapter_version="nanobot-decision-v1",
        execution_kind="real_model_decision",
        decision_boundary="one-provider-chat-call; no AgentLoop or tool execution",
        decision_system_version="next-action-v1",
    )
    return identity


async def execute_decision_task(
    task: dict[str, Any], *, config: dict[str, Any], workspace: Path | None = None
) -> dict[str, Any]:
    from .inspect_runtime import execute_boundary

    return await execute_boundary(
        decision_execution_projection(task),
        config=config,
        workspace=workspace,
        mode="decision",
        identity=decision_identity(config),
    )

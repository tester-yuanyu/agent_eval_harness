"""Compatibility views of frozen file tasks using the shared TaskSpec."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from eval_contracts.benchmark import TaskInput, TaskSpec

__all__ = ["TaskInput", "TaskSpec", "task_spec_from_legacy", "legacy_execution_input"]


def task_spec_from_legacy(task: dict[str, Any]) -> TaskSpec:
    """Convert an already validated task without rewriting its source bytes."""
    from .tasks import TOOLS

    parameters = {}
    if task.get("execution_mode") == "module":
        parameters["module_calls"] = task["module_calls"]
    if task.get("execution_mode") == "decision":
        parameters["decision_context"] = task["decision_context"]
    return TaskSpec(
        task_id=task["id"],
        prompt=task["prompt"],
        initial_state=deepcopy({"files": task["fixtures"]}),
        tools=list(task.get("allowed_tools", TOOLS)),
        followups=list(task["followups"]),
        max_steps=task["max_steps"],
        parameters=deepcopy(parameters),
        expected_delta=deepcopy(task.get("expected_delta", {})),
        oracle=deepcopy(task["oracle"]),
        checkpoints=deepcopy(task.get("checkpoints", [])),
        tags={
            key: deepcopy(task[key])
            for key in (
                "category", "family", "split", "evaluation_level", "execution_mode"
            )
            if key in task
        },
    )


def legacy_execution_input(task: dict[str, Any]) -> dict[str, Any]:
    public = task_spec_from_legacy(task).execution_input()
    return {
        "id": public["task_id"],
        "prompt": public["prompt"],
        "followups": public["followups"],
        "fixtures": public["initial_state"]["files"],
        "allowed_tools": public["tools"],
        "max_steps": public["max_steps"],
        **public["parameters"],
    }

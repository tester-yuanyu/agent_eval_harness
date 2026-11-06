"""Engine-independent task contract with an explicit private/public boundary.

This in-memory view never rewrites a frozen dataset. Expected deltas are
domain-owned JSON assertions; scorers, not execution runtimes, interpret them.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import Field, StrictInt

from .schema_base import StrictModel


class TaskInput(StrictModel):
    task_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    policy: str = ""
    initial_state: dict[str, Any] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)
    max_steps: StrictInt = Field(default=12, ge=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class TaskSpec(TaskInput):
    """Trusted authoring/scoring view; never pass this object to an Agent."""

    expected_delta: dict[str, Any] = Field(default_factory=dict)
    reference_answer: str | None = None
    oracle: dict[str, Any] = Field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)
    tags: dict[str, Any] = Field(default_factory=dict)

    def execution_input(self) -> dict[str, Any]:
        """Allowlist the public contract and detach all mutable values."""
        return TaskInput.model_validate(
            {name: deepcopy(getattr(self, name)) for name in TaskInput.model_fields}
        ).model_dump(mode="json")

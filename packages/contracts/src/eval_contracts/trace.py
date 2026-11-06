"""Runtime-neutral business trace, derived from authoritative runtime events."""

from typing import Any, Literal

from pydantic import Field

from .schema_base import StrictModel


class StepTrace(StrictModel):
    id: str
    kind: Literal["generation", "tool"]
    native_event_id: str
    data: dict[str, Any]


class TurnTrace(StrictModel):
    id: str
    index: int
    input: str
    output: str | None = None
    snapshot: dict[str, Any] | None = None
    steps: list[StepTrace] = Field(default_factory=list)


class TaskTrace(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    task_id: str
    status: Literal["completed", "error", "timeout"]
    stop_reason: str
    before_state: dict[str, Any] | None = None
    final_state: dict[str, Any] | None = None
    turns: list[TurnTrace] = Field(default_factory=list)
    evidence_complete: bool = False

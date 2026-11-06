"""Composable, deterministic limits checked before costly operations."""

from dataclasses import dataclass
from typing import Literal, Protocol

from .session_state import SessionState

Phase = Literal["model", "tool"]


class StopCondition(Protocol):
    def __call__(self, state: SessionState, phase: Phase) -> str | None: ...


@dataclass(frozen=True)
class StepLimit:
    maximum: int

    def __call__(self, state: SessionState, phase: Phase) -> str | None:
        return (
            "step_limit" if phase == "model" and state.steps >= self.maximum else None
        )


@dataclass(frozen=True)
class ToolCallLimit:
    maximum: int

    def __call__(self, state: SessionState, phase: Phase) -> str | None:
        if phase == "tool" and state.tool_calls >= self.maximum:
            return "tool_call_limit"
        return None


def first_stop(
    conditions: tuple[StopCondition, ...],
    state: SessionState,
    phase: Phase,
) -> str | None:
    for condition in conditions:
        if reason := condition(state, phase):
            return reason
    return None

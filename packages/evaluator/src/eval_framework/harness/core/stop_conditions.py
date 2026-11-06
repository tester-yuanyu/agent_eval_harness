"""Composable, deterministic limits checked before costly operations."""

from dataclasses import dataclass
from math import isfinite
from time import monotonic
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


@dataclass(frozen=True)
class TimeoutStop:
    """Sample-local wall deadline; the loop also cancels in-flight awaits."""

    seconds: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.seconds, bool)
            or not isfinite(self.seconds)
            or self.seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")

    def remaining(self, state: SessionState) -> float:
        return max(0.0, state.started_at + self.seconds - monotonic())

    def __call__(self, state: SessionState, phase: Phase) -> str | None:
        return "time_limit" if self.remaining(state) == 0 else None


@dataclass(frozen=True)
class ErrorStop:
    """Bound consecutive recoverable tool errors; infrastructure still raises."""

    maximum: int

    def __post_init__(self) -> None:
        if type(self.maximum) is not int or self.maximum < 1:
            raise ValueError("max_consecutive_errors must be a positive integer")

    def __call__(self, state: SessionState, phase: Phase) -> str | None:
        return "error_limit" if state.consecutive_errors >= self.maximum else None

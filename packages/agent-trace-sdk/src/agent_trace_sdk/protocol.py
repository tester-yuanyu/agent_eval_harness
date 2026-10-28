"""Versioned evidence envelopes and deterministic collection status."""

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class TraceContext:
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    turn_index: int = 0

    def __post_init__(self):
        if not self.trace_id or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for c in self.trace_id
        ):
            raise ValueError("trace_id must be a nonempty safe identifier")
        if self.turn_index < 0:
            raise ValueError("turn_index must be nonnegative")


@dataclass(frozen=True)
class EventRule:
    layer: str
    fields: tuple[str, ...]
    required: tuple[str, ...] = ()
    field_types: tuple[tuple[str, type], ...] = ()


def status_for(issues, *, completed=False, available=True):
    if not available:
        return "UNAVAILABLE"
    kinds = {issue["kind"] for issue in issues}
    if "export" in kinds:
        return "EXPORT_FAILED"
    if "partial" in kinds:
        return "PARTIAL"
    return "COMPLETE" if completed else "STILL_OPEN"

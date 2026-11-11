"""Runtime-neutral business trace, derived from authoritative runtime events."""

from collections import Counter
from collections.abc import Iterable
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


def duplicate_event_ids(identifiers: Iterable[str]) -> dict[str, int]:
    """返回重复身份及次数；调用者决定诊断码与证据状态。"""
    return {value: count for value, count in Counter(identifiers).items() if count > 1}


def associations_match(values: Iterable[object], expected: object) -> bool:
    """检查同属关联，不强制业务字段或补齐缺失身份。"""
    return all(value == expected for value in values)

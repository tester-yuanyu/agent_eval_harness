"""Shared per-turn expectation models."""

from typing import Any, Literal

from pydantic import Field

from .schema_base import StrictModel


class TurnToolExpectation(StrictModel):
    name: str = Field(min_length=1)
    arguments: dict[str, Any] | None = None
    status: Literal["SUCCESS", "FAILED", "TIMEOUT"] | None = None


class TurnExpectation(StrictModel):
    status: str = Field(min_length=1)
    parameters: dict[str, Any] | None = None
    tool_calls: list[TurnToolExpectation] | None = None
    state: dict[str, Any] | None = None


class TurnCheckConfig(StrictModel):
    turns: list[TurnExpectation] = Field(min_length=1)

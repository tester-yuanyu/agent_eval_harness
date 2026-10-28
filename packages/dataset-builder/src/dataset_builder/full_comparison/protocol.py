"""Strict envelope; input/oracle shapes are checked per capability below."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FullCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    input: dict[str, Any]
    preconditions: list[dict[str, Any]]
    oracle: dict[str, Any] | None
    evidence_refs: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    gap: str | None

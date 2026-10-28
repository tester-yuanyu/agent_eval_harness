"""Shared diagnostic configuration and result models."""

from typing import Any, Literal

from pydantic import Field, model_validator

from .schema_base import StrictModel


class ConversationMetricConfig(StrictModel):
    timeout_seconds: float = Field(default=90, gt=0, le=600, allow_inf_nan=False)


class DiagnosticMetricResult(StrictModel):
    status: Literal["SUCCESS", "ERROR", "NOT_APPLICABLE"]
    score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    reason: str | None = None
    issue_code: str | None = None
    input_sha256: str | None = None
    input_turn_count: int = Field(default=0, ge=0)
    evidence: dict[str, Any] = Field(default_factory=dict)
    token_usage: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_score_state(self):
        if (self.status == "SUCCESS") != (self.score is not None):
            raise ValueError("Only successful diagnostic metrics have numeric scores")
        return self


class DiagnosticMetricSummary(StrictModel):
    status_counts: dict[str, int]
    # Missing judgments remain in status_counts. This is a descriptive mean of
    # successful scores, never a pass rate or a gate input.
    scored_trials: int
    mean_score: float | None

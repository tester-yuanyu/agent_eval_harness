"""Opt-in diagnostic contracts; no scoring engine or release policy lives here."""

from typing import Any, Literal

from pydantic import Field, model_validator

from .schema_base import StrictModel

METRIC_ID = "conversation_completeness"


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


def conversation_input(case, result) -> list[dict[str, str]]:
    """Join observed turns to their execution inputs, never Oracle or unused turns."""
    inputs = [case.execution.user_input, *case.execution.user_responses]
    if not result.turn_results or len(result.turn_results) > len(inputs):
        raise ValueError("Conversation has missing or unmappable actual turns")
    messages = []
    for user, turn in zip(inputs, result.turn_results, strict=False):
        assistant = turn.get("final_response")
        if not all(isinstance(v, str) and v.strip() for v in (user, assistant)):
            raise ValueError("Conversation has a missing user or assistant message")
        messages.extend(
            [
                {"role": "user", "content": user},
                {"role": "assistant", "content": assistant},
            ]
        )
    return messages


async def evaluate_conversation(trial, result, client) -> DiagnosticMetricResult:
    if result.test_scope == "module":
        return DiagnosticMetricResult(status="NOT_APPLICABLE", issue_code="MODULE")
    if result.execution_status != "COMPLETED" or result.evaluation_validity != "VALID":
        return DiagnosticMetricResult(
            status="ERROR", issue_code="EXECUTION_UNAVAILABLE"
        )
    try:
        messages = conversation_input(trial.case, result)
    except ValueError:
        return DiagnosticMetricResult(status="ERROR", issue_code="INCOMPLETE_DIALOGUE")
    if len(messages) < 4:
        return DiagnosticMetricResult(status="NOT_APPLICABLE", issue_code="SINGLE_TURN")
    if result.turn_results[-1].get("status") in {
        "NEED_CLARIFICATION",
        "NEED_CONFIRMATION",
        "RUNNING",
        "MAX_STEPS_EXCEEDED",
        "FAILED",
        "TIMEOUT",
    }:
        return DiagnosticMetricResult(status="ERROR", issue_code="CONVERSATION_OPEN")
    return await client.evaluate(messages)

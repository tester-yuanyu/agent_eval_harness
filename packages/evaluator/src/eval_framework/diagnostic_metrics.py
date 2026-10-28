"""Opt-in diagnostic contracts; no scoring engine or release policy lives here."""

from eval_contracts.diagnostic_metrics import (
    ConversationMetricConfig as ConversationMetricConfig,
)
from eval_contracts.diagnostic_metrics import (
    DiagnosticMetricResult as DiagnosticMetricResult,
)
from eval_contracts.diagnostic_metrics import (
    DiagnosticMetricSummary as DiagnosticMetricSummary,
)

METRIC_ID = "conversation_completeness"


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

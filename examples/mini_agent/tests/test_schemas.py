import pytest
from pydantic import ValidationError

from minimal_agent.contracts.agent import AgentResult, IntentResult, ToolCallRecord


def make_intent(**overrides: object) -> IntentResult:
    values = {
        "intent": "query_information",
        "status": "READY",
        "next_action": "CALL_TOOL",
        "parameters": {"environment": "test"},
        "missing_parameters": [],
        "reason": "The request has all required parameters.",
    }
    values.update(overrides)
    return IntentResult.model_validate(values)


@pytest.mark.parametrize(
    ("status", "next_action", "missing_parameters"),
    [
        ("READY", "CALL_TOOL", []),
        ("NEED_CLARIFICATION", "ASK_USER", ["resource_type"]),
        ("NEED_CONFIRMATION", "ASK_CONFIRMATION", []),
        ("REJECTED", "REJECT", []),
    ],
)
def test_intent_result_accepts_valid_state_combinations(
    status: str,
    next_action: str,
    missing_parameters: list[str],
) -> None:
    result = make_intent(
        status=status,
        next_action=next_action,
        missing_parameters=missing_parameters,
    )

    assert result.status == status
    assert result.next_action == next_action


@pytest.mark.parametrize(
    ("status", "next_action"),
    [
        ("READY", "ASK_USER"),
        ("READY", "REJECT"),
        ("NEED_CLARIFICATION", "CALL_TOOL"),
        ("NEED_CONFIRMATION", "CALL_TOOL"),
        ("REJECTED", "CALL_TOOL"),
    ],
)
def test_intent_result_rejects_invalid_state_combinations(
    status: str, next_action: str
) -> None:
    missing = ["resource_type"] if status == "NEED_CLARIFICATION" else []

    with pytest.raises(ValidationError, match="requires next_action"):
        make_intent(
            status=status,
            next_action=next_action,
            missing_parameters=missing,
        )


def test_clarification_requires_missing_parameters() -> None:
    with pytest.raises(ValidationError, match="at least one missing parameter"):
        make_intent(
            status="NEED_CLARIFICATION",
            next_action="ASK_USER",
            missing_parameters=[],
        )


def test_ready_rejects_missing_parameters() -> None:
    with pytest.raises(ValidationError, match="empty missing_parameters"):
        make_intent(missing_parameters=["environment"])


def test_confirmation_rejects_missing_parameters() -> None:
    with pytest.raises(ValidationError, match="empty missing_parameters"):
        make_intent(
            intent="add_backpack_gift",
            status="NEED_CONFIRMATION",
            next_action="ASK_CONFIRMATION",
            missing_parameters=["user_id"],
        )


def test_protocol_models_reject_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        make_intent(case_id="hidden-evaluation-branch")


def test_agent_result_round_trips_as_json() -> None:
    intent = make_intent()
    tool_call = ToolCallRecord(
        call_id="call_123",
        name="query_information",
        arguments={"environment": "test", "resource_type": "fixture"},
        status="SUCCESS",
        output={"success": True, "data": {}},
        error=None,
        duration_ms=4,
    )
    result = AgentResult(
        run_id="run_123",
        status="SUCCESS",
        intent_result=intent,
        tool_calls=[tool_call],
        final_response="Query completed.",
        events=[],
    )

    restored = AgentResult.model_validate_json(result.model_dump_json())

    assert restored == result


def test_tool_call_duration_cannot_be_negative() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        ToolCallRecord(
            call_id="call_123",
            name="query_information",
            arguments={},
            status="FAILED",
            output=None,
            error="failure",
            duration_ms=-1,
        )

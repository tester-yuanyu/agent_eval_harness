import pytest

from minimal_agent.runtime.intent_router import IntentRouter, run_intent_only
from minimal_agent.runtime.model_client import (
    InvalidModelOutputError,
    ModelClient,
    ModelInvocationError,
    ScriptExhaustedError,
)
from tests.support.model_client import DeterministicModelClient


def ready_response() -> dict[str, object]:
    return {
        "intent": "query_information",
        "status": "READY",
        "next_action": "CALL_TOOL",
        "parameters": {
            "resource_type": "fixture",
            "environment": "test",
        },
        "missing_parameters": [],
        "reason": "All required parameters are present.",
    }


def test_scripted_client_satisfies_model_client_protocol() -> None:
    client = DeterministicModelClient([ready_response()])

    assert isinstance(client, ModelClient)


def test_ready_result_is_validated_and_returned() -> None:
    client = DeterministicModelClient([ready_response()])
    router = IntentRouter(client)

    result = router.run_intent_only("query the fixture in test")

    assert result.intent == "query_information"
    assert result.status == "READY"
    assert result.next_action == "CALL_TOOL"
    assert result.parameters == {
        "resource_type": "fixture",
        "environment": "test",
    }
    assert client.requests == ["query the fixture in test"]
    assert client.remaining_responses == 0


def test_clarification_result_is_returned_without_tool_execution() -> None:
    response = {
        "intent": "prepare_resource",
        "status": "NEED_CLARIFICATION",
        "next_action": "ASK_USER",
        "parameters": {"resource_type": "fixture"},
        "missing_parameters": ["environment", "count"],
        "reason": "Environment and count are required.",
    }
    client = DeterministicModelClient([response])

    result = run_intent_only("prepare fixtures", client)

    assert result.status == "NEED_CLARIFICATION"
    assert result.missing_parameters == ["environment", "count", "request_id"]


def test_rejected_result_is_returned() -> None:
    response = {
        "intent": "unsupported",
        "status": "REJECTED",
        "next_action": "REJECT",
        "parameters": {},
        "missing_parameters": [],
        "reason": "The requested capability is unsupported.",
    }

    result = run_intent_only(
        "perform an unsupported operation",
        DeterministicModelClient([response]),
    )

    assert result.intent == "unsupported"
    assert result.status == "REJECTED"


def test_json_response_is_supported() -> None:
    response = (
        '{"intent":"query_information","status":"READY",'
        '"next_action":"CALL_TOOL","parameters":{"environment":"test"},'
        '"missing_parameters":[],"reason":"Complete."}'
    )

    result = run_intent_only("query", DeterministicModelClient([response]))

    assert result.status == "NEED_CLARIFICATION"
    assert result.missing_parameters == ["resource_type"]


@pytest.mark.parametrize(
    "response",
    [
        {"status": "READY"},
        {
            **ready_response(),
            "status": "NEED_CLARIFICATION",
            "next_action": "CALL_TOOL",
        },
        {**ready_response(), "unexpected": True},
        "not valid json",
        ["not", "an", "object"],
    ],
)
def test_invalid_model_output_raises_domain_error(response: object) -> None:
    with pytest.raises(InvalidModelOutputError) as error:
        run_intent_only("query", DeterministicModelClient([response]))

    assert "invalid IntentResult" in str(error.value)
    assert error.value.__cause__ is not None


def test_model_exception_is_wrapped_as_domain_error() -> None:
    client = DeterministicModelClient([TimeoutError("model timed out")])

    with pytest.raises(ModelInvocationError) as error:
        run_intent_only("query", client)

    assert "invocation failed" in str(error.value)
    assert isinstance(error.value.__cause__, TimeoutError)


def test_script_exhaustion_fails_explicitly() -> None:
    client = DeterministicModelClient([])

    with pytest.raises(ScriptExhaustedError, match="responses are exhausted"):
        run_intent_only("query", client)


def test_scripted_responses_are_consumed_in_order() -> None:
    rejected = {
        "intent": "unsupported",
        "status": "REJECTED",
        "next_action": "REJECT",
        "parameters": {},
        "missing_parameters": [],
        "reason": "Unsupported.",
    }
    client = DeterministicModelClient([ready_response(), rejected])
    router = IntentRouter(client)

    first = router.run_intent_only("first input")
    second = router.run_intent_only("second input")

    assert first.status == "READY"
    assert second.status == "REJECTED"
    assert client.requests == ["first input", "second input"]

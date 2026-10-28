import pytest

from minimal_agent.contracts.tools import ToolResult
from minimal_agent.runtime.agent import MinimalAgent
from minimal_agent.runtime.tool_registry import ToolDefinition, ToolRegistry
from tests.support.model_client import DeterministicModelClient
from tests.support.tools import ECHO_CONTRACT, echo_definition


def ready_intent() -> dict[str, object]:
    return {
        "intent": "query_information",
        "status": "READY",
        "next_action": "CALL_TOOL",
        "parameters": {"resource_type": "fixture", "environment": "test"},
        "missing_parameters": [],
        "reason": "Ready.",
    }


def rejected_intent() -> dict[str, object]:
    return {
        "intent": "unsupported",
        "status": "REJECTED",
        "next_action": "REJECT",
        "parameters": {},
        "missing_parameters": [],
        "reason": "Unsupported.",
    }


def tool_call(
    *, name: str = "echo", arguments: dict[str, object] | None = None
) -> dict[str, object]:
    return {
        "type": "function_call",
        "call_id": "call-1",
        "name": name,
        "arguments": arguments or {"text": "hello"},
    }


def make_agent(
    responses: list[object], registry: ToolRegistry | None = None, *, max_steps: int = 4
) -> MinimalAgent:
    return MinimalAgent(
        DeterministicModelClient(responses),
        registry or ToolRegistry(),
        max_steps=max_steps,
        run_id_factory=lambda: "run-test",
    )


def echo_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(echo_definition())
    return registry


def test_intent_only_works_with_an_empty_registry() -> None:
    agent = make_agent([rejected_intent()])

    result = agent.run_intent_only("unsupported")

    assert result.status == "REJECTED"
    assert agent.intent_trace_snapshot()[-1]["event_type"] == "intent_decided"


def test_registered_tool_completes_the_plan_call_result_answer_loop() -> None:
    agent = make_agent(
        [
            ready_intent(),
            tool_call(),
            {"type": "message", "content": "Echo complete."},
        ],
        echo_registry(),
    )

    result = agent.run("echo hello")

    assert result.status == "SUCCESS"
    assert result.final_response == "Echo complete."
    assert result.tool_calls[0].output == {
        "success": True,
        "code": "OK",
        "message": "echoed",
        "data": {"text": "hello"},
    }
    assert "tool_succeeded" in {event["event_type"] for event in result.events}


def test_unavailable_tool_returns_a_stable_terminal_failure() -> None:
    agent = make_agent([ready_intent(), tool_call(name="missing")])

    result = agent.run("use missing tool")

    assert result.status == "FAILED"
    assert result.tool_calls[0].status == "FAILED"
    assert "TOOL_NOT_AVAILABLE" in (result.tool_calls[0].error or "")
    assert result.tool_calls[0].output is None


def test_invalid_arguments_do_not_call_the_handler() -> None:
    calls: list[str] = []

    def handler(text: str) -> ToolResult:
        calls.append(text)
        return ToolResult(success=True, code="OK", message="ok", data={})

    registry = ToolRegistry()
    registry.register(ToolDefinition(contract=ECHO_CONTRACT, handler=handler))
    agent = make_agent(
        [ready_intent(), tool_call(arguments={"text": 123})], registry
    )

    result = agent.run("invalid echo")

    assert result.status == "FAILED"
    assert calls == []


def test_allow_list_denial_is_observable() -> None:
    agent = make_agent([ready_intent(), tool_call()], echo_registry())

    result = agent.run("blocked echo", allowed_tools=frozenset())

    assert result.status == "FAILED"
    assert "TOOL_NOT_ALLOWED" in (result.tool_calls[0].error or "")


@pytest.mark.parametrize(
    ("raised", "expected_status", "expected_event"),
    [
        (RuntimeError("handler failed"), "FAILED", "tool_failed"),
        (TimeoutError("handler timed out"), "TIMEOUT", "tool_timeout"),
    ],
)
def test_handler_failures_are_normalized(
    raised: Exception, expected_status: str, expected_event: str
) -> None:
    def handler(text: str) -> ToolResult:
        del text
        raise raised

    registry = ToolRegistry()
    registry.register(ToolDefinition(contract=ECHO_CONTRACT, handler=handler))
    agent = make_agent([ready_intent(), tool_call()], registry)

    result = agent.run("failing echo")

    assert result.status == "FAILED"
    assert result.tool_calls[0].status == expected_status
    assert result.tool_calls[0].output is None
    assert expected_event in {event["event_type"] for event in result.events}


def test_model_can_finish_without_calling_a_tool() -> None:
    agent = make_agent(
        [ready_intent(), {"type": "message", "content": "No tool required."}]
    )

    result = agent.run("answer directly")

    assert result.status == "SUCCESS"
    assert result.tool_calls == []
    assert result.final_response == "No tool required."


def test_maximum_steps_terminates_repeated_tool_calls() -> None:
    agent = make_agent(
        [ready_intent(), tool_call()], echo_registry(), max_steps=1
    )

    result = agent.run("echo forever")

    assert result.status == "MAX_STEPS_EXCEEDED"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].status == "SUCCESS"
    assert result.events[-2]["event_type"] == "max_steps_exceeded"

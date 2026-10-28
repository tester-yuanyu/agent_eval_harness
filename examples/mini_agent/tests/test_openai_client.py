import json
from collections import deque
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import ConfigDict

from minimal_agent.contracts.agent import (
    FunctionCallOutput,
    IntentResult,
    ProtocolModel,
    ToolLoopRequest,
)
from minimal_agent.contracts.tools import ToolResult
from minimal_agent.runtime.agent import MinimalAgent
from minimal_agent.runtime.model_client import (
    InvalidModelOutputError,
    ModelInvocationError,
    ModelTimeoutError,
)
from minimal_agent.runtime.openai_client import (
    OpenAIClientConfigurationError,
    OpenAIModelClient,
)
from minimal_agent.runtime.prompts import INTENT_PROMPT_VERSION, TOOL_PROMPT_VERSION
from minimal_agent.runtime.tool_registry import ToolDefinition, ToolRegistry
from tests.support.tools import ECHO_CONTRACT


class FakeResponses:
    def __init__(
        self,
        *,
        parse_results: list[object] | None = None,
        create_results: list[object] | None = None,
    ) -> None:
        self._parse_results = deque(parse_results or [])
        self._create_results = deque(create_results or [])
        self.parse_calls: list[dict[str, object]] = []
        self.create_calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.parse_calls.append(kwargs)
        return self._next(self._parse_results)

    def create(self, **kwargs: object) -> object:
        self.create_calls.append(kwargs)
        return self._next(self._create_results)

    @staticmethod
    def _next(items: deque[object]) -> object:
        item = items.popleft()
        if isinstance(item, BaseException):
            raise item
        return item


class FakeSDKClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


class QueryInformationArguments(ProtocolModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    resource_type: str
    environment: str


def query_information(resource_type: str, environment: str) -> ToolResult:
    del resource_type, environment
    return ToolResult(
        success=True,
        code="OK",
        message="queried",
        data={"count": 0},
    )


def query_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            contract=replace(
                ECHO_CONTRACT,
                name="query_information",
                arguments_model=QueryInformationArguments,
            ),
            handler=query_information,
        )
    )
    return registry


def ready_intent() -> IntentResult:
    return IntentResult(
        intent="query_information",
        status="READY",
        next_action="CALL_TOOL",
        parameters={"resource_type": "fixture", "environment": "test"},
        missing_parameters=[],
        reason="Ready.",
    )


def tool_request(
    registry: ToolRegistry,
    *,
    step: int,
    outputs: list[FunctionCallOutput] | None = None,
) -> ToolLoopRequest:
    return ToolLoopRequest(
        user_input="query fixtures",
        intent_result=ready_intent(),
        tool_schemas=registry.schemas(),
        tool_outputs=outputs or [],
        step=step,
    )


def test_intent_uses_responses_parse_with_pydantic_schema() -> None:
    parsed = ready_intent()
    responses = FakeResponses(
        parse_results=[SimpleNamespace(output_parsed=parsed)]
    )
    client = OpenAIModelClient(FakeSDKClient(responses), model="configured-model")

    result = client.classify_intent("query fixtures")

    assert result == parsed
    call = responses.parse_calls[0]
    assert call["model"] == "configured-model"
    assert call["input"] == "query fixtures"
    assert call["text_format"] is IntentResult
    assert call["timeout"] == 30.0


def test_from_env_reads_key_and_model_without_hardcoded_defaults(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")
    captured: dict[str, object] = {}
    fake_sdk = FakeSDKClient(FakeResponses())

    def factory(**kwargs: object) -> FakeSDKClient:
        captured.update(kwargs)
        return fake_sdk

    client = OpenAIModelClient.from_env(client_factory=factory)

    assert captured == {
        "api_key": "environment-key",
        "timeout": 30.0,
        "max_retries": 0,
    }
    assert client.metadata()["model"] == "environment-model"
    assert "environment-key" not in repr(client.metadata())


@pytest.mark.parametrize("missing_name", ["OPENAI_API_KEY", "OPENAI_MODEL"])
def test_from_env_fails_when_required_configuration_is_missing(
    monkeypatch,
    missing_name: str,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")
    monkeypatch.delenv(missing_name)

    with pytest.raises(OpenAIClientConfigurationError, match=missing_name):
        OpenAIModelClient.from_env()


def test_api_timeout_becomes_domain_timeout() -> None:
    responses = FakeResponses(parse_results=[TimeoutError("slow")])
    client = OpenAIModelClient(FakeSDKClient(responses), model="configured-model")

    with pytest.raises(ModelTimeoutError) as error:
        client.classify_intent("query fixtures")

    assert isinstance(error.value.__cause__, TimeoutError)


def test_api_error_becomes_domain_invocation_error() -> None:
    responses = FakeResponses(parse_results=[RuntimeError("API failed")])
    client = OpenAIModelClient(FakeSDKClient(responses), model="configured-model")

    with pytest.raises(ModelInvocationError) as error:
        client.classify_intent("query fixtures")

    assert isinstance(error.value.__cause__, RuntimeError)


def test_missing_parsed_intent_fails_explicitly() -> None:
    responses = FakeResponses(
        parse_results=[SimpleNamespace(output_parsed=None)]
    )
    client = OpenAIModelClient(FakeSDKClient(responses), model="configured-model")

    with pytest.raises(InvalidModelOutputError, match="parsed IntentResult"):
        client.classify_intent("query fixtures")


def test_function_call_output_is_linked_by_call_id() -> None:
    registry = query_registry()
    function_call = SimpleNamespace(
        type="function_call",
        call_id="call-123",
        name="query_information",
        arguments='{"resource_type":"fixture","environment":"test"}',
    )
    responses = FakeResponses(
        create_results=[
            SimpleNamespace(id="response-1", output=[function_call], output_text=""),
            SimpleNamespace(
                id="response-2",
                output=[],
                output_text="No resources found.",
            ),
        ]
    )
    client = OpenAIModelClient(FakeSDKClient(responses), model="configured-model")

    first = client.next_tool_step(tool_request(registry, step=1))
    second = client.next_tool_step(
        tool_request(
            registry,
            step=2,
            outputs=[
                FunctionCallOutput(
                    call_id="call-123",
                    name="query_information",
                    output={"success": True, "data": {"count": 0}},
                )
            ],
        )
    )

    assert first == {
        "type": "function_call",
        "call_id": "call-123",
        "name": "query_information",
        "arguments": {"resource_type": "fixture", "environment": "test"},
    }
    assert second == {"type": "message", "content": "No resources found."}
    first_call, second_call = responses.create_calls
    assert first_call["parallel_tool_calls"] is False
    assert first_call["tool_choice"] == "required"
    assert "previous_response_id" not in first_call
    assert all(schema["strict"] is True for schema in first_call["tools"])
    assert second_call["parallel_tool_calls"] is False
    assert second_call["tool_choice"] == "auto"
    assert second_call["previous_response_id"] == "response-1"
    function_output = second_call["input"][0]
    assert function_output["type"] == "function_call_output"
    assert function_output["call_id"] == "call-123"
    assert json.loads(function_output["output"])["data"]["count"] == 0


def test_invalid_function_arguments_fail_explicitly() -> None:
    registry = query_registry()
    responses = FakeResponses(
        create_results=[
            SimpleNamespace(
                id="response-1",
                output=[
                    SimpleNamespace(
                        type="function_call",
                        call_id="call-invalid",
                        name="query_information",
                        arguments="not-json",
                    )
                ],
                output_text="",
            )
        ]
    )
    client = OpenAIModelClient(FakeSDKClient(responses), model="configured-model")

    with pytest.raises(InvalidModelOutputError, match="not valid JSON"):
        client.next_tool_step(tool_request(registry, step=1))


def test_openai_client_runs_through_minimal_agent() -> None:
    registry = query_registry()
    function_call = SimpleNamespace(
        type="function_call",
        call_id="call-agent",
        name="query_information",
        arguments='{"resource_type":"fixture","environment":"test"}',
    )
    responses = FakeResponses(
        parse_results=[SimpleNamespace(output_parsed=ready_intent())],
        create_results=[
            SimpleNamespace(id="response-1", output=[function_call], output_text=""),
            SimpleNamespace(
                id="response-2",
                output=[],
                output_text="No resources found.",
            ),
        ],
    )
    client = OpenAIModelClient(FakeSDKClient(responses), model="configured-model")
    agent = MinimalAgent(
        client,
        registry,
        run_id_factory=lambda: "run-openai-test",
    )

    result = agent.run("query fixtures")

    assert result.status == "SUCCESS"
    assert result.tool_calls[0].call_id == "call-agent"
    assert result.final_response == "No resources found."
    run_started = result.events[0]
    assert run_started["payload"]["model"] == {
        "model_client": "openai_responses",
        "model": "configured-model",
        "intent_prompt_version": INTENT_PROMPT_VERSION,
        "tool_prompt_version": TOOL_PROMPT_VERSION,
    }
    assert run_started["payload"]["tools"]["tool_names"] == ["query_information"]


def test_tool_api_failure_cannot_return_agent_success() -> None:
    registry = query_registry()
    responses = FakeResponses(
        parse_results=[SimpleNamespace(output_parsed=ready_intent())],
        create_results=[RuntimeError("API unavailable")],
    )
    client = OpenAIModelClient(FakeSDKClient(responses), model="configured-model")
    agent = MinimalAgent(client, registry)

    result = agent.run("query fixtures")

    assert result.status == "FAILED"
    assert result.tool_calls == []
    assert "ModelInvocationError" in result.final_response

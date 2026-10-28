import json
from collections import deque
from types import SimpleNamespace

import pytest

from minimal_agent.contracts.agent import (
    FunctionCallOutput,
    IntentResult,
    ToolLoopRequest,
)
from minimal_agent.runtime.deepseek_client import (
    DeepSeekClientConfigurationError,
    DeepSeekModelClient,
)
from minimal_agent.runtime.model_client import InvalidModelOutputError


class FakeResponses:
    def __init__(self, results: list[object]) -> None:
        self._results = deque(results)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        result = self._results.popleft()
        if isinstance(result, BaseException):
            raise result
        return result


class FakeSDKClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def ready_intent() -> IntentResult:
    return IntentResult(
        intent="query_user",
        status="READY",
        next_action="CALL_TOOL",
        parameters={"user_id": 123},
        missing_parameters=[],
        reason="Ready.",
    )


def test_from_env_uses_deepseek_endpoint_without_exposing_key(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    captured: dict[str, object] = {}
    fake_sdk = FakeSDKClient(FakeResponses([]))

    def factory(**kwargs: object) -> FakeSDKClient:
        captured.update(kwargs)
        return fake_sdk

    client = DeepSeekModelClient.from_env(client_factory=factory)

    assert captured == {
        "api_key": "deepseek-test-key",
        "base_url": "https://api.deepseek.com",
        "timeout": 30.0,
        "max_retries": 0,
    }
    assert client.metadata()["model"] == "deepseek-flash"
    assert "deepseek-test-key" not in repr(client.metadata())


@pytest.mark.parametrize("missing_name", ["DEEPSEEK_API_KEY", "DEEPSEEK_MODEL"])
def test_from_env_requires_key_and_model(monkeypatch, missing_name: str) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    monkeypatch.delenv(missing_name)

    with pytest.raises(DeepSeekClientConfigurationError, match=missing_name):
        DeepSeekModelClient.from_env()


def test_intent_uses_json_object_mode_and_validates_result() -> None:
    responses = FakeResponses(
        [SimpleNamespace(output_text=ready_intent().model_dump_json())]
    )
    client = DeepSeekModelClient(FakeSDKClient(responses), model="deepseek-flash")

    result = client.classify_intent("查询用户 123")

    assert result == ready_intent()
    call = responses.calls[0]
    assert call["model"] == "deepseek-flash"
    assert call["input"] == "查询用户 123"
    assert call["text"]["format"] == {"type": "json_object"}
    assert "JSON Schema" in call["instructions"]
    assert '"next_action"' in call["instructions"]
    assert client.metadata()["structured_output_mode"] == (
        "json_object+pydantic"
    )


def test_invalid_intent_json_fails_explicitly() -> None:
    responses = FakeResponses([SimpleNamespace(output_text="not-json")])
    client = DeepSeekModelClient(FakeSDKClient(responses), model="deepseek-flash")

    with pytest.raises(InvalidModelOutputError, match="IntentResult"):
        client.classify_intent("查询用户")


def test_invalid_intent_keeps_redacted_versioned_diagnostic() -> None:
    raw = '{"intent":"query_user","token":"sk-secret123456789"}'
    responses = FakeResponses([SimpleNamespace(output_text=raw)])
    client = DeepSeekModelClient(FakeSDKClient(responses), model="deepseek-flash")

    with pytest.raises(InvalidModelOutputError) as captured:
        client.classify_intent("查询用户")

    diagnostic = captured.value.diagnostic
    assert diagnostic["raw_output_redacted"] != raw
    assert "sk-secret123456789" not in diagnostic["raw_output_redacted"]
    assert diagnostic["validation_errors"]
    assert diagnostic["prompt_version"]
    assert diagnostic["schema_version"]
    assert len(diagnostic["schema_sha256"]) == 64
    assert "sk-secret123456789" not in json.dumps(diagnostic)


def test_tool_continuation_resends_complete_history() -> None:
    function_call = {
        "type": "function_call",
        "call_id": "call-1",
        "name": "query_user_info",
        "arguments": '{"user_id":123}',
    }
    responses = FakeResponses(
        [
            SimpleNamespace(output=[function_call], output_text=""),
            SimpleNamespace(
                output=[
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "查询成功"}
                        ],
                    }
                ],
                output_text="查询成功",
            ),
        ]
    )
    client = DeepSeekModelClient(FakeSDKClient(responses), model="deepseek-flash")
    first_request = ToolLoopRequest(
        user_input="查询用户 123",
        intent_result=ready_intent(),
        tool_schemas=[
            {
                "type": "function",
                "name": "query_user_info",
                "description": "query",
                "parameters": {"type": "object"},
                "strict": True,
            }
        ],
        tool_outputs=[],
        step=1,
    )

    first = client.next_tool_step(first_request)
    second = client.next_tool_step(
        first_request.model_copy(
            update={
                "step": 2,
                "tool_outputs": [
                    FunctionCallOutput(
                        call_id="call-1",
                        name="query_user_info",
                        output={"success": True},
                    )
                ],
            }
        )
    )

    assert first["name"] == "query_user_info"
    assert second == {"type": "message", "content": "查询成功"}
    first_call, second_call = responses.calls
    assert first_call["tool_choice"] == "required"
    assert second_call["tool_choice"] == "auto"
    assert "previous_response_id" not in second_call
    history = second_call["input"]
    assert history[0]["role"] == "user"
    assert function_call in history
    function_output = history[-1]
    assert function_output["type"] == "function_call_output"
    assert function_output["call_id"] == "call-1"
    assert json.loads(function_output["output"])["success"] is True

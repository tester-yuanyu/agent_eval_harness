import json

from minimal_agent.cli import main
from minimal_agent.contracts.agent import AgentResult, CliErrorResult, IntentResult
from minimal_agent.runtime.tool_registry import ToolRegistry
from tests.support.model_client import DeterministicModelClient
from tests.support.tools import echo_definition


def rejected_intent() -> dict[str, object]:
    return {
        "intent": "unsupported",
        "status": "REJECTED",
        "next_action": "REJECT",
        "parameters": {},
        "missing_parameters": [],
        "reason": "Unsupported.",
    }


def ready_intent() -> dict[str, object]:
    return {
        "intent": "query_information",
        "status": "READY",
        "next_action": "CALL_TOOL",
        "parameters": {"resource_type": "fixture", "environment": "test"},
        "missing_parameters": [],
        "reason": "Ready.",
    }


def test_intent_cli_outputs_protocol_json(capsys) -> None:
    client = DeterministicModelClient([rejected_intent()])

    exit_code = main(
        ["intent", "unsupported"],
        openai_client_factory=lambda: client,
    )

    assert exit_code == 0
    result = IntentResult.model_validate_json(capsys.readouterr().out)
    assert result.status == "REJECTED"


def test_run_cli_defaults_to_an_empty_registry_without_creating_state(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    client = DeterministicModelClient([rejected_intent()])

    exit_code = main(
        ["run", "unsupported"],
        openai_client_factory=lambda: client,
    )

    assert exit_code == 0
    result = AgentResult.model_validate_json(capsys.readouterr().out)
    assert result.status == "REJECTED"
    assert list(tmp_path.iterdir()) == []


def test_run_cli_executes_a_tool_from_the_injected_registry(capsys) -> None:
    client = DeterministicModelClient(
        [
            ready_intent(),
            {
                "type": "function_call",
                "call_id": "call-cli",
                "name": "echo",
                "arguments": {"text": "hello"},
            },
            {"type": "message", "content": "Echo complete."},
        ]
    )
    registry = ToolRegistry()
    registry.register(echo_definition())

    exit_code = main(
        ["run", "echo hello"],
        openai_client_factory=lambda: client,
        tool_registry_factory=lambda: registry,
    )

    assert exit_code == 0
    result = AgentResult.model_validate_json(capsys.readouterr().out)
    assert result.status == "SUCCESS"
    assert result.tool_calls[0].name == "echo"


def test_cli_error_is_structured_protocol_json(capsys) -> None:
    def fail_to_configure():
        raise RuntimeError("model configuration is unavailable")

    exit_code = main(
        ["intent", "query fixtures"],
        openai_client_factory=fail_to_configure,
    )

    assert exit_code == 1
    result = CliErrorResult.model_validate_json(capsys.readouterr().out)
    assert result.error_type == "RuntimeError"
    assert result.message == "model configuration is unavailable"


def test_removed_mock_cli_flags_are_rejected(capsys) -> None:
    try:
        main(["run", "anything", "--profile", "shadow"])
    except SystemExit as exc:
        assert exc.code == 2
    error = capsys.readouterr().err
    assert "unrecognized arguments" in error
    json.dumps(error)

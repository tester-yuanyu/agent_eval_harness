from dataclasses import replace

import pytest

from minimal_agent.contracts.tools import ToolResult
from minimal_agent.runtime.tool_registry import (
    DuplicateToolError,
    InvalidToolArgumentsError,
    ToolDefinition,
    ToolNotAllowedError,
    ToolNotAvailableError,
    ToolRegistry,
)
from tests.support.tools import ECHO_CONTRACT, echo_definition


def test_tool_contract_defaults_to_production_without_simulation_metadata() -> None:
    assert ECHO_CONTRACT.implementation_profile == "production"
    assert ECHO_CONTRACT.simulation_capabilities == ()
    assert ECHO_CONTRACT.observation_interfaces == ()


def test_tool_contract_accepts_explicit_evaluation_adapter_metadata() -> None:
    contract = replace(
        ECHO_CONTRACT,
        implementation_profile="evaluation_adapter",
        simulation_capabilities=("success", "timeout"),
        observation_interfaces=("tool_trace", "state_event"),
    )

    assert contract.implementation_profile == "evaluation_adapter"
    assert contract.simulation_capabilities == ("success", "timeout")
    assert contract.observation_interfaces == ("tool_trace", "state_event")


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("simulation_capabilities", ("",)),
        ("observation_interfaces", (" ",)),
    ],
)
def test_tool_contract_rejects_empty_metadata_entries(
    field_name: str,
    value: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match=field_name):
        replace(ECHO_CONTRACT, **{field_name: value})


def test_registry_preserves_registration_order_in_immutable_definitions() -> None:
    second = ECHO_CONTRACT.__class__(
        **{**ECHO_CONTRACT.__dict__, "name": "echo_second"}
    )
    registry = ToolRegistry()
    registry.register(echo_definition())
    registry.register(
        ToolDefinition(
            contract=second,
            handler=lambda text: ToolResult(
                success=True,
                code="OK",
                message="echoed",
                data={"text": text},
            ),
        )
    )

    definitions = registry.definitions

    assert isinstance(definitions, tuple)
    assert [definition.name for definition in definitions] == [
        "echo",
        "echo_second",
    ]


def test_registry_exposes_a_strict_function_schema() -> None:
    registry = ToolRegistry()
    registry.register(echo_definition())

    assert registry.schemas() == [
        {
            "type": "function",
            "name": "echo",
            "description": "Return the supplied text.",
            "parameters": {
                "additionalProperties": False,
                "properties": {
                    "text": {"minLength": 1, "title": "Text", "type": "string"}
                },
                "required": ["text"],
                "title": "EchoArguments",
                "type": "object",
            },
            "strict": True,
        }
    ]


def test_registry_validates_and_invokes_a_registered_tool() -> None:
    registry = ToolRegistry()
    registry.register(echo_definition())

    result = registry.invoke("echo", {"text": "hello"})

    assert result == ToolResult(
        success=True,
        code="OK",
        message="echoed",
        data={"text": "hello"},
    )


def test_registry_rejects_duplicate_names() -> None:
    registry = ToolRegistry()
    registry.register(echo_definition())

    with pytest.raises(DuplicateToolError):
        registry.register(echo_definition())


def test_registry_reports_a_stable_unavailable_tool_code() -> None:
    error = ToolNotAvailableError("missing")

    assert error.code == "TOOL_NOT_AVAILABLE"
    with pytest.raises(ToolNotAvailableError):
        ToolRegistry().invoke("missing", {})


def test_registry_filters_and_enforces_the_run_allow_list() -> None:
    registry = ToolRegistry()
    registry.register(echo_definition())

    assert registry.schemas(allowed_tools=frozenset()) == []
    with pytest.raises(ToolNotAllowedError) as captured:
        registry.invoke("echo", {"text": "blocked"}, allowed_tools=frozenset())
    assert captured.value.code == "TOOL_NOT_ALLOWED"


def test_invalid_arguments_never_call_the_handler() -> None:
    calls: list[str] = []

    def handler(text: str) -> ToolResult:
        calls.append(text)
        return ToolResult(success=True, code="OK", message="ok", data={})

    registry = ToolRegistry()
    registry.register(ToolDefinition(contract=ECHO_CONTRACT, handler=handler))

    with pytest.raises(InvalidToolArgumentsError):
        registry.invoke("echo", {"text": 123})

    assert calls == []

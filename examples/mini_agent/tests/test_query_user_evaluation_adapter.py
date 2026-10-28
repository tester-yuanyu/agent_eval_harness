import pytest

from minimal_agent.contracts.tools import ToolResult
from minimal_agent.runtime.tool_registry import InvalidToolArgumentsError
from minimal_agent.testing.query_user_tool import (
    QUERY_USER_EVALUATION_CONTRACT,
    query_user_evaluation_definition,
)


def _arguments(**updates):
    values = {
        "user_id": None,
        "room_id": None,
        "email": None,
        "phone": None,
    }
    values.update(updates)
    return values


def test_adapter_requires_an_explicit_handler() -> None:
    with pytest.raises(TypeError):
        query_user_evaluation_definition()  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="handler"):
        query_user_evaluation_definition(None)  # type: ignore[arg-type]


def test_adapter_reuses_strict_single_and_multi_condition_arguments() -> None:
    calls: list[dict[str, object]] = []

    def handler(**arguments) -> ToolResult:
        calls.append(arguments)
        return ToolResult(success=True, code="OK", message="matched", data=arguments)

    definition = query_user_evaluation_definition(handler)

    single = definition.invoke(_arguments(user_id=10001))
    multi = definition.invoke(_arguments(room_id=20002, email="person@example.com"))

    assert single.data["user_id"] == 10001
    assert multi.data == {
        "user_id": None,
        "room_id": 20002,
        "email": "person@example.com",
        "phone": None,
    }
    assert len(calls) == 2
    with pytest.raises(InvalidToolArgumentsError, match="invalid arguments"):
        definition.invoke(_arguments(phone="123"))
    with pytest.raises(InvalidToolArgumentsError, match="invalid arguments"):
        definition.invoke(_arguments())


def test_injected_handler_owns_deterministic_fixture_results() -> None:
    fixture = {10001: {"display_name": "fixture-user"}}

    def handler(**arguments) -> ToolResult:
        user = fixture.get(arguments["user_id"])
        return ToolResult(
            success=user is not None,
            code="OK" if user else "EMPTY",
            message="matched" if user else "not found",
            data={"user": user},
        )

    result = query_user_evaluation_definition(handler).invoke(_arguments(user_id=10001))

    assert result.data == {"user": {"display_name": "fixture-user"}}


def test_contract_declares_evaluation_execution_metadata() -> None:
    contract = QUERY_USER_EVALUATION_CONTRACT

    assert contract.name == "query_user_info"
    assert contract.implementation_profile == "evaluation_adapter"
    assert set(contract.simulation_capabilities) >= {
        "success",
        "empty_result",
        "business_failure",
        "timeout",
        "rate_limit",
        "execution_failure",
    }
    assert contract.side_effects == ()
    assert contract.risk_level == "low"
    assert contract.requires_confirmation is False
    assert contract.observation_interfaces == (
        "agent_result.tool_calls",
        "agent_result.events",
    )
    assert contract.version

"""Fixture-free QueryUser Tool adapter for evaluator-owned handlers."""

from collections.abc import Callable

from minimal_agent.contracts.intent_parameters import QueryUserInfoArguments
from minimal_agent.contracts.tools import ToolContract, ToolResult
from minimal_agent.runtime.tool_registry import ToolDefinition

QueryUserEvaluationHandler = Callable[..., ToolResult]

QUERY_USER_EVALUATION_CONTRACT = ToolContract(
    name="query_user_info",
    version="query-user-evaluation-adapter-v1",
    description=(
        "Query user information through an evaluator-injected deterministic handler."
    ),
    arguments_model=QueryUserInfoArguments,
    tool_type="read",
    parameter_rules={
        "condition_cardinality": "AT_LEAST_ONE",
        "multiple_conditions": "AND",
        "batch_queries": "UNSUPPORTED",
        "accepted_fields": ["user_id", "room_id", "email", "phone"],
    },
    permission_requirements=("REGISTERED_TOOL_AND_RUN_ALLOW_LIST",),
    requires_confirmation=False,
    risk_level="low",
    idempotency_rules={
        "mode": "READ_ONLY",
        "same_fixture_and_arguments": "DETERMINISTIC",
    },
    side_effects=(),
    result_contracts={
        "OK": {
            "terminal_status": "success",
            "data_schema": {"type": "object"},
        },
        "EMPTY": {
            "terminal_status": "success",
            "data_schema": {"type": "object"},
        },
        "BUSINESS_FAILURE": {
            "terminal_status": "business_failure",
            "data_schema": {"type": "object"},
        },
        "RATE_LIMITED": {
            "terminal_status": "business_failure",
            "data_schema": {"type": "object"},
        },
    },
    empty_result_behavior="HANDLER_RETURNS_EMPTY_RESULT_PROTOCOL",
    partial_success_behavior="UNSUPPORTED",
    trace_event_types=(),
    implementation_profile="evaluation_adapter",
    simulation_capabilities=(
        "success",
        "empty_result",
        "business_failure",
        "timeout",
        "rate_limit",
        "execution_failure",
    ),
    observation_interfaces=(
        "agent_result.tool_calls",
        "agent_result.events",
    ),
)


def query_user_evaluation_definition(
    handler: QueryUserEvaluationHandler,
) -> ToolDefinition:
    """Bind caller-owned fixture behavior to the public evaluation contract."""

    if not callable(handler):
        raise TypeError("handler must be an explicit callable")
    return ToolDefinition(contract=QUERY_USER_EVALUATION_CONTRACT, handler=handler)

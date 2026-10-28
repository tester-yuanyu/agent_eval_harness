"""Deterministic tools owned by tests rather than the Agent runtime."""

from pydantic import ConfigDict, Field

from minimal_agent.contracts.agent import ProtocolModel
from minimal_agent.contracts.tools import ToolContract, ToolResult
from minimal_agent.runtime.tool_registry import ToolDefinition


class EchoArguments(ProtocolModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1)


ECHO_CONTRACT = ToolContract(
    name="echo",
    version="test-echo-v1",
    description="Return the supplied text.",
    arguments_model=EchoArguments,
    tool_type="read",
    parameter_rules={"text": "NONEMPTY_STRING"},
    permission_requirements=("REGISTERED_TOOL_AND_RUN_ALLOW_LIST",),
    requires_confirmation=False,
    risk_level="low",
    idempotency_rules={"mode": "NOT_APPLICABLE"},
    side_effects=(),
    result_contracts={
        "OK": {
            "terminal_status": "success",
            "data_schema": {
                "additionalProperties": False,
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "type": "object",
            },
        }
    },
    empty_result_behavior="UNSUPPORTED",
    partial_success_behavior="UNSUPPORTED",
    trace_event_types=(),
)


def echo(text: str) -> ToolResult:
    return ToolResult(
        success=True,
        code="OK",
        message="echoed",
        data={"text": text},
    )


def echo_definition() -> ToolDefinition:
    return ToolDefinition(contract=ECHO_CONTRACT, handler=echo)

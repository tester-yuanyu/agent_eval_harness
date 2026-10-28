"""Pydantic protocols shared across the minimal Agent boundary."""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProtocolModel(BaseModel):
    """Base class that rejects undeclared protocol fields."""

    model_config = ConfigDict(extra="forbid")


class IntentResult(ProtocolModel):
    """Observable result produced by the future intent router."""

    intent: Literal[
        "query_information",
        "prepare_resource",
        "query_user",
        "query_gift",
        "add_backpack_gift",
        "query_pool",
        "unsupported",
    ]
    status: Literal[
        "READY",
        "NEED_CLARIFICATION",
        "NEED_CONFIRMATION",
        "REJECTED",
    ]
    next_action: Literal[
        "CALL_TOOL",
        "ASK_USER",
        "ASK_CONFIRMATION",
        "REJECT",
    ]
    parameters: dict[str, Any] = Field(default_factory=dict)
    missing_parameters: list[str] = Field(default_factory=list)
    reason: str

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        """Enforce the finite-state combinations in the public protocol."""

        expected_actions = {
            "READY": "CALL_TOOL",
            "NEED_CLARIFICATION": "ASK_USER",
            "NEED_CONFIRMATION": "ASK_CONFIRMATION",
            "REJECTED": "REJECT",
        }
        expected_action = expected_actions[self.status]
        if self.next_action != expected_action:
            raise ValueError(
                f"status {self.status!r} requires next_action {expected_action!r}"
            )

        if self.status == "NEED_CLARIFICATION" and not self.missing_parameters:
            raise ValueError(
                "NEED_CLARIFICATION requires at least one missing parameter"
            )

        if self.status == "READY" and self.missing_parameters:
            raise ValueError("READY requires an empty missing_parameters list")

        if self.status == "NEED_CONFIRMATION" and self.missing_parameters:
            raise ValueError(
                "NEED_CONFIRMATION requires an empty missing_parameters list"
            )

        return self


class ToolCallRecord(ProtocolModel):
    """Observable terminal record for one tool call."""

    call_id: str
    name: str
    arguments: dict[str, Any]
    status: Literal["SUCCESS", "FAILED", "TIMEOUT"]
    output: dict[str, Any] | None
    error: str | None
    duration_ms: int = Field(ge=0)


class AgentResult(ProtocolModel):
    """Stable result boundary exposed to the future evaluation framework."""

    run_id: str
    trace_id: str | None = None
    status: Literal[
        "SUCCESS",
        "NEED_CLARIFICATION",
        "NEED_CONFIRMATION",
        "REJECTED",
        "FAILED",
        "MAX_STEPS_EXCEEDED",
    ]
    intent_result: IntentResult
    tool_calls: list[ToolCallRecord]
    final_response: str
    events: list[dict[str, Any]]


class CliErrorResult(ProtocolModel):
    """Structured terminal error emitted by the CLI boundary."""

    status: Literal["ERROR"] = "ERROR"
    error_type: str = Field(min_length=1)
    message: str = Field(min_length=1)


class FunctionCallItem(ProtocolModel):
    """One function call requested by a scripted model step."""

    type: Literal["function_call"]
    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any]


class FinalResponseItem(ProtocolModel):
    """One terminal response produced by a scripted model step."""

    type: Literal["message"]
    content: str = Field(min_length=1)


class FunctionCallOutput(ProtocolModel):
    """Observable tool output passed into the next model step."""

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    output: dict[str, Any]


class ToolLoopRequest(ProtocolModel):
    """Complete observable input for one scripted tool-loop model request."""

    user_input: str
    intent_result: IntentResult
    tool_schemas: list[dict[str, Any]]
    tool_outputs: list[FunctionCallOutput]
    step: int = Field(ge=1)

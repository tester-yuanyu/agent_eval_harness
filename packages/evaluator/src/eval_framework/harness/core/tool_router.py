"""Domain-independent schema validation and native Inspect tool dispatch."""

from copy import deepcopy
from typing import Any
from uuid import uuid4

from inspect_ai.log import transcript
from inspect_ai.model import ChatMessageAssistant, ChatMessageTool, execute_tools
from inspect_ai.tool import ToolCall, ToolDef, ToolError, ToolInfo, ToolParams

from ...environments.base.protocol import (
    Environment as Environment,
)
from ...environments.base.protocol import (
    EnvironmentFailure as EnvironmentFailure,
)
from ...environments.base.protocol import (
    ToolExecutionError as ToolExecutionError,
)
from ..tool_validation import Rejection as Rejection
from ..tool_validation import ToolSchemaValidator


def business_info(kind: str, **data: Any) -> None:
    transcript().info({"kind": kind, **data}, source="harness.v1")
    from ..trace.evidence_checkpoint import checkpoint_business_event

    checkpoint_business_event()


class ToolRouter(ToolSchemaValidator):
    def __init__(self, schemas: list[dict[str, Any]]) -> None:
        normalized = []
        for original in schemas:
            schema = deepcopy(original)
            parameters = schema["parameters"]
            if parameters.get("type") != "object" or set(parameters) - {
                "type",
                "properties",
                "required",
                "additionalProperties",
                "description",
            }:
                raise ValueError("tool schema has unsupported top-level constraints")
            # JSON Schema allows additional properties unless explicitly denied;
            # Inspect's ToolParams defaults to False. Normalize that difference.
            parameters.setdefault("properties", {})
            parameters.setdefault("required", [])
            parameters.setdefault("additionalProperties", True)
            # ToolParams has no root description (the tool itself has one).
            parameters.pop("description", None)
            projected = ToolInfo.model_validate(schema).parameters.model_dump(
                mode="json",
                exclude_unset=True,
            )
            if projected != parameters:
                raise ValueError(
                    "tool schema contains constraints Inspect cannot preserve"
                )
            normalized.append(schema)
        super().__init__(normalized)

    def tool_infos(self) -> list[ToolInfo]:
        return [ToolInfo.model_validate(schema) for schema in self.schemas.values()]

    def validate(self, call: ToolCall) -> Rejection | None:
        return super().validate(
            call.function, call.arguments, parse_error=call.parse_error
        )

    async def dispatch(
        self,
        call: ToolCall,
        environment: Environment,
        *,
        turn: int,
    ) -> list[ChatMessageTool]:
        rejection = self.validate(call)
        before = await environment.snapshot()
        started = False
        route_id = uuid4().hex
        business_info(
            "route_start",
            route_id=route_id,
            call_id=call.id,
            turn=turn,
            before=before,
            validation_code=rejection.code if rejection else None,
            schema=self.schemas.get(call.function, {}).get("parameters"),
        )

        async def invoke(**arguments: Any) -> str:
            nonlocal started
            if rejection:
                raise ToolError(f"{rejection.code}: {rejection.message}")
            started = True
            try:
                return await environment.step(call.function, deepcopy(arguments))
            except ToolExecutionError as exc:
                raise ToolError(f"execution_error: {exc}") from exc
            except Exception as exc:
                # Preserve cancellation and native limits; infrastructure errors
                # must bypass Inspect's recoverable OSError mappings.
                from inspect_ai.util import LimitExceededError

                if isinstance(exc, LimitExceededError):
                    raise
                raise EnvironmentFailure(str(exc)) from exc

        definition = ToolDef(
            invoke,
            name=call.function,
            description="Validated environment operation",
            # The original JSON Schema was checked above. A permissive envelope
            # prevents upstream coercion from changing the validated arguments.
            parameters=ToolParams(additionalProperties=True),
            parallel=False,
        )
        try:
            result = await execute_tools(
                [ChatMessageAssistant(content="", tool_calls=[call])], [definition]
            )
            return [m for m in result.messages if isinstance(m, ChatMessageTool)]
        finally:
            import anyio

            with anyio.CancelScope(shield=True):
                business_info(
                    "route_end",
                    route_id=route_id,
                    call_id=call.id,
                    turn=turn,
                    after=await environment.snapshot(),
                    execution_started=started,
                )

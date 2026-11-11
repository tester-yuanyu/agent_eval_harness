"""Parse and validate public tool calls before an environment observes them."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from ..environments.file_tools.schemas import TOOLS, file_tool_schemas
from .tool_validation import ToolSchemaValidator


class InvalidToolCall(ValueError):
    """A supplied tool name, arguments or domain operation is invalid."""


class ToolRouter:
    """同步兼容入口；校验环境 Schema，保留 InvalidToolCall 错误语义。"""

    def __init__(
        self, environment: Any = None, *, allowed_tools: list[str] | None = None
    ) -> None:
        self.environment = environment
        schemas = (
            environment.tool_schemas()
            if callable(getattr(environment, "tool_schemas", None))
            else file_tool_schemas([tool[0] for tool in TOOLS])
        )
        available = {schema["name"] for schema in schemas}
        self.allowed_tools = frozenset(
            available if allowed_tools is None else allowed_tools
        )
        if not self.allowed_tools or not self.allowed_tools <= available:
            raise ValueError("unsupported allowed tools")
        self._validation = ToolSchemaValidator(
            [schema for schema in schemas if schema["name"] in self.allowed_tools]
        )

    def parse(self, raw: str | dict[str, Any]) -> dict[str, Any]:
        try:
            action = json.loads(raw) if isinstance(raw, str) else deepcopy(raw)
        except ValueError as exc:
            raise InvalidToolCall("tool call must contain valid JSON") from exc
        if not isinstance(action, dict) or set(action) != {"name", "arguments"}:
            raise InvalidToolCall("tool call requires name and arguments")
        if (
            not isinstance(action["name"], str)
            or action["name"] not in self.allowed_tools
        ):
            raise InvalidToolCall("tool is not allowed")
        errors = self.validate_args(action)
        if errors:
            raise InvalidToolCall("; ".join(errors))
        return action

    def validate_args(self, call: dict[str, Any]) -> list[str]:
        if not isinstance(call, dict) or set(call) != {"name", "arguments"}:
            return ["tool call requires name and arguments"]
        tool_name, arguments = call["name"], call["arguments"]
        if not isinstance(tool_name, str) or tool_name not in self.allowed_tools:
            return ["tool is not allowed"]
        if self._validation.validate(tool_name, arguments):
            return ["invalid tool arguments"]
        return []

    def dispatch(self, call: dict[str, Any], env: Any = None) -> Any:
        environment = self.environment if env is None else env
        if environment is None:
            raise ValueError("tool dispatch requires an environment")
        action = self.parse(call)
        try:
            return environment.step(action)
        except ValueError as exc:
            # The deterministic file environment reports invalid paths and edit
            # preconditions as ValueError. Unexpected router failures retain
            # their original exception and are classified as Harness faults.
            raise InvalidToolCall(str(exc)) from exc

"""Registration, validation, and execution for explicitly configured Tools."""

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from minimal_agent.contracts.tools import ToolContract, ToolResult

ToolHandler = Callable[..., ToolResult]


class ToolRegistryError(RuntimeError):
    """Base class for explicit Tool registry failures."""


class ToolNotAvailableError(ToolRegistryError):
    """Raised when a requested Tool is not registered."""

    code = "TOOL_NOT_AVAILABLE"


class DuplicateToolError(ToolRegistryError):
    """Raised when a Tool name is registered more than once."""


class InvalidToolArgumentsError(ToolRegistryError):
    """Raised when Tool arguments violate its strict contract."""


class InvalidToolResultError(ToolRegistryError):
    """Raised when a Tool handler violates the result protocol."""


class ToolNotAllowedError(ToolRegistryError):
    """Raised when run-scoped policy excludes a registered Tool."""

    code = "TOOL_NOT_ALLOWED"


class ToolDefinition:
    """One executable handler bound to immutable Tool metadata."""

    def __init__(self, *, contract: ToolContract, handler: ToolHandler) -> None:
        self.contract = contract
        self.handler = handler

    @property
    def name(self) -> str:
        return self.contract.name

    @property
    def description(self) -> str:
        return self.contract.description

    @property
    def arguments_model(self):
        return self.contract.arguments_model

    def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            validated = self.arguments_model.model_validate(arguments)
        except ValidationError as exc:
            raise InvalidToolArgumentsError(
                f"invalid arguments for tool {self.name!r}"
            ) from exc
        result = self.handler(**validated.model_dump())
        if not isinstance(result, ToolResult):
            raise InvalidToolResultError(
                f"tool {self.name!r} returned {type(result).__name__}, "
                "expected ToolResult"
            )
        return result

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.arguments_model.model_json_schema(),
            "strict": True,
        }


class ToolRegistry:
    """Stable ordered collection of explicitly registered Tools."""

    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._definitions.values())

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise DuplicateToolError(f"tool {definition.name!r} is already registered")
        self._definitions[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise ToolNotAvailableError(
                f"TOOL_NOT_AVAILABLE: tool {name!r} is not registered"
            ) from exc

    def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        allowed_tools: frozenset[str] | None = None,
    ) -> ToolResult:
        if allowed_tools is not None and name not in allowed_tools:
            raise ToolNotAllowedError(f"TOOL_NOT_ALLOWED: tool {name!r}")
        return self.get(name).invoke(arguments)

    def schemas(
        self, *, allowed_tools: frozenset[str] | None = None
    ) -> list[dict[str, Any]]:
        return [
            definition.schema()
            for definition in self.definitions
            if allowed_tools is None or definition.name in allowed_tools
        ]

    def metadata(
        self, *, allowed_tools: frozenset[str] | None = None
    ) -> dict[str, Any]:
        return {
            "tool_names": [
                definition.name
                for definition in self.definitions
                if allowed_tools is None or definition.name in allowed_tools
            ]
        }

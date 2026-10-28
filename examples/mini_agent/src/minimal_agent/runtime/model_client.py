"""Model boundary and explicit failures for intent classification."""

from typing import Any, Protocol, runtime_checkable

from minimal_agent.contracts.agent import ToolLoopRequest


class IntentModuleError(RuntimeError):
    """Base class for failures exposed by the intent module."""


class ModelInvocationError(IntentModuleError):
    """Raised when a model client cannot produce an intent response."""


class ModelTimeoutError(ModelInvocationError):
    """Raised when a model API request exceeds its configured timeout."""


class InvalidModelOutputError(IntentModuleError):
    """Raised when a model response violates the IntentResult protocol."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic or {}


class ScriptExhaustedError(ModelInvocationError):
    """Raised when a scripted client has no response left to return."""


@runtime_checkable
class ModelClient(Protocol):
    """Minimal model interface required by the intent router."""

    def classify_intent(self, user_input: str) -> object:
        """Return candidate data for an IntentResult."""

        ...

    def next_tool_step(self, request: ToolLoopRequest) -> object:
        """Return a function call or final response for one tool-loop step."""

        ...

"""Intent-only execution that never invokes tools."""

from pydantic import ValidationError

from minimal_agent.contracts.agent import IntentResult
from minimal_agent.contracts.intents import (
    IntentRegistry,
    build_default_intent_registry,
)
from minimal_agent.runtime.model_client import (
    IntentModuleError,
    InvalidModelOutputError,
    ModelClient,
    ModelInvocationError,
)
from minimal_agent.runtime.trace import TraceCollector


class IntentRouter:
    """Turn one model response into a validated IntentResult."""

    def __init__(
        self,
        model_client: ModelClient,
        intent_registry: IntentRegistry | None = None,
    ) -> None:
        self._model_client = model_client
        self._intent_registry = intent_registry or build_default_intent_registry()

    def run_intent_only(
        self,
        user_input: str,
        *,
        trace: TraceCollector | None = None,
        record_request: bool = True,
    ) -> IntentResult:
        """Classify input and validate the response without executing a tool."""

        if trace is not None and record_request:
            trace.record("intent_requested", {})
        try:
            candidate = self._model_client.classify_intent(user_input)
        except IntentModuleError:
            raise
        except Exception as exc:
            raise ModelInvocationError("intent model invocation failed") from exc

        try:
            if isinstance(candidate, str):
                parsed = IntentResult.model_validate_json(candidate)
            else:
                parsed = IntentResult.model_validate(candidate)
        except (ValidationError, ValueError, TypeError) as exc:
            raise InvalidModelOutputError(
                "model returned an invalid IntentResult"
            ) from exc
        if trace is not None:
            trace.record(
                "intent_candidate_received",
                {
                    "intent": parsed.intent,
                    "status": parsed.status,
                    "next_action": parsed.next_action,
                },
            )
        return self._intent_registry.validate(user_input, parsed, trace=trace)


def run_intent_only(user_input: str, model_client: ModelClient) -> IntentResult:
    """Convenience entry point for module-level intent evaluation."""

    return IntentRouter(model_client).run_intent_only(user_input)

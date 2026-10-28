"""OpenAI Responses API adapter for intent and function-calling steps."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn, Protocol

from openai import APIError, APITimeoutError, OpenAI

from minimal_agent.contracts.agent import IntentResult, ToolLoopRequest
from minimal_agent.runtime.config import load_config
from minimal_agent.runtime.model_client import (
    InvalidModelOutputError,
    ModelInvocationError,
    ModelTimeoutError,
)
from minimal_agent.runtime.prompts import (
    INTENT_INSTRUCTIONS,
    INTENT_PROMPT_VERSION,
    TOOL_INSTRUCTIONS,
    TOOL_PROMPT_VERSION,
)


class OpenAIClientConfigurationError(RuntimeError):
    """Raised when required OpenAI environment configuration is absent."""


class ResponsesResource(Protocol):
    """Subset of the SDK Responses resource used by this adapter."""

    def parse(self, **kwargs: Any) -> Any:
        """Create and parse a structured response."""

        ...

    def create(self, **kwargs: Any) -> Any:
        """Create a function-calling response."""

        ...


class OpenAIClientLike(Protocol):
    """Injectable SDK client boundary for offline tests."""

    responses: ResponsesResource


OpenAIFactory = Callable[..., OpenAIClientLike]


class OpenAIModelClient:
    """Translate the project's ModelClient protocol to Responses API calls."""

    def __init__(
        self,
        client: OpenAIClientLike,
        *,
        model: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not model.strip():
            raise OpenAIClientConfigurationError("OPENAI_MODEL must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        self._client = client
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._previous_response_id: str | None = None
        self._submitted_call_ids: set[str] = set()

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = None,
        timeout_seconds: float = 30.0,
        client_factory: OpenAIFactory = OpenAI,
    ) -> "OpenAIModelClient":
        """Create a client using only OPENAI_API_KEY and OPENAI_MODEL."""

        config = load_config(env_file)
        if config.openai_api_key is None:
            raise OpenAIClientConfigurationError("OPENAI_API_KEY is required")
        if config.openai_model is None or not config.openai_model.strip():
            raise OpenAIClientConfigurationError("OPENAI_MODEL is required")

        sdk_client = client_factory(
            api_key=config.openai_api_key.get_secret_value(),
            timeout=timeout_seconds,
            max_retries=0,
        )
        return cls(
            sdk_client,
            model=config.openai_model,
            timeout_seconds=timeout_seconds,
        )

    def metadata(self) -> dict[str, str]:
        """Return model and prompt versions without secrets."""

        return {
            "model_client": "openai_responses",
            "model": self._model,
            "intent_prompt_version": INTENT_PROMPT_VERSION,
            "tool_prompt_version": TOOL_PROMPT_VERSION,
        }

    def classify_intent(self, user_input: str) -> object:
        """Request a strict Pydantic IntentResult from Responses API."""

        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=INTENT_INSTRUCTIONS,
                input=user_input,
                text_format=IntentResult,
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            self._raise_api_error(exc, operation="intent classification")

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise InvalidModelOutputError(
                "OpenAI response did not contain a parsed IntentResult"
            )
        return parsed

    def next_tool_step(self, request: ToolLoopRequest) -> object:
        """Request one function call or a final text message."""

        if request.step == 1:
            self._previous_response_id = None
            self._submitted_call_ids.clear()
            response_input: str | list[dict[str, Any]] = self._initial_input(request)
            previous_response_id = None
            tool_choice = "required"
            new_call_ids: set[str] = set()
        else:
            if self._previous_response_id is None:
                raise ModelInvocationError(
                    "OpenAI tool continuation has no previous response ID"
                )
            pending_outputs = [
                output
                for output in request.tool_outputs
                if output.call_id not in self._submitted_call_ids
            ]
            if not pending_outputs:
                raise ModelInvocationError(
                    "OpenAI tool continuation has no new function output"
                )
            response_input = [
                {
                    "type": "function_call_output",
                    "call_id": output.call_id,
                    "output": json.dumps(
                        output.output,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
                for output in pending_outputs
            ]
            previous_response_id = self._previous_response_id
            tool_choice = "auto"
            new_call_ids = {output.call_id for output in pending_outputs}

        request_kwargs: dict[str, Any] = {
            "model": self._model,
            "instructions": TOOL_INSTRUCTIONS,
            "input": response_input,
            "tools": request.tool_schemas,
            "tool_choice": tool_choice,
            "parallel_tool_calls": False,
            "timeout": self._timeout_seconds,
        }
        if previous_response_id is not None:
            request_kwargs["previous_response_id"] = previous_response_id

        try:
            response = self._client.responses.create(**request_kwargs)
        except Exception as exc:
            self._raise_api_error(exc, operation="tool-loop response")

        response_id = getattr(response, "id", None)
        if not isinstance(response_id, str) or not response_id:
            raise InvalidModelOutputError("OpenAI response is missing its response ID")
        self._previous_response_id = response_id
        self._submitted_call_ids.update(new_call_ids)

        function_calls = [
            item
            for item in getattr(response, "output", [])
            if self._item_value(item, "type") == "function_call"
        ]
        if len(function_calls) > 1:
            raise InvalidModelOutputError(
                "OpenAI returned multiple function calls with parallel calls disabled"
            )
        if function_calls:
            return self._parse_function_call(function_calls[0])

        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return {"type": "message", "content": output_text.strip()}
        raise InvalidModelOutputError(
            "OpenAI response contained neither a function call nor final text"
        )

    @staticmethod
    def _initial_input(request: ToolLoopRequest) -> str:
        intent_json = request.intent_result.model_dump_json()
        return (
            f"User request:\n{request.user_input}\n\n"
            f"Validated intent:\n{intent_json}"
        )

    @classmethod
    def _parse_function_call(cls, item: object) -> dict[str, Any]:
        call_id = cls._item_value(item, "call_id")
        name = cls._item_value(item, "name")
        arguments_json = cls._item_value(item, "arguments")
        if not isinstance(call_id, str) or not call_id:
            raise InvalidModelOutputError("function call is missing call_id")
        if not isinstance(name, str) or not name:
            raise InvalidModelOutputError("function call is missing name")
        if not isinstance(arguments_json, str):
            raise InvalidModelOutputError("function call arguments must be JSON text")
        try:
            arguments = json.loads(arguments_json)
        except json.JSONDecodeError as exc:
            raise InvalidModelOutputError(
                "function call arguments are not valid JSON"
            ) from exc
        if not isinstance(arguments, dict):
            raise InvalidModelOutputError(
                "function call arguments must decode to an object"
            )
        return {
            "type": "function_call",
            "call_id": call_id,
            "name": name,
            "arguments": arguments,
        }

    @staticmethod
    def _item_value(item: object, name: str) -> object:
        if isinstance(item, dict):
            return item.get(name)
        return getattr(item, name, None)

    @staticmethod
    def _raise_api_error(error: Exception, *, operation: str) -> NoReturn:
        if isinstance(error, (APITimeoutError, TimeoutError)):
            raise ModelTimeoutError(f"OpenAI {operation} timed out") from error
        if isinstance(error, APIError):
            raise ModelInvocationError(f"OpenAI {operation} failed") from error
        raise ModelInvocationError(f"OpenAI {operation} failed") from error

"""DeepSeek Responses API adapter for intent and function-calling steps."""

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn, Protocol

from openai import APIError, APITimeoutError, OpenAI
from pydantic import ValidationError

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

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
INTENT_SCHEMA_VERSION = "intent-result-v1"
MAX_DIAGNOSTIC_OUTPUT_CHARS = 10_000


def _redact_model_output(value: str) -> str:
    truncated = value[:MAX_DIAGNOSTIC_OUTPUT_CHARS]
    return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", truncated)


def _redact_diagnostic(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_model_output(value)
    if isinstance(value, list):
        return [_redact_diagnostic(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_diagnostic(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_diagnostic(item) for key, item in value.items()}
    return value


def _intent_schema_sha256() -> str:
    encoded = json.dumps(
        IntentResult.model_json_schema(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DeepSeekClientConfigurationError(RuntimeError):
    """Raised when required DeepSeek environment configuration is absent."""


class ResponsesResource(Protocol):
    """Subset of the SDK Responses resource used by this adapter."""

    def create(self, **kwargs: Any) -> Any:
        """Create a Responses API result."""

        ...


class DeepSeekClientLike(Protocol):
    """Injectable SDK client boundary for offline tests."""

    responses: ResponsesResource


DeepSeekFactory = Callable[..., DeepSeekClientLike]


class DeepSeekModelClient:
    """Translate ModelClient calls to DeepSeek's stateless Responses API."""

    def __init__(
        self,
        client: DeepSeekClientLike,
        *,
        model: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not model.strip():
            raise DeepSeekClientConfigurationError(
                "DEEPSEEK_MODEL must not be empty"
            )
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        self._client = client
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._history: list[dict[str, Any]] = []
        self._submitted_call_ids: set[str] = set()

    @classmethod
    def from_env(
        cls,
        *,
        env_file: str | Path | None = None,
        timeout_seconds: float = 30.0,
        client_factory: DeepSeekFactory = OpenAI,
    ) -> "DeepSeekModelClient":
        """Create a client from explicit DeepSeek environment variables."""

        config = load_config(env_file)
        if config.deepseek_api_key is None:
            raise DeepSeekClientConfigurationError("DEEPSEEK_API_KEY is required")
        if config.deepseek_model is None or not config.deepseek_model.strip():
            raise DeepSeekClientConfigurationError("DEEPSEEK_MODEL is required")

        sdk_client = client_factory(
            api_key=config.deepseek_api_key.get_secret_value(),
            base_url=DEEPSEEK_BASE_URL,
            timeout=timeout_seconds,
            max_retries=0,
        )
        return cls(
            sdk_client,
            model=config.deepseek_model,
            timeout_seconds=timeout_seconds,
        )

    def metadata(self) -> dict[str, str]:
        """Return model and prompt versions without credentials."""

        return {
            "model_client": "deepseek_responses",
            "model": self._model,
            "intent_prompt_version": INTENT_PROMPT_VERSION,
            "tool_prompt_version": TOOL_PROMPT_VERSION,
            "structured_output_mode": "json_object+pydantic",
        }

    def classify_intent(self, user_input: str) -> object:
        """Request JSON Schema output and validate it as IntentResult."""

        try:
            response = self._client.responses.create(
                model=self._model,
                instructions=self._intent_instructions(),
                input=user_input,
                text={"format": {"type": "json_object"}},
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            self._raise_api_error(exc, operation="intent classification")

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise InvalidModelOutputError(
                "DeepSeek response did not contain an IntentResult"
            )
        try:
            return IntentResult.model_validate_json(output_text)
        except (ValidationError, ValueError) as exc:
            validation_errors = (
                exc.errors(include_url=False)
                if isinstance(exc, ValidationError)
                else [{"type": type(exc).__name__, "message": str(exc)}]
            )
            raise InvalidModelOutputError(
                "DeepSeek response is not a valid IntentResult",
                diagnostic={
                    "provider": "deepseek",
                    "model": self._model,
                    "raw_output_redacted": _redact_model_output(output_text),
                    "raw_output_truncated": len(output_text)
                    > MAX_DIAGNOSTIC_OUTPUT_CHARS,
                    "validation_errors": _redact_diagnostic(validation_errors),
                    "prompt_version": INTENT_PROMPT_VERSION,
                    "schema_version": INTENT_SCHEMA_VERSION,
                    "schema_sha256": _intent_schema_sha256(),
                },
            ) from exc

    def next_tool_step(self, request: ToolLoopRequest) -> object:
        """Request one tool call or final message with full history replay."""

        if request.step == 1:
            self._history = [
                {"role": "user", "content": self._initial_input(request)}
            ]
            self._submitted_call_ids.clear()
            tool_choice = "required"
            new_call_ids: set[str] = set()
        else:
            pending_outputs = [
                output
                for output in request.tool_outputs
                if output.call_id not in self._submitted_call_ids
            ]
            if not self._history:
                raise ModelInvocationError(
                    "DeepSeek tool continuation has no conversation history"
                )
            if not pending_outputs:
                raise ModelInvocationError(
                    "DeepSeek tool continuation has no new function output"
                )
            self._history.extend(
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
            )
            tool_choice = "auto"
            new_call_ids = {output.call_id for output in pending_outputs}

        try:
            response = self._client.responses.create(
                model=self._model,
                instructions=TOOL_INSTRUCTIONS,
                input=list(self._history),
                tools=request.tool_schemas,
                tool_choice=tool_choice,
                parallel_tool_calls=False,
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            self._raise_api_error(exc, operation="tool-loop response")

        output_items = [
            self._serialize_item(item) for item in getattr(response, "output", [])
        ]
        self._history.extend(output_items)
        self._submitted_call_ids.update(new_call_ids)

        function_calls = [
            item for item in output_items if item.get("type") == "function_call"
        ]
        if len(function_calls) > 1:
            raise InvalidModelOutputError(
                "DeepSeek returned multiple function calls with parallel calls disabled"
            )
        if function_calls:
            return self._parse_function_call(function_calls[0])

        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return {"type": "message", "content": output_text.strip()}
        raise InvalidModelOutputError(
            "DeepSeek response contained neither a function call nor final text"
        )

    @staticmethod
    def _initial_input(request: ToolLoopRequest) -> str:
        return (
            f"User request:\n{request.user_input}\n\n"
            f"Validated intent:\n{request.intent_result.model_dump_json()}"
        )

    @staticmethod
    def _intent_instructions() -> str:
        """Describe the protocol while using DeepSeek's JSON object mode."""

        schema_json = json.dumps(
            IntentResult.model_json_schema(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return (
            f"{INTENT_INSTRUCTIONS}\n"
            "Return only one valid JSON object matching this JSON Schema "
            f"exactly:\n{schema_json}"
        )

    @staticmethod
    def _serialize_item(item: object) -> dict[str, Any]:
        if isinstance(item, dict):
            return dict(item)
        model_dump = getattr(item, "model_dump", None)
        if callable(model_dump):
            value = model_dump(mode="json", exclude_none=True)
            if isinstance(value, dict):
                return value
        raise InvalidModelOutputError(
            "DeepSeek response contained an invalid output item"
        )

    @staticmethod
    def _parse_function_call(item: dict[str, Any]) -> dict[str, Any]:
        call_id = item.get("call_id")
        name = item.get("name")
        arguments_json = item.get("arguments")
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
    def _raise_api_error(error: Exception, *, operation: str) -> NoReturn:
        if isinstance(error, (APITimeoutError, TimeoutError)):
            raise ModelTimeoutError(f"DeepSeek {operation} timed out") from error
        if isinstance(error, APIError):
            raise ModelInvocationError(f"DeepSeek {operation} failed") from error
        raise ModelInvocationError(f"DeepSeek {operation} failed") from error

"""Generic Agent orchestration and bounded Tool-calling loop."""

from collections.abc import Callable
from copy import deepcopy
from time import monotonic
from uuid import uuid4

from agent_trace_sdk import TraceContext
from pydantic import TypeAdapter, ValidationError

from minimal_agent.contracts.agent import (
    AgentResult,
    FinalResponseItem,
    FunctionCallItem,
    FunctionCallOutput,
    IntentResult,
    ToolCallRecord,
    ToolLoopRequest,
)
from minimal_agent.runtime.intent_router import IntentRouter
from minimal_agent.runtime.model_client import ModelClient
from minimal_agent.runtime.tool_registry import ToolRegistry
from minimal_agent.runtime.trace import TraceCollector

ModelStep = FunctionCallItem | FinalResponseItem
MODEL_STEP_ADAPTER = TypeAdapter(ModelStep)


def _new_run_id() -> str:
    return f"run_{uuid4().hex}"


class MinimalAgent:
    """Small observable Agent with no built-in business Tools."""

    def __init__(
        self,
        model_client: ModelClient,
        tool_registry: ToolRegistry,
        *,
        max_steps: int = 4,
        run_id_factory: Callable[[], str] = _new_run_id,
        evidence_sink=None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self._model_client = model_client
        self._intent_router = IntentRouter(model_client)
        self._tool_registry = tool_registry
        self._max_steps = max_steps
        self._run_id_factory = run_id_factory
        self._last_intent_trace: list[dict[str, object]] = []
        self._evidence_sink = evidence_sink

    def run_intent_only(
        self, user_input: str, *, trace_context: TraceContext | None = None
    ) -> IntentResult:
        trace = self._new_trace(trace_context=trace_context)
        try:
            return self._intent_router.run_intent_only(user_input, trace=trace)
        finally:
            self._last_intent_trace = trace.export()

    def intent_trace_snapshot(self) -> list[dict[str, object]]:
        return deepcopy(self._last_intent_trace)

    def _new_trace(self, *, trace_context=None, session_id=None):
        context = trace_context
        if self._evidence_sink is not None and context is None:
            context = self._evidence_sink.context
        return TraceCollector(
            self._run_id_factory(),
            session_id=session_id,
            sink=self._evidence_sink,
            context=context,
        )

    def run(
        self,
        user_input: str,
        *,
        session_id: str | None = None,
        allowed_tools: frozenset[str] | None = None,
        trace_context: TraceContext | None = None,
    ) -> AgentResult:
        if session_id is not None and not session_id.strip():
            raise ValueError("session_id must not be empty")
        trace = self._new_trace(trace_context=trace_context, session_id=session_id)
        trace.record(
            "run_started",
            {
                "user_input": user_input,
                "model": self._model_metadata(),
                "tools": self._tool_registry.metadata(allowed_tools=allowed_tools),
            },
        )
        trace.record("intent_requested", {"user_input": user_input})
        intent_result = self._intent_router.run_intent_only(
            user_input,
            trace=trace,
            record_request=False,
        )

        if intent_result.status == "NEED_CLARIFICATION":
            trace.record(
                "clarification_returned",
                {
                    "missing_parameters": intent_result.missing_parameters,
                    "response": intent_result.reason,
                },
            )
            return self._finish(
                trace=trace,
                status="NEED_CLARIFICATION",
                intent_result=intent_result,
                tool_calls=[],
                final_response=intent_result.reason,
            )
        if intent_result.status == "NEED_CONFIRMATION":
            trace.record("confirmation_required", {"response": intent_result.reason})
            return self._finish(
                trace=trace,
                status="NEED_CONFIRMATION",
                intent_result=intent_result,
                tool_calls=[],
                final_response=intent_result.reason,
            )
        if intent_result.status == "REJECTED":
            trace.record("request_rejected", {"response": intent_result.reason})
            return self._finish(
                trace=trace,
                status="REJECTED",
                intent_result=intent_result,
                tool_calls=[],
                final_response=intent_result.reason,
            )
        return self._run_tool_loop(
            user_input=user_input,
            intent_result=intent_result,
            trace=trace,
            allowed_tools=allowed_tools,
        )

    def _run_tool_loop(
        self,
        *,
        user_input: str,
        intent_result: IntentResult,
        trace: TraceCollector,
        allowed_tools: frozenset[str] | None,
    ) -> AgentResult:
        tool_calls: list[ToolCallRecord] = []
        tool_outputs: list[FunctionCallOutput] = []
        for step in range(1, self._max_steps + 1):
            request = ToolLoopRequest(
                user_input=user_input,
                intent_result=intent_result,
                tool_schemas=self._tool_registry.schemas(allowed_tools=allowed_tools),
                tool_outputs=tool_outputs,
                step=step,
            )
            try:
                model_step = self._validate_model_step(
                    self._model_client.next_tool_step(request)
                )
            except Exception as exc:
                trace.record(
                    "model_failed",
                    {"step": step, "error": self._error_message(exc)},
                )
                return self._finish(
                    trace=trace,
                    status="FAILED",
                    intent_result=intent_result,
                    tool_calls=tool_calls,
                    final_response=self._error_message(exc),
                )

            if isinstance(model_step, FinalResponseItem):
                trace.record(
                    "final_response_generated",
                    {"response": model_step.content, "step": step},
                )
                return self._finish(
                    trace=trace,
                    status="SUCCESS",
                    intent_result=intent_result,
                    tool_calls=tool_calls,
                    final_response=model_step.content,
                )

            failure = self._execute_tool_call(
                model_step=model_step,
                intent_result=intent_result,
                tool_calls=tool_calls,
                tool_outputs=tool_outputs,
                trace=trace,
                allowed_tools=allowed_tools,
            )
            if failure is not None:
                return failure

        trace.record("max_steps_exceeded", {"max_steps": self._max_steps})
        return self._finish(
            trace=trace,
            status="MAX_STEPS_EXCEEDED",
            intent_result=intent_result,
            tool_calls=tool_calls,
            final_response=f"maximum tool-loop steps exceeded: {self._max_steps}",
        )

    def _execute_tool_call(
        self,
        *,
        model_step: FunctionCallItem,
        intent_result: IntentResult,
        tool_calls: list[ToolCallRecord],
        tool_outputs: list[FunctionCallOutput],
        trace: TraceCollector,
        allowed_tools: frozenset[str] | None,
    ) -> AgentResult | None:
        trace.record(
            "tool_requested",
            {
                "call_id": model_step.call_id,
                "name": model_step.name,
                "arguments": model_step.arguments,
            },
        )
        trace.record(
            "tool_started",
            {"call_id": model_step.call_id, "name": model_step.name},
        )
        started_at = monotonic()
        try:
            result = self._tool_registry.invoke(
                model_step.name,
                model_step.arguments,
                allowed_tools=allowed_tools,
            )
        except Exception as exc:
            duration_ms = max(0, round((monotonic() - started_at) * 1000))
            is_timeout = isinstance(exc, TimeoutError)
            error = self._error_message(exc)
            tool_calls.append(
                ToolCallRecord(
                    call_id=model_step.call_id,
                    name=model_step.name,
                    arguments=model_step.arguments,
                    status="TIMEOUT" if is_timeout else "FAILED",
                    output=None,
                    error=error,
                    duration_ms=duration_ms,
                )
            )
            trace.record(
                "tool_timeout" if is_timeout else "tool_failed",
                {
                    "call_id": model_step.call_id,
                    "name": model_step.name,
                    "error": error,
                },
            )
            return self._finish(
                trace=trace,
                status="FAILED",
                intent_result=intent_result,
                tool_calls=tool_calls,
                final_response=error,
            )

        output = result.model_dump(mode="json")
        tool_calls.append(
            ToolCallRecord(
                call_id=model_step.call_id,
                name=model_step.name,
                arguments=model_step.arguments,
                status="SUCCESS",
                output=output,
                error=None,
                duration_ms=max(0, round((monotonic() - started_at) * 1000)),
            )
        )
        tool_outputs.append(
            FunctionCallOutput(
                call_id=model_step.call_id,
                name=model_step.name,
                output=output,
            )
        )
        trace.record(
            "tool_succeeded",
            {
                "call_id": model_step.call_id,
                "name": model_step.name,
                "output": output,
            },
        )
        return None

    def _model_metadata(self) -> dict[str, str]:
        provider = getattr(self._model_client, "metadata", None)
        if callable(provider):
            metadata = provider()
            if isinstance(metadata, dict):
                return {str(key): str(value) for key, value in metadata.items()}
        return {"model_client": type(self._model_client).__name__}

    @staticmethod
    def _validate_model_step(candidate: object) -> ModelStep:
        try:
            if isinstance(candidate, str):
                return MODEL_STEP_ADAPTER.validate_json(candidate)
            return MODEL_STEP_ADAPTER.validate_python(candidate)
        except (ValidationError, ValueError, TypeError) as exc:
            raise ValueError("model returned an invalid tool-loop step") from exc

    @staticmethod
    def _error_message(error: Exception) -> str:
        detail = str(error).strip()
        code = getattr(error, "code", None)
        if isinstance(code, str) and code and code not in detail:
            detail = f"{code}: {detail}" if detail else code
        return f"{type(error).__name__}: {detail}" if detail else type(error).__name__

    @staticmethod
    def _finish(
        *,
        trace: TraceCollector,
        status: str,
        intent_result: IntentResult,
        tool_calls: list[ToolCallRecord],
        final_response: str,
    ) -> AgentResult:
        trace.record("run_finished", {"status": status})
        return AgentResult.model_validate(
            {
                "run_id": trace.run_id,
                "status": status,
                "intent_result": intent_result,
                "tool_calls": tool_calls,
                "final_response": final_response,
                "events": trace.export(),
                "trace_id": trace.context.trace_id if trace.context else None,
            }
        )

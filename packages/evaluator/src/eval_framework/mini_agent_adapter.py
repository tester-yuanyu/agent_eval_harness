"""Oracle-free adapter over minimal-agent public interfaces."""

from __future__ import annotations

from agent_trace_sdk import TraceContext

from .provider import AdapterOutput
from .runtime_factory import Runtime
from .schemas import ExecutionSpec, TestScope


class MiniAgentAdapter:
    """Receives ExecutionSpec only; case IDs and oracles cannot cross this boundary."""

    def __init__(self, runtime: Runtime) -> None:
        self._runtime = runtime

    def run_module(self, execution: ExecutionSpec) -> AdapterOutput:
        result = self._runtime.agent.run_intent_only(execution.user_input)
        return AdapterOutput(
            result.model_dump(mode="json"),
            [],
            None,
            [],
            None,
            (
                self._runtime.agent.intent_trace_snapshot()
                if getattr(self._runtime, "evidence_sink", None) is None
                else None
            ),
        )

    def run_full(self, execution: ExecutionSpec, scope: TestScope) -> AdapterOutput:
        if scope not in {"link", "end_to_end"}:
            raise ValueError("run_full requires link or end_to_end scope")
        if scope == "link" and execution.user_responses:
            raise ValueError("link scope supports one Agent call, not user_responses")
        if execution.fault_injection:
            raise ValueError(
                "the current mini_agent native runtime does not support fault injection"
            )
        allowed = (
            frozenset(execution.allowed_tools)
            if execution.allowed_tools is not None
            else None
        )
        raw_turns, snapshots = [], []
        before = self._snapshot()
        after = before
        try:
            for text in [execution.user_input, *execution.user_responses]:
                if raw_turns and raw_turns[-1].status not in {
                    "NEED_CLARIFICATION",
                    "NEED_CONFIRMATION",
                }:
                    break
                result = self._run_turn(raw_turns, text, allowed)
                raw_turns.append(result)
                after = self._snapshot()
                if after is not None:
                    snapshots.append(after)
        except Exception as exc:
            # Retain completed turns and a fresh state read, including partial writes.
            try:
                after = self._snapshot()
            except Exception:
                after = None
            exc.__dict__["adapter_output"] = AdapterOutput(
                None,
                [turn.model_dump(mode="json") for turn in raw_turns],
                before,
                snapshots,
                after,
                execution_completed=False,
            )
            raise
        return AdapterOutput(
            None,
            [turn.model_dump(mode="json") for turn in raw_turns],
            before,
            snapshots,
            after,
        )

    def _snapshot(self):
        reader = getattr(self._runtime, "snapshot", None)
        return reader() if callable(reader) else None

    def _run_turn(self, raw_turns, user_input, allowed):
        try:
            sink = getattr(self._runtime, "evidence_sink", None)
            options = {}
            if sink is not None:
                options["trace_context"] = TraceContext(
                    sink.context.trace_id, len(raw_turns)
                )
            return self._runtime.agent.run(
                user_input,
                session_id=self._runtime.session_id,
                allowed_tools=allowed,
                **options,
            )
        except Exception as exc:
            exc.__dict__["adapter_output"] = AdapterOutput(
                None,
                [t.model_dump(mode="json") for t in raw_turns],
                None,
                [],
                None,
            )
            raise

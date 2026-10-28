"""Observable event collection without model reasoning or hidden state."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agent_trace_sdk import EventRule, TraceContext
from agent_trace_sdk import TraceCollector as SDKTraceCollector

from minimal_agent.contracts.agent import ProtocolModel

# Event semantics belong to the Agent adapter, not the generic collector.
EVENT_FIELDS = {
    "run_started": ("result", "user_input model tools"),
    "intent_requested": ("understanding", "user_input"),
    "intent_candidate_received": ("understanding", "intent status next_action"),
    "intent_definition_resolved": ("understanding", "intent contract_version"),
    "intent_parameter_normalized": (
        "understanding",
        "intent field normalizer before after",
    ),
    "intent_parameter_validation_failed": ("understanding", "intent fields error_type"),
    "intent_semantic_constraint_failed": (
        "understanding",
        "intent constraint missing_parameters reason",
    ),
    "intent_contract_validated": (
        "understanding",
        "intent contract_version valid invalid_fields",
    ),
    "intent_decided": ("understanding", "intent status next_action missing_parameters"),
    "clarification_returned": ("understanding", "missing_parameters response"),
    "confirmation_required": ("safety_recovery", "response"),
    "request_rejected": ("safety_recovery", "response"),
    "model_failed": ("safety_recovery", "step error"),
    "max_steps_exceeded": ("safety_recovery", "max_steps"),
    "tool_requested": ("planning_execution", "call_id name arguments"),
    "tool_started": ("planning_execution", "call_id name"),
    "tool_succeeded": ("planning_execution", "call_id name output"),
    "tool_failed": ("safety_recovery", "call_id name error"),
    "tool_timeout": ("safety_recovery", "call_id name error"),
    "final_response_generated": ("result", "response step"),
    "run_finished": ("result", "status"),
}
EVENT_RULES = {
    name: EventRule(
        layer,
        tuple(fields.split()),
        tuple(fields.split()),
        tuple(
            (key, str)
            for key in fields.split()
            if key in {"call_id", "name", "intent", "status", "next_action"}
        )
        + tuple(
            (key, dict) for key in fields.split() if key in {"arguments", "output"}
        ),
    )
    for name, (layer, fields) in EVENT_FIELDS.items()
}
# Direct module invocation intentionally omits raw user input.
EVENT_RULES["intent_requested"] = EventRule("understanding", ("user_input",))


class TraceEvent(ProtocolModel):
    """One observable execution event."""

    event_id: str
    run_id: str
    session_id: str | None = None
    event_type: str
    timestamp: str
    payload: dict[str, Any]


def _new_event_id() -> str:
    return f"event_{uuid4().hex}"


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class TraceCollector(SDKTraceCollector):
    """Append-only collection of observable events for one run."""

    def __init__(
        self,
        run_id: str,
        *,
        session_id: str | None = None,
        event_id_factory: Callable[[], str] = _new_event_id,
        timestamp_factory: Callable[[], str] = _utc_timestamp,
        sink=None,
        context: TraceContext | None = None,
    ) -> None:
        super().__init__(
            run_id,
            session_id=session_id,
            event_id_factory=event_id_factory,
            timestamp_factory=timestamp_factory,
            sink=sink,
            context=context,
            rules=EVENT_RULES,
        )

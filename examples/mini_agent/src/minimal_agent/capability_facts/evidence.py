"""Observable MiniAgent Evidence facts."""

from typing import Any

from capability_snapshot_kit.facts import EvidenceFactV3
from capability_snapshot_kit.models import CapabilityClaimV3
from minimal_agent.contracts.agent import IntentResult, ToolCallRecord
from minimal_agent.runtime.trace import EVENT_RULES


def _availability(
    evidence_id: str,
    status: str = "supported",
    reason: str | None = None,
) -> CapabilityClaimV3:
    return CapabilityClaimV3(
        capability_key=f"evidence.{evidence_id}_available",
        support_status=status,
        evidence_ids=[f"evidence.{evidence_id}"] if status == "supported" else [],
        reason=reason,
    )


def build_evidence_facts_v3() -> tuple[EvidenceFactV3, ...]:
    specs: dict[str, dict[str, Any]] = {
        "intent_result": {
            "producers": ("intent_routing",),
            "timing": "after formal Intent validation",
            "schema": IntentResult.model_json_schema(),
            "interface": "agent_result.intent_result",
            "events": ("intent_decided",),
            "paths": (
                "success",
                "need_clarification",
                "need_confirmation",
                "rejected",
                "failure",
            ),
            "availability": _availability("intent_result"),
        },
        "context_state": {
            "producers": ("orchestration",),
            "timing": "not emitted by the current runtime",
            "schema": {"type": "object"},
            "interface": "unavailable",
            "events": (),
            "paths": (),
            "availability": _availability(
                "context_state",
                "unsupported",
                "The runtime has no cross-turn state input or state snapshot output.",
            ),
        },
        "tool_trace": {
            "producers": ("tool_loop", "tool_registry"),
            "timing": "before, during, and after a Tool invocation",
            "schema": ToolCallRecord.model_json_schema(),
            "interface": "agent_result.tool_calls_and_events",
            "events": (
                "tool_requested",
                "tool_started",
                "tool_succeeded",
                "tool_failed",
                "tool_timeout",
            ),
            "paths": ("success", "failure", "timeout"),
            "availability": _availability("tool_trace"),
        },
        "safety_recovery_event": {
            "producers": ("orchestration", "tool_loop", "execution_guard"),
            "timing": "when execution stops before normal completion",
            "schema": {"type": "object"},
            "interface": "agent_result.events",
            "events": (
                "clarification_returned",
                "confirmation_required",
                "request_rejected",
                "model_failed",
                "tool_failed",
                "tool_timeout",
                "max_steps_exceeded",
            ),
            "paths": (
                "need_clarification",
                "need_confirmation",
                "rejected",
                "failure",
                "timeout",
            ),
            "availability": _availability("safety_recovery_event"),
        },
        "final_response": {
            "producers": ("orchestration", "observability"),
            "timing": "at terminal run completion",
            "schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "final_response": {"type": "string"},
                },
                "required": ["status", "final_response"],
            },
            "interface": "agent_result",
            "events": ("final_response_generated", "run_finished"),
            "paths": (
                "success",
                "need_clarification",
                "need_confirmation",
                "rejected",
                "failure",
            ),
            "availability": _availability("final_response"),
        },
    }
    return tuple(
        EvidenceFactV3(
            evidence_id=evidence_id,
            producer_module_roles=spec["producers"],
            production_timing=spec["timing"],
            payload_schema={
                **spec["schema"],
                "x-evidence-delivery": {
                    "version": "1.0",
                    "protocol_version": "1.0",
                    "event_rules_version": "mini-agent-events-v1",
                    "independent_interface": "agent_trace_sdk.EvidenceReader.read",
                    "correlation": ["trace_id", "run_id", "turn_index"],
                    "enabled_when": "LocalEvidenceSink is injected by the caller",
                    "legacy_interface": spec["interface"],
                    "unavailable_when": [
                        "sink not configured",
                        "execution interrupted before emission",
                        "export failed",
                        "required fields redacted or truncated",
                    ],
                    "events": {
                        name: {
                            "capability_layer": EVENT_RULES[name].layer,
                            "allowed_fields": list(EVENT_RULES[name].fields),
                            "required_fields": list(EVENT_RULES[name].required),
                        }
                        for name in spec["events"]
                        if name in EVENT_RULES
                    },
                    "coverage": "declared events only; not a full copy of AgentResult",
                },
            },
            observation_interface=spec["interface"],
            event_types=spec["events"],
            applicable_result_paths=spec["paths"],
            availability=spec["availability"],
        )
        for evidence_id, spec in specs.items()
    )

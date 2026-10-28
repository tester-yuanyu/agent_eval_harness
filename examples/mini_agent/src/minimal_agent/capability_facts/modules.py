"""Fixed MiniAgent runtime module facts."""

from typing import Any

from capability_snapshot_kit.facts import ModuleFactV3
from capability_snapshot_kit.models import CapabilityClaimV3

MODULE_IDS_V3 = frozenset(
    {
        "agent_orchestrator",
        "model_gateway",
        "intent_router",
        "tool_loop",
        "tool_registry",
        "execution_guard",
        "observability",
    }
)


def _claim(
    capability_key: str,
    status: str,
    *,
    evidence_ids: tuple[str, ...] = (),
    reason: str | None = None,
) -> CapabilityClaimV3:
    return CapabilityClaimV3(
        capability_key=capability_key,
        support_status=status,
        evidence_ids=list(evidence_ids),
        reason=reason,
    )


def build_module_facts_v3(
    intent_ids: tuple[str, ...],
    tool_ids: tuple[str, ...],
) -> tuple[ModuleFactV3, ...]:
    no_conversation_state = (
        "MinimalAgent.run accepts one user input and no inherited conversation state."
    )
    specs: dict[str, dict[str, Any]] = {
        "agent_orchestrator": {
            "role": "orchestration",
            "responsibility": "Coordinate one run from intent routing to result.",
            "boundary": "boundary.end_to_end",
            "claims": [
                _claim(
                    "orchestration.single_run",
                    "supported",
                    evidence_ids=("evidence.final_response",),
                ),
                *[
                    _claim(key, "unsupported", reason=no_conversation_state)
                    for key in (
                        "context.inheritance",
                        "context.override",
                        "context.cancellation",
                        "context.session_isolation",
                        "context.residual_state_handling",
                        "context.cleanup",
                    )
                ],
            ],
            "events": ["run_started", "run_finished"],
        },
        "model_gateway": {
            "role": "model_gateway",
            "responsibility": "Request structured model output.",
            "boundary": "boundary.understanding",
            "claims": [
                _claim(
                    "model.structured_output",
                    "supported",
                    evidence_ids=("evidence.intent_result",),
                )
            ],
            "events": ["intent_candidate_received", "model_failed"],
        },
        "intent_router": {
            "role": "intent_routing",
            "responsibility": "Normalize and validate formal Intent contracts.",
            "boundary": "boundary.understanding",
            "claims": [
                _claim(
                    "intent.formal_validation",
                    "supported",
                    evidence_ids=("evidence.intent_result",),
                ),
                _claim(
                    "intent.semantic_validation",
                    "supported",
                    evidence_ids=("evidence.intent_result",),
                ),
            ],
            "events": [
                "intent_parameter_normalized",
                "intent_parameter_validation_failed",
                "intent_semantic_constraint_failed",
                "intent_contract_validated",
                "intent_decided",
            ],
        },
        "tool_loop": {
            "role": "tool_loop",
            "responsibility": "Run a bounded synchronous Tool-calling loop.",
            "boundary": "boundary.planning_execution",
            "claims": [
                _claim(
                    "execution.bounded_tool_loop",
                    "supported",
                    evidence_ids=("evidence.tool_trace",),
                ),
                _claim(
                    "safety.tool_failure_terminal",
                    "supported",
                    evidence_ids=("evidence.safety_recovery_event",),
                ),
                _claim(
                    "safety.tool_timeout_terminal",
                    "supported",
                    evidence_ids=("evidence.safety_recovery_event",),
                ),
            ],
            "events": [
                "tool_requested",
                "tool_started",
                "tool_succeeded",
                "tool_failed",
                "tool_timeout",
                "max_steps_exceeded",
            ],
        },
        "tool_registry": {
            "role": "tool_registry",
            "responsibility": "Validate and invoke explicitly registered Tools.",
            "boundary": "boundary.planning_execution",
            "claims": [
                _claim(
                    "execution.registered_tool_invocation",
                    "supported",
                    evidence_ids=("evidence.tool_trace",),
                )
            ],
            "events": ["tool_started", "tool_succeeded", "tool_failed"],
        },
        "execution_guard": {
            "role": "execution_guard",
            "responsibility": "Enforce the run-scoped Tool allow list.",
            "boundary": "boundary.safety_recovery",
            "claims": [
                _claim(
                    "safety.run_allow_list",
                    "supported",
                    evidence_ids=("evidence.safety_recovery_event",),
                )
            ],
            "events": ["tool_failed"],
        },
        "observability": {
            "role": "observability",
            "responsibility": "Expose terminal results and runtime Trace events.",
            "boundary": "boundary.result",
            "claims": [
                _claim(
                    "observability.trace_export",
                    "supported",
                    evidence_ids=("evidence.final_response",),
                ),
                _claim(
                    "result.final_response",
                    "supported",
                    evidence_ids=("evidence.final_response",),
                ),
            ],
            "events": ["final_response_generated", "run_finished"],
        },
    }
    facts = tuple(
        ModuleFactV3(
            module_id=module_id,
            contract_version=f"{module_id.replace('_', '-')}-module-v3",
            roles=(spec["role"],),
            responsibility=spec["responsibility"],
            component_versions={module_id: "v3"},
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            capabilities=tuple(spec["claims"]),
            module_ids=(),
            intent_ids=intent_ids if module_id == "intent_router" else (),
            tool_ids=(
                tool_ids if module_id in {"tool_loop", "tool_registry"} else ()
            ),
            execution_boundary_ids=(spec["boundary"],),
            trace_event_types=tuple(spec["events"]),
        )
        for module_id, spec in specs.items()
    )
    if {item.module_id for item in facts} != MODULE_IDS_V3:
        raise ValueError("module facts do not match the fixed runtime modules")
    return facts

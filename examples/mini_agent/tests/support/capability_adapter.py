"""Agent-independent adapter fixture for Capability Snapshot Kit tests."""

from capability_snapshot_kit import CapabilityClaimV3
from capability_snapshot_kit.adapter import CapabilityAdapterV3
from capability_snapshot_kit.facts import (
    AgentFactsV3,
    EvidenceFactV3,
    IntentFactV3,
    ModuleFactV3,
    ToolFactV3,
)


class FakeCapabilityAdapter(CapabilityAdapterV3):
    def agent_facts(self) -> AgentFactsV3:
        return AgentFactsV3(
            agent_id="example_agent",
            agent_version="1.0.0",
            contract_version="example-agent-v1",
            entrypoints=["ExampleAgent.run_intent_only", "ExampleAgent.run"],
            runtime_bindings={
                "entrypoint.intent_only": "ExampleAgent.run_intent_only",
                "input.context": "context_input",
                "node.intent_decided": "intent_decided",
                "node.context_state_observed": "context_state_observed",
                "node.tool_requested": "tool_requested",
                "node.tool_terminal": "tool_terminal",
                "node.policy_or_failure_detected": "policy_or_failure_detected",
                "node.terminal_stop": "terminal_stop",
                "node.terminal_status_selected": "terminal_status_selected",
                "node.run_started": "run_started",
                "node.run_finished": "run_finished",
            },
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            runtime_versions={"runtime": "example-v1"},
        )

    def module_facts(self) -> tuple[ModuleFactV3, ...]:
        return (
            ModuleFactV3(
                module_id="intent_router",
                contract_version="intent-router-v1",
                roles=(
                    "orchestration",
                    "model_gateway",
                    "intent_routing",
                    "tool_loop",
                    "tool_registry",
                    "execution_guard",
                    "observability",
                ),
                responsibility="Validate example intents.",
                component_versions={"intent_router": "v1"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                capabilities=(
                    CapabilityClaimV3(
                        capability_key="intent.formal_validation",
                        support_status="supported",
                        evidence_ids=["evidence.intent_result"],
                        reason=None,
                    ),
                ),
                module_ids=(),
                intent_ids=("intent.query_user",),
                tool_ids=(),
                execution_boundary_ids=("boundary.understanding",),
                trace_event_types=("intent_decided",),
            ),
        )

    def intent_facts(self) -> tuple[IntentFactV3, ...]:
        return (
            IntentFactV3(
                intent_id="query_user",
                contract_version="query-user-v1",
                module_role="intent_routing",
                parameters_schema={"type": "object"},
                parameter_semantics={},
                decision_rules={},
                semantic_rules={},
                required_tool_name=None,
                capabilities=(
                    CapabilityClaimV3(
                        capability_key="intent.contract_validation",
                        support_status="supported",
                        evidence_ids=["evidence.intent_result"],
                        reason=None,
                    ),
                ),
            ),
        )

    def tool_facts(self) -> tuple[ToolFactV3, ...]:
        return ()

    def evidence_facts(self) -> tuple[EvidenceFactV3, ...]:
        return (
            EvidenceFactV3(
                evidence_id="intent_result",
                producer_module_roles=("intent_routing",),
                production_timing="after validation",
                payload_schema={"type": "object"},
                observation_interface="agent_result.intent_result",
                event_types=("intent_decided",),
                applicable_result_paths=("success",),
                availability=CapabilityClaimV3(
                    capability_key="evidence.intent_result_available",
                    support_status="supported",
                    evidence_ids=["evidence.intent_result"],
                    reason=None,
                ),
            ),
        )

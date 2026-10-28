"""An Agent-owned plugin: the Kit never imports this module itself."""

from pathlib import Path

from capability_snapshot_kit import (
    AgentFacts,
    CapabilityClaim,
    EvidenceFact,
    IntentFact,
    ModuleFact,
)
from capability_snapshot_kit.ingestion import FactDocument
from capability_snapshot_kit.ingestion.sources import source_reference

from .agent import AGENT_VERSION, POLICY_VERSION, CustomerInput, CustomerResult


def _claim(key: str) -> CapabilityClaim:
    return CapabilityClaim(
        capability_key=key,
        support_status="supported",
        evidence_ids=["evidence.final_response"],
        reason=None,
    )


class CustomerCollector:
    def collect(self, source_root: Path) -> FactDocument:
        document = FactDocument(
            agent=AgentFacts(
                agent_id="customer_service_demo",
                agent_version=AGENT_VERSION,
                contract_version="customer-contract-v1",
                entrypoints=["CustomerServiceAgent.run"],
                runtime_bindings={
                    "entrypoint.run": "CustomerServiceAgent.run",
                    "node.finished": "run_finished",
                },
                input_schema=CustomerInput.model_json_schema(),
                output_schema=CustomerResult.model_json_schema(),
                runtime_versions={
                    "policy": POLICY_VERSION,
                    "implementation": AGENT_VERSION,
                },
            ),
            modules=(
                ModuleFact(
                    module_id="customer_dialogue",
                    contract_version="dialogue-v1",
                    roles=("dialogue", "observability"),
                    responsibility="Rule-based demo: empty input clarification, refund "
                    "keyword policy response, otherwise handoff suggestion.",
                    component_versions={"implementation": AGENT_VERSION},
                    input_schema=CustomerInput.model_json_schema(),
                    output_schema=CustomerResult.model_json_schema(),
                    capabilities=tuple(
                        _claim(key)
                        for key in (
                            "dialogue.respond",
                            "dialogue.clarification",
                            "dialogue.handoff_suggestion",
                            "result.final_response",
                        )
                    )
                    + (
                        CapabilityClaim(
                            capability_key="context.inheritance",
                            support_status="unsupported",
                            evidence_ids=[],
                            reason="Each call is stateless; no conversation memory.",
                        ),
                    ),
                    module_ids=(),
                    intent_ids=("intent.customer_support",),
                    tool_ids=(),
                    execution_boundary_ids=("boundary.conversation",),
                    trace_event_types=("run_started", "response_ready", "run_finished"),
                ),
            ),
            intents=(
                IntentFact(
                    intent_id="customer_support",
                    contract_version="support-v1",
                    module_role="dialogue",
                    parameters_schema=CustomerInput.model_json_schema(),
                    parameter_semantics={
                        "user_input": "Text stripped before keyword matching."
                    },
                    decision_rules={
                        "empty": "NEED_CLARIFICATION",
                        "contains_退款": "SUCCESS",
                        "otherwise": "HANDOFF_SUGGESTED",
                    },
                    semantic_rules={
                        "policy_version": POLICY_VERSION,
                        "handoff": "Suggestion only, no external transfer.",
                    },
                    required_tool_name=None,
                    capabilities=(_claim("dialogue.business_task"),),
                ),
            ),
            evidence=(
                EvidenceFact(
                    evidence_id="final_response",
                    producer_module_roles=("observability",),
                    production_timing="On return from CustomerServiceAgent.run",
                    payload_schema=CustomerResult.model_json_schema(),
                    observation_interface="CustomerResult.model_dump()",
                    event_types=("run_started", "response_ready", "run_finished"),
                    applicable_result_paths=(
                        "success",
                        "need_clarification",
                        "handoff_suggested",
                    ),
                    availability=_claim("evidence.final_response_available"),
                ),
            ),
        )
        paths = [
            "examples/customer_service/agent.py",
            "examples/customer_service/collector.py",
        ]
        payload = document.model_dump(mode="json")
        payload["sources"] = {
            path: source_reference(source_root, path).model_dump(mode="json")
            for path in paths
        }
        payload["origins"] = {key: paths for key in document.fact_index()}
        return FactDocument.model_validate(payload)


def create() -> CustomerCollector:
    return CustomerCollector()

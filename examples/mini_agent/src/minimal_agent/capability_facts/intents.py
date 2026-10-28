"""MiniAgent Intent facts derived from its formal Intent registry."""

from capability_snapshot_kit.facts import IntentFactV3
from capability_snapshot_kit.models import CapabilityClaimV3
from minimal_agent.contracts.intents import IntentRegistry


def build_intent_facts_v3(registry: IntentRegistry) -> tuple[IntentFactV3, ...]:
    facts: list[IntentFactV3] = []
    for definition in registry.definitions:
        if definition.execution_mode == "write":
            complete = {
                "status": "NEED_CONFIRMATION",
                "next_action": "ASK_CONFIRMATION",
            }
        elif definition.execution_mode == "unsupported":
            complete = {"status": "REJECTED", "next_action": "REJECT"}
        else:
            complete = {"status": "READY", "next_action": "CALL_TOOL"}
        incomplete = (
            {"status": "REJECTED", "next_action": "REJECT"}
            if definition.execution_mode == "unsupported"
            else {
                "status": "NEED_CLARIFICATION",
                "next_action": "ASK_USER",
            }
        )
        facts.append(
            IntentFactV3(
                intent_id=definition.intent,
                contract_version=definition.contract_version,
                module_role="intent_routing",
                parameters_schema=definition.parameters_model.model_json_schema(),
                parameter_semantics={
                    "missing_parameters": list(definition.missing_parameters),
                    "normalizers": [
                        type(normalizer).__name__
                        for normalizer in definition.normalizers
                    ],
                },
                decision_rules={
                    "complete": complete,
                    "incomplete": incomplete,
                    "execution_mode": definition.execution_mode,
                },
                semantic_rules=dict(definition.semantic_rules),
                required_tool_name=definition.tool_name,
                capabilities=(
                    CapabilityClaimV3(
                        capability_key="intent.contract_validation",
                        support_status="supported",
                        evidence_ids=["evidence.intent_result"],
                        reason=None,
                    ),
                ),
            )
        )
    return tuple(facts)

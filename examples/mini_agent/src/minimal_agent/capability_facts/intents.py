"""MiniAgent Intent facts derived from its formal Intent registry."""

from capability_snapshot_kit.facts import IntentFactV3
from capability_snapshot_kit.models import CapabilityClaimV3

from minimal_agent.contracts.intents import IntentRegistry

from .semantics import intent_semantics


def build_intent_facts_v3(registry: IntentRegistry) -> tuple[IntentFactV3, ...]:
    facts: list[IntentFactV3] = []
    for definition in registry.definitions:
        semantics = intent_semantics(definition)
        complete_status, complete_action = definition.completion_policy.decide(False)
        incomplete_status, incomplete_action = definition.completion_policy.decide(True)
        complete = {"status": complete_status, "next_action": complete_action}
        incomplete = {"status": incomplete_status, "next_action": incomplete_action}
        facts.append(
            IntentFactV3(
                intent_id=definition.intent,
                contract_version=definition.contract_version + "+semantics-v2",
                module_role="intent_routing",
                parameters_schema=definition.parameters_model.model_json_schema(),
                parameter_semantics={
                    "execution_semantics": semantics,
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

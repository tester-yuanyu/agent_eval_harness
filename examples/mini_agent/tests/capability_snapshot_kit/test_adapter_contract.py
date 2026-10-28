from __future__ import annotations

import pytest
from pydantic import ValidationError

from capability_snapshot_kit import CapabilityClaimV3
from capability_snapshot_kit.adapter import CapabilityAdapterV3
from capability_snapshot_kit.facts import ModuleFactV3, ToolFactV3
from tests.support.capability_adapter import FakeCapabilityAdapter


def _module(module_id: str, role: str) -> ModuleFactV3:
    return ModuleFactV3(
        module_id=module_id,
        contract_version=f"{module_id}-v1",
        roles=(role,),
        responsibility="Test module.",
        component_versions={module_id: "v1"},
        input_schema={},
        output_schema={},
        capabilities=(
            CapabilityClaimV3(
                capability_key="module.test_capability",
                support_status="unknown",
                evidence_ids=[],
                reason="Test fact.",
            ),
        ),
        module_ids=(),
        intent_ids=(),
        tool_ids=(),
        execution_boundary_ids=(),
        trace_event_types=(),
    )


def test_fake_adapter_is_structurally_independent_of_minimal_agent() -> None:
    adapter = FakeCapabilityAdapter()

    assert isinstance(adapter, CapabilityAdapterV3)
    assert adapter.agent_facts().agent_id == "example_agent"
    assert [fact.module_id for fact in adapter.module_facts()] == ["intent_router"]
    assert [fact.intent_id for fact in adapter.intent_facts()] == ["query_user"]
    assert adapter.tool_facts() == ()
    assert [fact.evidence_id for fact in adapter.evidence_facts()] == [
        "intent_result"
    ]


def test_fact_ids_roles_and_claims_are_strict() -> None:
    with pytest.raises(ValidationError, match="roles|module role"):
        _module("intent_router", "Invalid Role")

    with pytest.raises(ValidationError, match="module_id"):
        _module("IntentRouter", "intent_routing")


def test_adapter_cannot_report_registered_false_tool_fact() -> None:
    with pytest.raises(ValidationError, match="registered"):
        ToolFactV3.model_validate(
            {
                "tool_name": "query_user_info",
                "contract_version": "v1",
                "tool_version": "v1",
                "description": "Query user info.",
                "implementation_profile": "production",
                "registered": False,
                "function_schema": {},
                "parameter_semantics": {},
                "combination_rules": {},
                "batch_behavior": {},
                "preconditions": [],
                "result_protocols": {},
                "permission_requirements": [],
                "requires_confirmation": False,
                "risk_level": "low",
                "idempotency_rules": {},
                "side_effects": [],
                "retry_policy": {},
                "simulation_protocol": None,
                "simulation_capabilities": [],
                "observation_interfaces": [],
                "capabilities": [],
            }
        )


def test_duplicate_module_roles_are_retained_for_compiler_diagnostics() -> None:
    first = _module("first_module", "intent_routing")
    second = _module("second_module", "intent_routing")

    assert first.roles == second.roles == ("intent_routing",)

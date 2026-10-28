from dataclasses import replace
from pathlib import Path

from capability_snapshot_kit.compiler import compile_capability_bundle_v3
from capability_snapshot_kit.spec_loader import load_capability_spec_pack_v3
from minimal_agent.capabilities.v3.bundle import build_capability_bundle_v3
from minimal_agent.capabilities.v3.models import CapabilityClaimV3
from minimal_agent.capability_adapter import MiniAgentCapabilityAdapter
from minimal_agent.contracts.intents import build_default_intent_registry
from minimal_agent.runtime.tool_registry import ToolDefinition, ToolRegistry
from tests.support.tools import ECHO_CONTRACT, echo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPECS = load_capability_spec_pack_v3(PROJECT_ROOT / "capability_specs")
MODULE_IDS_V3 = {
    "module.agent_orchestrator",
    "module.model_gateway",
    "module.intent_router",
    "module.tool_loop",
    "module.tool_registry",
    "module.execution_guard",
    "module.observability",
}


def _configured_registry(name: str = "query_information") -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            contract=replace(
                ECHO_CONTRACT,
                name=name,
                implementation_profile="evaluation_adapter",
                simulation_capabilities=("success", "timeout"),
                observation_interfaces=("agent_result.tool_calls", "trace.events"),
            ),
            handler=echo,
        )
    )
    return registry


def _default_runtime_artifacts() -> tuple[dict, dict, dict]:
    bundle = build_capability_bundle_v3(
        build_default_intent_registry(),
        ToolRegistry(),
    )
    return bundle.modules, bundle.intents, bundle.tools


def test_module_catalog_is_specific_and_truthful() -> None:
    modules, _, _ = _default_runtime_artifacts()

    assert set(modules) == MODULE_IDS_V3
    generic_layer_keys = {
        "agent.understanding",
        "agent.context",
        "agent.planning_execution",
        "agent.safety_recovery",
        "agent.result",
    }
    assert all(
        not generic_layer_keys.issubset(
            {claim.capability_key for claim in module.capabilities}
        )
        for module in modules.values()
    )
    router_claims = {
        claim.capability_key: claim
        for claim in modules["module.intent_router"].capabilities
    }
    assert router_claims["intent.formal_validation"].support_status == "supported"
    assert router_claims["intent.formal_validation"].evidence_ids == [
        "evidence.intent_result"
    ]


def test_general_context_state_is_not_falsely_supported() -> None:
    modules, _, _ = _default_runtime_artifacts()
    claims = {
        claim.capability_key: claim
        for claim in modules["module.agent_orchestrator"].capabilities
        if claim.capability_key.startswith("context.")
    }

    assert set(claims) >= {
        "context.inheritance",
        "context.override",
        "context.cancellation",
        "context.session_isolation",
        "context.residual_state_handling",
        "context.cleanup",
    }
    assert all(claim.support_status != "supported" for claim in claims.values())
    assert all(claim.reason for claim in claims.values())


def test_zero_tool_catalog_keeps_requirements_without_manufacturing_refs() -> None:
    _, intents, tools = _default_runtime_artifacts()

    assert tools == {}
    assert all(intent.tool_refs == [] for intent in intents.values())
    assert intents["intent.query_user"].required_tool_name == "query_user_info"
    assert intents["intent.add_backpack_gift"].required_tool_name == (
        "add_gift_to_backpack"
    )


def test_only_the_matching_intent_references_a_registered_tool() -> None:
    bundle = build_capability_bundle_v3(
        build_default_intent_registry(),
        _configured_registry(),
    )
    tools = bundle.tools
    intents = bundle.intents

    assert set(tools) == {"tool.query_information"}
    assert [
        ref.snapshot_id for ref in intents["intent.query_information"].tool_refs
    ] == ["tool.query_information"]
    assert all(
        intent.tool_refs == []
        for snapshot_id, intent in intents.items()
        if snapshot_id != "intent.query_information"
    )


def test_tool_snapshot_exposes_execution_contract_without_fixture_values() -> None:
    tool = build_capability_bundle_v3(
        build_default_intent_registry(),
        _configured_registry(),
    ).tools["tool.query_information"]
    payload = tool.model_dump_json()

    assert tool.implementation_profile == "evaluation_adapter"
    assert set(tool.result_protocols) >= {
        "declared_results",
        "empty_result",
        "timeout",
        "rate_limit",
        "execution_failure",
        "partial_success",
    }
    assert tool.permission_requirements
    assert tool.risk_level == "low"
    assert tool.side_effects == []
    assert tool.idempotency_rules
    assert set(tool.retry_policy) >= {"eligible", "maximum_attempts", "stop_conditions"}
    assert tool.observation_interfaces == [
        "agent_result.tool_calls",
        "trace.events",
    ]
    assert "fixture-user" not in payload


def test_agent_aggregation_uses_worst_mandatory_child_status() -> None:
    base = MiniAgentCapabilityAdapter(
        build_default_intent_registry(),
        ToolRegistry(),
    )

    class UnknownUnderstandingAdapter(MiniAgentCapabilityAdapter):
        def module_facts(self):
            facts = list(base.module_facts())
            router = next(item for item in facts if item.module_id == "intent_router")
            claims = tuple(
                CapabilityClaimV3(
                    capability_key=claim.capability_key,
                    support_status="unknown",
                    evidence_ids=[],
                    reason="Test dependency has no verified implementation fact.",
                )
                if claim.capability_key == "intent.formal_validation"
                else claim
                for claim in router.capabilities
            )
            facts[facts.index(router)] = router.model_copy(
                update={"capabilities": claims}
            )
            return tuple(facts)

    adapter = UnknownUnderstandingAdapter(
        build_default_intent_registry(),
        ToolRegistry(),
    )
    claims = {
        claim.capability_key: claim
        for claim in compile_capability_bundle_v3(SPECS, adapter).agent.capabilities
    }

    assert claims["agent.understanding"].support_status == "unknown"
    assert claims["agent.understanding"].reason

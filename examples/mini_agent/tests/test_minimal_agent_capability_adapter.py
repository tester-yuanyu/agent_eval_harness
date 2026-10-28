from __future__ import annotations

from minimal_agent.capability_adapter import MiniAgentCapabilityAdapter
from minimal_agent.contracts.intents import build_default_intent_registry
from minimal_agent.contracts.tools import ToolResult
from minimal_agent.runtime.tool_registry import ToolRegistry
from minimal_agent.testing.query_user_tool import query_user_evaluation_definition

MODULE_ROLES = {
    "agent_orchestrator": ("orchestration",),
    "model_gateway": ("model_gateway",),
    "intent_router": ("intent_routing",),
    "tool_loop": ("tool_loop",),
    "tool_registry": ("tool_registry",),
    "execution_guard": ("execution_guard",),
    "observability": ("observability",),
}


def _handler(**arguments) -> ToolResult:
    return ToolResult(
        success=True,
        code="OK",
        message="matched",
        data={"fixture_secret": "must-not-enter-facts", "arguments": arguments},
    )


def _configured_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(query_user_evaluation_definition(_handler))
    return registry


def test_default_adapter_reports_runtime_truth_without_tools() -> None:
    adapter = MiniAgentCapabilityAdapter(
        build_default_intent_registry(),
        ToolRegistry(),
    )

    modules = adapter.module_facts()
    intents = adapter.intent_facts()
    evidence = {item.evidence_id: item for item in adapter.evidence_facts()}

    assert {item.module_id: item.roles for item in modules} == MODULE_ROLES
    assert len(intents) == 7
    assert {item.intent_id for item in intents} == {
        "query_information",
        "prepare_resource",
        "query_user",
        "query_gift",
        "add_backpack_gift",
        "query_pool",
        "unsupported",
    }
    assert adapter.tool_facts() == ()
    assert adapter.agent_facts().agent_id == "mini_agent"
    assert evidence["intent_result"].availability.support_status == "supported"
    assert evidence["context_state"].availability.support_status == "unsupported"
    assert evidence["tool_trace"].availability.support_status == "supported"


def test_configured_adapter_exports_only_registered_contract_metadata() -> None:
    adapter = MiniAgentCapabilityAdapter(
        build_default_intent_registry(),
        _configured_registry(),
    )

    tools = adapter.tool_facts()
    intents = {item.intent_id: item for item in adapter.intent_facts()}
    serialized = "\n".join(
        item.model_dump_json()
        for item in (
            adapter.agent_facts(),
            *adapter.module_facts(),
            *adapter.intent_facts(),
            *tools,
            *adapter.evidence_facts(),
        )
    )

    assert [item.tool_name for item in tools] == ["query_user_info"]
    assert tools[0].implementation_profile == "evaluation_adapter"
    assert tools[0].result_protocols["rate_limit"]["result_code"] == "RATE_LIMITED"
    assert intents["query_user"].required_tool_name == "query_user_info"
    assert "must-not-enter-facts" not in serialized

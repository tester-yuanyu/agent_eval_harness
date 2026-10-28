from minimal_agent.capabilities.v3.bundle import build_capability_bundle_v3
from minimal_agent.capabilities.v3.resolution import (
    CapabilitySelectionV3,
    resolve_capability_graph_v3,
)
from minimal_agent.contracts.intents import build_default_intent_registry
from minimal_agent.contracts.tools import ToolResult
from minimal_agent.runtime.tool_registry import ToolRegistry
from minimal_agent.testing.query_user_tool import query_user_evaluation_definition


def _handler(**arguments) -> ToolResult:
    return ToolResult(
        success=True,
        code="OK",
        message="matched",
        data={"fixture_user": "must-not-enter-snapshot", "query": arguments},
    )


def _configured_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(query_user_evaluation_definition(_handler))
    return registry


def test_default_bundle_remains_zero_tool() -> None:
    bundle = build_capability_bundle_v3(
        build_default_intent_registry(),
        ToolRegistry(),
    )

    assert bundle.tools == {}
    assert bundle.intents["intent.query_user"].tool_refs == []


def test_explicit_adapter_registration_changes_only_matching_tool_graph() -> None:
    default = build_capability_bundle_v3(
        build_default_intent_registry(),
        ToolRegistry(),
    )
    configured = build_capability_bundle_v3(
        build_default_intent_registry(),
        _configured_registry(),
    )

    assert set(configured.tools) == {"tool.query_user_info"}
    tool = configured.tools["tool.query_user_info"]
    assert tool.result_protocols["rate_limit"] == {
        "support_status": "supported",
        "result_code": "RATE_LIMITED",
        "source": "tool_contract",
    }
    assert tool.simulation_protocol == {
        "name": "deterministic_injected_handler",
        "version": "query-user-evaluation-adapter-v1",
    }
    assert [
        ref.snapshot_id for ref in configured.intents["intent.query_user"].tool_refs
    ] == ["tool.query_user_info"]
    assert all(
        intent.tool_refs == []
        for snapshot_id, intent in configured.intents.items()
        if snapshot_id != "intent.query_user"
    )
    assert configured.agent.snapshot_sha256 != default.agent.snapshot_sha256
    assert (
        configured.agent.capability_bundle_sha256
        != default.agent.capability_bundle_sha256
    )
    serialized = "\n".join(
        snapshot.model_dump_json()
        for snapshot in [configured.agent, *configured.child_snapshots]
    )
    assert "must-not-enter-snapshot" not in serialized


def test_configured_query_user_resolves_applicable_ranges_truthfully() -> None:
    bundle = build_capability_bundle_v3(
        build_default_intent_registry(),
        _configured_registry(),
    )

    understanding = resolve_capability_graph_v3(
        bundle,
        CapabilitySelectionV3(
            scope_or_chain_id="scope.understanding",
            intent_id="intent.query_user",
            tool_id=None,
        ),
    )
    execution = resolve_capability_graph_v3(
        bundle,
        CapabilitySelectionV3(
            scope_or_chain_id="scope.planning_execution",
            intent_id="intent.query_user",
            tool_id="tool.query_user_info",
        ),
    )
    context = resolve_capability_graph_v3(
        bundle,
        CapabilitySelectionV3(
            scope_or_chain_id="scope.context",
            intent_id="intent.query_user",
            tool_id="tool.query_user_info",
        ),
    )

    assert understanding.support_status == "supported"
    assert execution.support_status == "supported"
    assert context.support_status == "unsupported"

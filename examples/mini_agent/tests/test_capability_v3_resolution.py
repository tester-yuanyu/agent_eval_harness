from dataclasses import replace

from minimal_agent.capabilities.v3.bundle import build_capability_bundle_v3
from minimal_agent.capabilities.v3.models import CapabilityRequirementV3
from minimal_agent.capabilities.v3.resolution import (
    CapabilitySelectionV3,
    resolve_capability_graph_v3,
)
from minimal_agent.contracts.intents import build_default_intent_registry
from minimal_agent.runtime.tool_registry import ToolDefinition, ToolRegistry
from tests.support.tools import ECHO_CONTRACT, echo


def _bundle(tool_name: str | None = None):
    registry = ToolRegistry()
    if tool_name is not None:
        registry.register(
            ToolDefinition(
                contract=replace(ECHO_CONTRACT, name=tool_name),
                handler=echo,
            )
        )
    return build_capability_bundle_v3(build_default_intent_registry(), registry)


def _selection(
    scope_or_chain_id: str,
    intent_id: str = "intent.query_user",
    tool_id: str | None = None,
) -> CapabilitySelectionV3:
    return CapabilitySelectionV3(
        scope_or_chain_id=scope_or_chain_id,
        intent_id=intent_id,
        tool_id=tool_id,
    )


def test_explicit_unsupported_mandatory_claim_wins() -> None:
    result = resolve_capability_graph_v3(
        _bundle(),
        _selection("scope.context"),
    )

    assert result.support_status == "unsupported"
    assert all(item.support_status == "unsupported" for item in result.requirements)
    assert any("scope.context ->" in diagnostic for diagnostic in result.diagnostics)


def test_missing_claim_is_unknown_and_optional_failure_does_not_lower_status() -> None:
    bundle = _bundle("query_user_info")
    scope = bundle.scopes["scope.planning_execution"]
    missing_claim = CapabilityRequirementV3(
        requirement_id="missing_optional_claim",
        capability_key="tool.undeclared_behavior",
        provider={"role": "selected_tool", "snapshot_id": None},
        mandatory=False,
        evidence_ids=[],
    )
    bundle.scopes[scope.snapshot_id] = scope.model_copy(
        update={"requirements": [*scope.requirements, missing_claim]}
    )

    result = resolve_capability_graph_v3(
        bundle,
        _selection(
            "scope.planning_execution",
            tool_id="tool.query_user_info",
        ),
    )

    assert result.support_status == "supported"
    optional = next(
        item
        for item in result.requirements
        if item.requirement_id == "missing_optional_claim"
    )
    assert optional.support_status == "unknown"
    assert optional.diagnostics


def test_query_user_execution_without_registered_tool_is_unsupported() -> None:
    result = resolve_capability_graph_v3(
        _bundle(),
        _selection("scope.planning_execution"),
    )

    assert result.support_status == "unsupported"
    assert any("query_user_info" in diagnostic for diagnostic in result.diagnostics)
    assert any("not registered" in diagnostic for diagnostic in result.diagnostics)


def test_unrelated_selected_tool_is_an_explicit_mismatch() -> None:
    result = resolve_capability_graph_v3(
        _bundle("query_information"),
        _selection(
            "scope.planning_execution",
            tool_id="tool.query_information",
        ),
    )

    assert result.support_status == "unsupported"
    assert any("required-tool mismatch" in item for item in result.diagnostics)
    assert any("query_user_info" in item for item in result.diagnostics)


def test_supported_requires_compatible_claims_and_available_evidence() -> None:
    bundle = _bundle("query_user_info")
    selection = _selection(
        "scope.planning_execution",
        tool_id="tool.query_user_info",
    )

    supported = resolve_capability_graph_v3(bundle, selection)

    assert supported.support_status == "supported"
    assert all(item.support_status == "supported" for item in supported.requirements)

    scope = bundle.scopes[selection.scope_or_chain_id]
    first = scope.requirements[0].model_copy(
        update={"evidence_ids": ["evidence.context_state"]}
    )
    bundle.scopes[scope.snapshot_id] = scope.model_copy(
        update={"requirements": [first, *scope.requirements[1:]]}
    )
    unavailable = resolve_capability_graph_v3(bundle, selection)
    assert unavailable.support_status == "unknown"
    assert any("unavailable Evidence" in item for item in unavailable.diagnostics)


def test_resolution_does_not_mutate_sources_and_is_deterministic() -> None:
    bundle = _bundle("query_user_info")
    selection = _selection(
        "chain.end_to_end",
        tool_id="tool.query_user_info",
    )
    before = bundle.chains[selection.scope_or_chain_id].model_dump(mode="json")

    first = resolve_capability_graph_v3(bundle, selection)
    second = resolve_capability_graph_v3(bundle, selection)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert bundle.chains[selection.scope_or_chain_id].model_dump(mode="json") == before
    assert "support_status" not in before

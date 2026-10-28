from __future__ import annotations

from pathlib import Path

import pytest

from capability_snapshot_kit.compiler import compile_capability_bundle_v3
from capability_snapshot_kit.resolution import (
    CapabilitySelectionV3,
    resolve_capability_graph_v3,
)
from capability_snapshot_kit.spec_loader import load_capability_spec_pack_v3
from minimal_agent.capabilities.v3.bundle import build_capability_bundle_v3
from minimal_agent.capability_adapter import MiniAgentCapabilityAdapter
from minimal_agent.contracts.intents import build_default_intent_registry
from minimal_agent.contracts.tools import ToolResult
from minimal_agent.runtime.tool_registry import ToolRegistry
from minimal_agent.testing.query_user_tool import query_user_evaluation_definition

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPECS = load_capability_spec_pack_v3(PROJECT_ROOT / "capability_specs")


def _handler(**arguments) -> ToolResult:
    return ToolResult(success=True, code="OK", message="matched", data=arguments)


def _registry(configured: bool) -> ToolRegistry:
    registry = ToolRegistry()
    if configured:
        registry.register(query_user_evaluation_definition(_handler))
    return registry


def _payloads(bundle) -> dict[str, dict]:
    snapshots = [bundle.agent, *bundle.child_snapshots]
    return {
        snapshot.snapshot_id: snapshot.model_dump(mode="json")
        for snapshot in snapshots
    }


def _resolve_matrix(bundle, configured: bool) -> dict[tuple[str, str], dict]:
    tool_id = "tool.query_user_info" if configured else None
    roots = [*sorted(bundle.scopes), *sorted(bundle.chains)]
    return {
        (root, "intent.query_user"): resolve_capability_graph_v3(
            bundle,
            CapabilitySelectionV3(
                scope_or_chain_id=root,
                intent_id="intent.query_user",
                tool_id=tool_id,
            ),
        ).model_dump(mode="json")
        for root in roots
    }


@pytest.mark.parametrize("configured", [False, True])
def test_portable_compiler_matches_legacy_generator(configured: bool) -> None:
    intents = build_default_intent_registry()
    tools = _registry(configured)

    old = build_capability_bundle_v3(intents, tools)
    new = compile_capability_bundle_v3(
        SPECS,
        MiniAgentCapabilityAdapter(intents, tools),
    )

    assert _payloads(new) == _payloads(old)
    assert _resolve_matrix(new, configured) == _resolve_matrix(old, configured)

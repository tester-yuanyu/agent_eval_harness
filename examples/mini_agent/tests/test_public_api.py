from pathlib import Path

import capability_snapshot_kit as kit
import minimal_agent
import minimal_agent.capabilities.v3 as mini_v3
from minimal_agent import (
    AgentResult,
    IntentRegistry,
    IntentResult,
    MinimalAgent,
    ToolContract,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    build_capability_bundle,
    build_default_intent_registry,
    export_capability_bundle,
    run_intent_only,
    validate_capability_bundle,
)
from tests.support.model_client import DeterministicModelClient
from tests.support.tools import echo_definition

PUBLIC_NAMES = {
    "AgentResult",
    "IntentRegistry",
    "IntentResult",
    "MinimalAgent",
    "ToolContract",
    "ToolDefinition",
    "ToolRegistry",
    "ToolResult",
    "build_capability_bundle",
    "build_default_intent_registry",
    "export_capability_bundle",
    "run_intent_only",
    "validate_capability_bundle",
}


def rejected_intent() -> dict[str, object]:
    return {
        "intent": "unsupported",
        "status": "REJECTED",
        "next_action": "REJECT",
        "parameters": {},
        "missing_parameters": [],
        "reason": "Unsupported.",
    }


def test_root_facade_exports_only_stable_consumer_interfaces() -> None:
    assert len(minimal_agent.__all__) == 13
    assert set(minimal_agent.__all__) == PUBLIC_NAMES
    assert ToolContract is not None
    assert ToolDefinition is not None
    assert ToolResult is not None
    assert IntentRegistry is not None


def test_v3_compatibility_facade_reexports_portable_implementations() -> None:
    portable_names = {
        "AgentSnapshotV3",
        "BoundarySnapshotV3",
        "BundleDiffV3",
        "BundleValidationResultV3",
        "CapabilityBundleV3",
        "CapabilityBundleValidationErrorV3",
        "CapabilityClaimV3",
        "CapabilityProviderV3",
        "CapabilityRequirementV3",
        "CapabilitySelectionV3",
        "ChainNodeV3",
        "ChainSnapshotV3",
        "EvidenceSnapshotV3",
        "IntentSnapshotV3",
        "ModuleSnapshotV3",
        "ResolvedCapabilityGraphV3",
        "ResolvedRequirementV3",
        "ScopeSnapshotV3",
        "SnapshotReferenceV3",
        "SnapshotTypeV3",
        "SnapshotV3",
        "SupportStatusV3",
        "ToolSnapshotV3",
        "diff_capability_bundles_v3",
        "load_capability_bundle_v3",
        "resolve_capability_graph_v3",
        "snapshot_schema_v3",
        "validate_capability_bundle_v3",
    }

    assert set(mini_v3.__all__) == {
        "AGENT_CONTRACT_VERSION_V3",
        "SNAPSHOT_FORMAT_VERSION_V3",
        *portable_names,
        "build_capability_bundle_v3",
        "build_capability_snapshot_v3",
        "export_capability_bundle_v3",
    }
    for name in portable_names:
        assert getattr(mini_v3, name) is getattr(kit, name)


def test_public_interfaces_run_and_export_empty_configuration(
    tmp_path: Path,
) -> None:
    intents = build_default_intent_registry()
    tools = ToolRegistry()
    client = DeterministicModelClient([rejected_intent(), rejected_intent()])

    direct = run_intent_only("unsupported", client)
    result = MinimalAgent(client, tools).run("unsupported")
    bundle = build_capability_bundle(intents, tools)
    output = tmp_path / "empty"
    export_capability_bundle(output, intents, tools)

    assert isinstance(direct, IntentResult)
    assert isinstance(result, AgentResult)
    assert isinstance(bundle, kit.CapabilityBundle)
    assert bundle.agent.snapshot_format_version == "3.0"
    assert bundle.tools == {}
    assert validate_capability_bundle(output).snapshot_counts == {
        "agent": 1,
        "module": 7,
        "intent": 7,
        "tool": 0,
        "scope": 5,
        "chain": 3,
        "evidence": 5,
        "boundary": 7,
    }


def test_public_interfaces_run_and_export_configured_tool(tmp_path: Path) -> None:
    tools = ToolRegistry()
    tools.register(echo_definition())
    client = DeterministicModelClient(
        [
            {
                "intent": "query_information",
                "status": "READY",
                "next_action": "CALL_TOOL",
                "parameters": {
                    "resource_type": "fixture",
                    "environment": "test",
                },
                "missing_parameters": [],
                "reason": "Ready.",
            },
            {
                "type": "function_call",
                "call_id": "call-public",
                "name": "echo",
                "arguments": {"text": "hello"},
            },
            {"type": "message", "content": "Echo complete."},
        ]
    )

    result = MinimalAgent(client, tools).run("echo hello")
    output = tmp_path / "configured"
    export_capability_bundle(output, build_default_intent_registry(), tools)

    assert result.status == "SUCCESS"
    assert validate_capability_bundle(output).snapshot_counts["tool"] == 1

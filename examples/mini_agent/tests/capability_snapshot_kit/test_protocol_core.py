from __future__ import annotations

import ast
from pathlib import Path

from capability_snapshot_kit import (
    AgentSnapshotV3,
    CapabilityBundleV3,
    ChainSnapshotV3,
    ModuleSnapshotV3,
    calculate_capability_bundle_sha256_v3,
    reference_for_snapshot_v3,
    sha256_json,
)

ZERO_HASH = "0" * 64
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_generic_agent_snapshot_accepts_non_minimal_agent_id() -> None:
    snapshot = AgentSnapshotV3(
        snapshot_id="agent.example_agent",
        snapshot_type="agent",
        snapshot_format_version="3.0",
        contract_version="example-agent-v1",
        source_hashes={"agent_sha256": ZERO_HASH},
        snapshot_sha256=ZERO_HASH,
        agent_id="example_agent",
        agent_version="1.0.0",
        entrypoints=["ExampleAgent.run"],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        capabilities=[],
        module_refs=[],
        intent_refs=[],
        tool_refs=[],
        scope_refs=[],
        chain_refs=[],
        evidence_refs=[],
        boundary_refs=[],
        runtime_versions={"runtime": "1"},
        capability_bundle_sha256=ZERO_HASH,
    )

    assert snapshot.agent_id == "example_agent"
    assert snapshot.snapshot_id == "agent.example_agent"


def test_snapshot_models_and_hashes_are_deterministic() -> None:
    assert sha256_json({"b": 2, "a": 1}) == (
        "43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777"
    )
    assert calculate_capability_bundle_sha256_v3([]) == (
        "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    )


def test_generic_package_has_no_minimal_agent_imports() -> None:
    package_root = PROJECT_ROOT / "src" / "capability_snapshot_kit"
    violations: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(
                name == "minimal_agent" or name.startswith("minimal_agent.")
                for name in names
            ):
                violations.append(str(path.relative_to(PROJECT_ROOT)))

    assert violations == []


def test_reference_paths_preserve_current_v3_layout() -> None:
    module = ModuleSnapshotV3(
        snapshot_id="module.intent_router",
        snapshot_type="module",
        snapshot_format_version="3.0",
        contract_version="intent-router-module-v3",
        source_hashes={"module_sha256": ZERO_HASH},
        snapshot_sha256=ZERO_HASH,
        module_id="intent_router",
        responsibility="Validate intents.",
        component_versions={"intent_router": "v3"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        capabilities=[],
        module_refs=[],
        intent_refs=[],
        tool_refs=[],
        execution_boundary_ids=[],
        trace_event_types=[],
    )
    critical = ChainSnapshotV3(
        snapshot_id="chain.understanding_to_planning",
        snapshot_type="chain",
        snapshot_format_version="3.0",
        contract_version="example-v3",
        source_hashes={"chain_sha256": ZERO_HASH},
        snapshot_sha256=ZERO_HASH,
        chain_id="understanding_to_planning",
        description="Critical chain.",
        nodes=[],
        module_refs=[],
        evidence_refs=[],
        boundary_refs=[],
        requirements=[],
        branches=[],
        completion_condition="Complete.",
    )
    end_to_end = critical.model_copy(
        update={
            "snapshot_id": "chain.end_to_end",
            "chain_id": "end_to_end",
        }
    )

    assert reference_for_snapshot_v3(module).path == "modules/intent_router.json"
    assert reference_for_snapshot_v3(critical).path == (
        "chains/critical/understanding_to_planning.json"
    )
    assert reference_for_snapshot_v3(end_to_end).path == (
        "chains/end_to_end/end_to_end.json"
    )
    bundle = CapabilityBundleV3(
        agent=AgentSnapshotV3(
            snapshot_id="agent.example_agent",
            snapshot_type="agent",
            snapshot_format_version="3.0",
            contract_version="example-v1",
            source_hashes={"agent_sha256": ZERO_HASH},
            snapshot_sha256=ZERO_HASH,
            agent_id="example_agent",
            agent_version="1",
            entrypoints=[],
            input_schema={},
            output_schema={},
            capabilities=[],
            module_refs=[],
            intent_refs=[],
            tool_refs=[],
            scope_refs=[],
            chain_refs=[],
            evidence_refs=[],
            boundary_refs=[],
            runtime_versions={},
            capability_bundle_sha256=ZERO_HASH,
        ),
        modules={module.snapshot_id: module},
        intents={},
        tools={},
        scopes={},
        chains={critical.snapshot_id: critical, end_to_end.snapshot_id: end_to_end},
        evidence={},
        boundaries={},
    )
    assert [item.snapshot_id for item in bundle.child_snapshots] == [
        "chain.end_to_end",
        "chain.understanding_to_planning",
        "module.intent_router",
    ]

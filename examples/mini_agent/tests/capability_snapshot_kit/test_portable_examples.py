from __future__ import annotations

import json
from pathlib import Path

from capability_snapshot_kit import (
    CapabilitySelection,
    compile_capability_bundle,
    load_capability_bundle,
    load_capability_spec_pack,
    resolve_capability_graph,
)

ROOT = Path(__file__).resolve().parents[2]


def test_customer_agent_runs_without_tools_and_matches_declared_outcomes():
    from examples.customer_service.agent import CustomerServiceAgent

    agent = CustomerServiceAgent()
    assert agent.run("").status == "NEED_CLARIFICATION"
    assert agent.run("退款政策是什么").status == "SUCCESS"
    result = agent.run("请修改我的账户")
    assert result.status == "HANDOFF_SUGGESTED"
    assert result.handoff_executed is False
    assert result.events[-1] == "run_finished"


def test_customer_collector_exports_and_resolves_without_tool(tmp_path):
    from capability_snapshot_kit.ingestion.cli import main

    output = tmp_path / "customer"
    assert (
        main(
            [
                "export",
                "--collector",
                "examples.customer_service.collector:create",
                "--source-root",
                str(ROOT),
                "--profile",
                "conversation",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    bundle = load_capability_bundle(output / "bundle")
    assert len(bundle.tools) == 0
    assert len(bundle.modules) == 1
    selection = CapabilitySelection(
        scope_or_chain_id="chain.end_to_end",
        intent_id="intent.customer_support",
        tool_id=None,
    )
    resolved = resolve_capability_graph(bundle, selection)
    assert resolved.support_status == "supported"
    provenance = json.loads((output / "provenance.json").read_text())
    assert all(fact["source_ids"] for fact in provenance["facts"].values())
    assert provenance["execution_verified"] is False


def test_mini_agent_collector_preserves_existing_full_tool_bundle(tmp_path):
    from capability_snapshot_kit.ingestion.service import export_delivery
    from examples.full_tool_fixture import create_registry
    from examples.full_tool_fixture.collector import create
    from minimal_agent.capability_adapter import MiniAgentCapabilityAdapter
    from minimal_agent.contracts import build_default_intent_registry

    specs = load_capability_spec_pack(ROOT / "capability_specs")
    original = compile_capability_bundle(
        specs,
        MiniAgentCapabilityAdapter(build_default_intent_registry(), create_registry()),
    )
    output = tmp_path / "mini"
    export_delivery(
        output,
        source_root=ROOT,
        spec_root=ROOT / "capability_specs",
        runtime=create().collect(ROOT),
    )
    bundle = load_capability_bundle(output / "bundle")
    assert bundle.agent == original.agent
    assert len(bundle.tools) == 6

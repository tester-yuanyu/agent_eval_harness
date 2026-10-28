import json

import pytest

from capability_snapshot_kit import (
    CapabilitySelection,
    load_capability_bundle,
    resolve_capability_graph,
)
from examples.full_tool_fixture import create_registry
from minimal_agent import MinimalAgent, build_default_intent_registry
from minimal_agent.capabilities import export_capability_bundle
from tests.support.model_client import DeterministicModelClient

EXPECTED_TOOLS = {
    "query_information",
    "prepare_resource",
    "query_user_info",
    "query_gift_info",
    "add_gift_to_backpack",
    "query_pool_config",
}


def test_full_export_preserves_protocol_references_and_is_reproducible(tmp_path):
    roots = [tmp_path / "first", tmp_path / "second"]
    for root in roots:
        export_capability_bundle(
            root,
            build_default_intent_registry(),
            create_registry(),
        )
    first, second = roots
    assert {
        p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()
    } == {
        p.relative_to(second): p.read_bytes() for p in second.rglob("*") if p.is_file()
    }
    bundle = load_capability_bundle(first)
    assert len(bundle.modules) == len(bundle.intents) == 7
    assert len(bundle.chains) == 3
    assert {tool.tool_name for tool in bundle.tools.values()} == EXPECTED_TOOLS
    for intent in bundle.intents.values():
        assert [ref.snapshot_id for ref in intent.tool_refs] == (
            [f"tool.{intent.required_tool_name}"] if intent.required_tool_name else []
        )
    for tool in bundle.tools.values():
        assert tool.registered is True
        assert tool.implementation_profile == "test_fixture"
        assert tool.function_schema["parameters"]["additionalProperties"] is False
        assert tool.result_protocols["declared_results"]["OK"]["data_schema"][
            "required"
        ]
        data_schema = tool.result_protocols["declared_results"]["OK"]["data_schema"]
        value_schema = next(iter(data_schema["properties"].values()))
        row_schema = value_schema.get("items", value_schema)
        assert row_schema["required"]
        assert row_schema["additionalProperties"] is False
        assert all(name in row_schema["properties"] for name in row_schema["required"])
    serialized = "\n".join(p.read_text() for p in first.rglob("*.json"))
    assert "example-user@example.invalid" not in serialized
    assert '"gift_name": "Rose"' not in serialized
    resolved = resolve_capability_graph(
        bundle,
        CapabilitySelection(
            scope_or_chain_id="chain.end_to_end",
            intent_id="intent.query_user",
            tool_id="tool.query_user_info",
        ),
    )
    assert resolved.support_status == "supported"


def test_export_delivery_includes_hash_bound_inventory_gaps_and_validation(tmp_path):
    from examples.full_tool_fixture.export import export_delivery

    output = tmp_path / "delivery"
    export_delivery(output)
    bundle = load_capability_bundle(output / "bundle")
    validation = json.loads((output / "validation_report.json").read_text())
    assert validation["valid"] is True
    assert validation["snapshot_counts"]["tool"] == 6
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["capability_bundle_sha256"] == bundle.agent.capability_bundle_sha256
    inventory = json.loads((output / "capability_inventory.json").read_text())
    assert len(inventory["targets"]) == 17
    gaps = json.loads((output / "capability_contract_gaps.json").read_text())
    codes = {gap["gap_id"] for gap in gaps["gaps"]}
    assert {
        "PRODUCTION_BACKENDS_MISSING",
        "CONFIRMATION_RESUME_UNSUPPORTED",
        "CONTEXT_UNSUPPORTED",
        "PREPARE_RESOURCE_POLICY_MISMATCH",
    } <= codes
    assert manifest["production_ready"] is False
    with pytest.raises(FileExistsError):
        export_delivery(output)


def test_full_configuration_really_runs_query_user_and_preserves_confirmation():
    client = DeterministicModelClient(
        [
            {
                "intent": "query_user",
                "status": "READY",
                "next_action": "CALL_TOOL",
                "parameters": {"user_id": 10001},
                "missing_parameters": [],
                "reason": "ready",
            },
            {
                "type": "function_call",
                "call_id": "query-1",
                "name": "query_user_info",
                "arguments": {
                    "user_id": 10001,
                    "room_id": None,
                    "email": None,
                    "phone": None,
                },
            },
            {"type": "message", "content": "Found example user."},
            {
                "intent": "add_backpack_gift",
                "status": "READY",
                "next_action": "CALL_TOOL",
                "parameters": {"user_id": 10001, "gift_id": 101, "environment": "test"},
                "missing_parameters": [],
                "reason": "confirm",
            },
        ]
    )
    agent = MinimalAgent(client, create_registry())
    result = agent.run("查询用户 ID 10001")
    assert result.tool_calls[0].output["data"]["user"]["user_id"] == 10001
    assert result.status == "SUCCESS"
    pending = agent.run("给用户 ID 10001 发礼物 101，测试环境")
    assert pending.status == "NEED_CONFIRMATION"
    assert pending.tool_calls == []
    assert client.remaining_responses == 0

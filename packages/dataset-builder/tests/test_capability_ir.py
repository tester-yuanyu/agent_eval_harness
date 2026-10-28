from __future__ import annotations

from pathlib import Path

import pytest

from dataset_builder.capability_adapters import (
    AdapterConversionError,
    CapabilityAdapter,
    resolve_support_status,
)
from dataset_builder.capability_bundle import load_validated_bundle
from dataset_builder.capability_ir import (
    CapabilitySelection,
    SupportStatus,
    write_capability_ir_schema,
)
from dataset_builder.capability_profiles import load_trusted_profile
from dataset_builder.plugins import PluginKey, PluginRegistry

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT.parent / "mini_agent" / "capabilities"
TRUST_STORE = ROOT / "protocol_profiles" / "trust_store.json"


def _profile():
    return load_trusted_profile(
        "capability-snapshot", "3.0", TRUST_STORE
    )


def _bundle():
    return load_validated_bundle(BUNDLE, _profile())


def test_converts_supported_understanding_selection_to_canonical_ir():
    ir = CapabilityAdapter().convert(
        _bundle(),
        CapabilitySelection(
            scope_or_chain_id="scope.understanding",
            intent_id="intent.query_user",
        ),
        _profile(),
    )

    assert ir.support_status is SupportStatus.SUPPORTED
    assert ir.intent.snapshot_id == "intent.query_user"
    assert ir.intent.required_tool_name == "query_user_info"
    assert set(ir.parameters_schema["properties"]) == {
        "user_id",
        "room_id",
        "email",
        "phone",
    }
    assert ir.decision_rules["complete"]["next_action"] == "CALL_TOOL"
    assert [item.requirement_id for item in ir.requirements] == [
        "formal_intent_validation",
        "selected_intent_contract",
    ]
    assert all(
        item.support_status is SupportStatus.SUPPORTED
        for item in ir.requirements
    )
    assert ir.evidence[0].observation_interface == "agent_result.intent_result"
    assert ir.source_artifacts == tuple(
        sorted(ir.source_artifacts, key=lambda item: item.snapshot_id)
    )
    assert len(ir.canonical_sha256) == 64


@pytest.mark.parametrize(
    "chain_id",
    [
        "chain.understanding_to_planning",
        "chain.planning_to_result",
        "chain.end_to_end",
    ],
)
def test_missing_selected_tool_is_explicitly_unsupported_for_tool_chain(
    chain_id,
):
    ir = CapabilityAdapter().convert(
        _bundle(),
        CapabilitySelection(
            scope_or_chain_id=chain_id,
            intent_id="intent.query_user",
        ),
        _profile(),
    )

    assert ir.support_status is SupportStatus.UNSUPPORTED
    tool_requirement = next(
        item
        for item in ir.requirements
        if item.requirement_id == "selected_tool_execution"
    )
    assert tool_requirement.support_status is SupportStatus.UNSUPPORTED
    assert "query_user_info" in tool_requirement.reason


def test_support_precedence_and_optional_gaps_are_deterministic():
    assert resolve_support_status(
        [SupportStatus.SUPPORTED, SupportStatus.UNKNOWN]
    ) is SupportStatus.UNKNOWN
    assert resolve_support_status(
        [
            SupportStatus.SUPPORTED,
            SupportStatus.UNKNOWN,
            SupportStatus.UNSUPPORTED,
        ]
    ) is SupportStatus.UNSUPPORTED
    assert resolve_support_status([]) is SupportStatus.SUPPORTED


def test_context_selection_preserves_explicit_unsupported_claims():
    ir = CapabilityAdapter().convert(
        _bundle(),
        CapabilitySelection(
            scope_or_chain_id="scope.context",
            intent_id="intent.query_user",
        ),
        _profile(),
    )
    assert ir.support_status is SupportStatus.UNSUPPORTED
    assert all(
        item.support_status is SupportStatus.UNSUPPORTED
        for item in ir.requirements
    )


@pytest.mark.parametrize(
    "selection",
    [
        CapabilitySelection(
            scope_or_chain_id="scope.missing",
            intent_id="intent.query_user",
        ),
        CapabilitySelection(
            scope_or_chain_id="scope.understanding",
            intent_id="intent.missing",
        ),
        CapabilitySelection(
            scope_or_chain_id="scope.understanding",
            intent_id="intent.query_user",
            tool_id="tool.missing",
        ),
    ],
)
def test_rejects_invalid_selected_ids(selection):
    with pytest.raises(AdapterConversionError, match="selected_artifact_missing"):
        CapabilityAdapter().convert(
            _bundle(), selection, _profile()
        )


def test_conversion_is_byte_deterministic_and_schema_is_generated(tmp_path):
    adapter = CapabilityAdapter()
    selection = CapabilitySelection(
        scope_or_chain_id="scope.understanding",
        intent_id="intent.query_gift",
    )
    first = adapter.convert(_bundle(), selection, _profile())
    second = adapter.convert(_bundle(), selection, _profile())
    assert first.model_dump_json() == second.model_dump_json()
    assert first.canonical_sha256 == second.canonical_sha256

    output = tmp_path / "capability_ir.schema.json"
    write_capability_ir_schema(output)
    assert output.is_file()
    assert '"CapabilityIR"' in output.read_text()


def test_adapter_is_resolved_by_protocol_key_not_agent_identity():
    registry = PluginRegistry()
    adapter = CapabilityAdapter()
    key = PluginKey(
        "capability_adapter", "capability-snapshot", "1.0"
    )
    registry.register(key, adapter)
    resolved = registry.resolve(key)
    assert resolved is adapter

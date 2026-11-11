import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from examples.full_tool_fixture import collector, export
from minimal_agent.capability_adapter import MiniAgentCapabilityAdapter
from minimal_agent.contracts.intents import build_default_intent_registry
from minimal_agent.runtime.tool_registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


def test_collector_rejects_other_checkout_even_if_all_hashes_are_consistent(tmp_path):
    document = collector.create().collect(ROOT)
    for source in document.sources.values():
        dest = tmp_path / source.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source.path, dest)
    with pytest.raises(ValueError, match="loaded module"):
        collector.create().collect(tmp_path)


def test_collector_uses_supplied_registry_without_building_another():
    adapter = MiniAgentCapabilityAdapter(
        build_default_intent_registry(), ToolRegistry()
    )
    with patch.object(
        collector, "create_registry", side_effect=AssertionError("second registry")
    ):
        doc = collector.MiniAgentCollector(adapter).collect(ROOT)
    assert doc.tools == ()


def test_full_export_compiles_exactly_the_collected_document(tmp_path):
    # A second factory call would now disagree; it must never be made.
    with patch.object(
        collector, "create_registry", side_effect=AssertionError("second registry")
    ):
        output = export.export_delivery(tmp_path / "delivery")
    facts = json.loads((output / "collected_facts.json").read_text())
    manifest = json.loads((output / "manifest.json").read_text())
    assert len(facts["tools"]) == manifest["tool_count"] == 6
    from capability_snapshot_kit.compiler import compile_capability_bundle_v3
    from capability_snapshot_kit.ingestion.models import FactDocument
    from capability_snapshot_kit.spec_loader import load_capability_spec_pack_v3
    from minimal_agent.capabilities.v3.bundle import DEFAULT_CAPABILITY_SPEC_ROOT

    rebuilt = compile_capability_bundle_v3(
        load_capability_spec_pack_v3(DEFAULT_CAPABILITY_SPEC_ROOT),
        FactDocument.model_validate(facts),
    )
    assert (
        rebuilt.agent.capability_bundle_sha256 == manifest["capability_bundle_sha256"]
    )


def test_custom_configured_implementation_source_is_bound():
    from dataclasses import replace

    from minimal_agent.contracts.intents import IntentRegistry

    class ExternalNormalizer:
        def snapshot_semantics(self):
            return {
                "component_id": "external.normalizer",
                "version": "1",
                "parameters": {},
            }

        def normalize(self, *args):
            raise AssertionError("do not execute custom normalizer")

    registry = IntentRegistry()
    for definition in build_default_intent_registry().definitions:
        registry.register(
            replace(definition, normalizers=(ExternalNormalizer(),))
            if definition.intent == "query_information"
            else definition
        )
    adapter = MiniAgentCapabilityAdapter(registry, ToolRegistry())
    document = collector.MiniAgentCollector(adapter).collect(ROOT)
    assert (
        "tests/test_snapshot_collection.py"
        in document.origins["intent.query_information"]
    )
    assert "tests/test_snapshot_collection.py" in document.sources

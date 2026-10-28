from __future__ import annotations

from pathlib import Path

import pytest

from dataset_builder.builtin_plugins import BUILTIN_PROTOCOL, register_builtins
from dataset_builder.plugins import (
    CapabilityResolver,
    CaseGenerator,
    CoveragePlanner,
    DatasetFreezer,
    DuplicatePluginError,
    MissingPluginError,
    PluginKey,
    PluginRegistry,
    ReviewRenderer,
    SnapshotLoader,
    SourcePackCompiler,
    ValidationGate,
)


class CompletePlugin:
    def load(self, root: Path):
        return root

    def resolve(self, bundle, selection):
        return bundle, selection

    def compile_source_pack(self, suite, graph):
        return suite, graph

    def plan_coverage(self, suite, source_pack):
        return suite, source_pack

    def generate_cases(self, request, client):
        return request, client

    def validate(self, suite, draft):
        return suite, draft

    def render_review(self, suite, draft, report):
        return f"{suite}:{draft}:{report}"

    def freeze(self, suite, draft, approval, output):
        return suite, draft, approval, output


def test_plugin_protocols_describe_real_role_behavior():
    plugin = CompletePlugin()

    assert isinstance(plugin, SnapshotLoader)
    assert isinstance(plugin, CapabilityResolver)
    assert isinstance(plugin, SourcePackCompiler)
    assert isinstance(plugin, CoveragePlanner)
    assert isinstance(plugin, CaseGenerator)
    assert isinstance(plugin, ValidationGate)
    assert isinstance(plugin, ReviewRenderer)
    assert isinstance(plugin, DatasetFreezer)


def test_registry_is_deterministic_and_rejects_duplicate_or_missing_plugins():
    registry = PluginRegistry()
    plugin = CompletePlugin()
    later = PluginKey("validation_gate", "z-protocol", "1.0")
    earlier = PluginKey("snapshot_loader", "a-protocol", "1.0")

    registry.register(later, plugin)
    registry.register(earlier, plugin)

    assert registry.resolve(earlier) is plugin
    assert registry.keys() == (earlier, later)
    with pytest.raises(DuplicatePluginError, match="already registered"):
        registry.register(earlier, plugin)
    with pytest.raises(MissingPluginError, match="not registered"):
        registry.resolve(PluginKey("dataset_freezer", "missing", "1.0"))


def test_dispatch_depends_on_protocol_key_not_agent_or_capability_identity():
    registry = PluginRegistry()
    plugin = CompletePlugin()
    key = PluginKey("snapshot_loader", "provider-protocol", "1.0")
    registry.register(key, plugin)

    for arbitrary_root in (
        Path("provider-a/capabilities"),
        Path("another-agent/capabilities"),
    ):
        resolved = registry.resolve(key)
        assert resolved.load(arbitrary_root) == arbitrary_root


def test_builtin_registration_uses_stable_protocol_keys():
    plugin = CompletePlugin()
    registry = register_builtins(
        snapshot_loader=plugin,
        capability_resolver=plugin,
        source_pack_compiler=plugin,
        coverage_planner=plugin,
        case_generator=plugin,
        validation_gate=plugin,
        review_renderer=plugin,
        dataset_freezer=plugin,
    )

    assert len(registry.keys()) == 8
    assert {key.protocol for key in registry.keys()} == {BUILTIN_PROTOCOL}
    assert {key.version for key in registry.keys()} == {"1.0"}

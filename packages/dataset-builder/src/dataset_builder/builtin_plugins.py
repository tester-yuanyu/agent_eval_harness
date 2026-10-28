"""Registration helpers for the framework's built-in plugin implementations."""

from __future__ import annotations

from .capability_adapters import CapabilityAdapter
from .plugins import PluginKey, PluginRegistry

BUILTIN_PROTOCOL = "dataset-builder-core"
BUILTIN_VERSION = "1.0"


def register_capability_adapter(
    registry: PluginRegistry | None = None,
) -> PluginRegistry:
    registry = registry or PluginRegistry()
    registry.register(
        PluginKey(
            "capability_adapter", "capability-snapshot", "1.0"
        ),
        CapabilityAdapter(),
    )
    return registry


def register_builtins(
    *,
    snapshot_loader: object,
    capability_resolver: object,
    source_pack_compiler: object,
    coverage_planner: object,
    case_generator: object,
    validation_gate: object,
    review_renderer: object,
    dataset_freezer: object,
) -> PluginRegistry:
    plugins = {
        "snapshot_loader": snapshot_loader,
        "capability_resolver": capability_resolver,
        "source_pack_compiler": source_pack_compiler,
        "coverage_planner": coverage_planner,
        "case_generator": case_generator,
        "validation_gate": validation_gate,
        "review_renderer": review_renderer,
        "dataset_freezer": dataset_freezer,
    }
    registry = PluginRegistry()
    for role, plugin in plugins.items():
        registry.register(
            PluginKey(role, BUILTIN_PROTOCOL, BUILTIN_VERSION), plugin
        )
    return registry

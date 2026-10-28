"""MiniAgent compatibility wrappers over the portable v3 compiler."""

from pathlib import Path

from capability_snapshot_kit.bundle import (
    CapabilityBundleV3,
    calculate_capability_bundle_sha256_v3,
    reference_for_snapshot_v3,
    schema_artifacts_v3,
)
from capability_snapshot_kit.compiler import (
    compile_capability_bundle_v3,
    compile_capability_snapshot_v3,
)
from capability_snapshot_kit.exporting import (
    _write_capability_bundle_v3 as _portable_write_capability_bundle_v3,
)
from capability_snapshot_kit.exporting import (
    export_capability_bundle_v3 as _export_portable_bundle_v3,
)
from capability_snapshot_kit.models import SnapshotV3
from capability_snapshot_kit.spec_loader import load_capability_spec_pack_v3
from minimal_agent.capability_adapter import MiniAgentCapabilityAdapter
from minimal_agent.contracts.intents import IntentRegistry
from minimal_agent.runtime.tool_registry import ToolRegistry

DEFAULT_CAPABILITY_SPEC_ROOT = Path(__file__).resolve().parents[4] / "capability_specs"
_write_capability_bundle_v3 = _portable_write_capability_bundle_v3


def _adapter(
    intent_registry: IntentRegistry,
    tool_registry: ToolRegistry,
) -> MiniAgentCapabilityAdapter:
    return MiniAgentCapabilityAdapter(intent_registry, tool_registry)


def build_capability_bundle_v3(
    intent_registry: IntentRegistry,
    tool_registry: ToolRegistry,
) -> CapabilityBundleV3:
    """Build the MiniAgent Bundle through the portable Spec/Adapter compiler."""

    return compile_capability_bundle_v3(
        load_capability_spec_pack_v3(DEFAULT_CAPABILITY_SPEC_ROOT),
        _adapter(intent_registry, tool_registry),
    )


def build_capability_snapshot_v3(
    snapshot_id: str,
    intent_registry: IntentRegistry,
    tool_registry: ToolRegistry,
) -> SnapshotV3:
    return compile_capability_snapshot_v3(
        snapshot_id,
        load_capability_spec_pack_v3(DEFAULT_CAPABILITY_SPEC_ROOT),
        _adapter(intent_registry, tool_registry),
    )


def export_capability_bundle_v3(
    output_root: str | Path,
    intent_registry: IntentRegistry,
    tool_registry: ToolRegistry,
) -> list[Path]:
    return _export_portable_bundle_v3(
        output_root,
        load_capability_spec_pack_v3(DEFAULT_CAPABILITY_SPEC_ROOT),
        _adapter(intent_registry, tool_registry),
    )


__all__ = [
    "CapabilityBundleV3",
    "build_capability_bundle_v3",
    "build_capability_snapshot_v3",
    "calculate_capability_bundle_sha256_v3",
    "export_capability_bundle_v3",
    "reference_for_snapshot_v3",
    "schema_artifacts_v3",
]

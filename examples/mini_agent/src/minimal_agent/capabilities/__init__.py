"""Stable public facade for the Capability Snapshot Protocol."""

from capability_snapshot_kit import (
    BundleValidationResult,
    CapabilityBundle,
    CapabilityBundleValidationError,
    validate_capability_bundle,
)
from minimal_agent.capabilities.v3 import (
    build_capability_bundle_v3,
    build_capability_snapshot_v3,
    export_capability_bundle_v3,
)

build_capability_bundle = build_capability_bundle_v3
build_capability_snapshot = build_capability_snapshot_v3
export_capability_bundle = export_capability_bundle_v3

__all__ = [
    "BundleValidationResult",
    "CapabilityBundle",
    "CapabilityBundleValidationError",
    "build_capability_bundle",
    "build_capability_snapshot",
    "export_capability_bundle",
    "validate_capability_bundle",
]

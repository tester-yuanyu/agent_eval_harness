"""Compatibility re-exports for portable v3 graph resolution."""

from capability_snapshot_kit.resolution import (
    CapabilitySelectionV3,
    ResolvedCapabilityGraphV3,
    ResolvedRequirementV3,
    resolve_capability_graph_v3,
)

__all__ = [
    "CapabilitySelectionV3",
    "ResolvedCapabilityGraphV3",
    "ResolvedRequirementV3",
    "resolve_capability_graph_v3",
]

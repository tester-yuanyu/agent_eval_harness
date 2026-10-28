import capability_snapshot_kit as kit

UNVERSIONED_ALIASES = {
    "SNAPSHOT_FORMAT_VERSION": "SNAPSHOT_FORMAT_VERSION_V3",
    "AgentFacts": "AgentFactsV3",
    "AgentSnapshot": "AgentSnapshotV3",
    "BoundarySnapshot": "BoundarySnapshotV3",
    "BundleDiff": "BundleDiffV3",
    "BundleValidationResult": "BundleValidationResultV3",
    "CapabilityAdapter": "CapabilityAdapterV3",
    "CapabilityBundle": "CapabilityBundleV3",
    "CapabilityBundleValidationError": "CapabilityBundleValidationErrorV3",
    "CapabilityCompilationError": "CapabilityCompilationErrorV3",
    "CapabilityClaim": "CapabilityClaimV3",
    "CapabilityProvider": "CapabilityProviderV3",
    "CapabilityRequirement": "CapabilityRequirementV3",
    "CapabilitySelection": "CapabilitySelectionV3",
    "CapabilitySpecLoadError": "CapabilitySpecLoadErrorV3",
    "CapabilitySpecPack": "CapabilitySpecPackV3",
    "ChainNode": "ChainNodeV3",
    "ChainSnapshot": "ChainSnapshotV3",
    "EvidenceFact": "EvidenceFactV3",
    "EvidenceSnapshot": "EvidenceSnapshotV3",
    "IntentFact": "IntentFactV3",
    "IntentSnapshot": "IntentSnapshotV3",
    "ModuleFact": "ModuleFactV3",
    "ModuleSnapshot": "ModuleSnapshotV3",
    "ResolvedCapabilityGraph": "ResolvedCapabilityGraphV3",
    "ResolvedRequirement": "ResolvedRequirementV3",
    "ScopeSnapshot": "ScopeSnapshotV3",
    "Snapshot": "SnapshotV3",
    "SnapshotReference": "SnapshotReferenceV3",
    "SnapshotType": "SnapshotTypeV3",
    "SupportStatus": "SupportStatusV3",
    "ToolFact": "ToolFactV3",
    "ToolSnapshot": "ToolSnapshotV3",
    "calculate_capability_bundle_sha256": (
        "calculate_capability_bundle_sha256_v3"
    ),
    "collect_snapshot_references": "collect_snapshot_references_v3",
    "compile_capability_bundle": "compile_capability_bundle_v3",
    "compile_capability_snapshot": "compile_capability_snapshot_v3",
    "diff_capability_bundles": "diff_capability_bundles_v3",
    "export_capability_bundle": "export_capability_bundle_v3",
    "load_capability_bundle": "load_capability_bundle_v3",
    "load_capability_spec_pack": "load_capability_spec_pack_v3",
    "reference_for_snapshot": "reference_for_snapshot_v3",
    "resolve_capability_graph": "resolve_capability_graph_v3",
    "schema_artifacts": "schema_artifacts_v3",
    "snapshot_schema": "snapshot_schema_v3",
    "validate_capability_bundle": "validate_capability_bundle_v3",
}


def test_unversioned_names_are_object_identical_public_aliases() -> None:
    for public_name, concrete_name in UNVERSIONED_ALIASES.items():
        assert getattr(kit, public_name) is getattr(kit, concrete_name)


def test_unversioned_names_are_declared_public() -> None:
    assert set(UNVERSIONED_ALIASES) <= set(kit.__all__)

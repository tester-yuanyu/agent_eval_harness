"""Portable Capability Snapshot Protocol toolkit."""

from capability_snapshot_kit.adapter import CapabilityAdapterV3
from capability_snapshot_kit.bundle import (
    CapabilityBundleV3,
    calculate_capability_bundle_sha256_v3,
    reference_for_snapshot_v3,
    schema_artifacts_v3,
)
from capability_snapshot_kit.compiler import (
    CapabilityCompilationErrorV3,
    compile_capability_bundle_v3,
    compile_capability_snapshot_v3,
)
from capability_snapshot_kit.diffing import BundleDiffV3, diff_capability_bundles_v3
from capability_snapshot_kit.exporting import export_capability_bundle_v3
from capability_snapshot_kit.facts import (
    AgentFactsV3,
    EvidenceFactV3,
    IntentFactV3,
    ModuleFactV3,
    ToolFactV3,
)
from capability_snapshot_kit.hashing import (
    calculate_snapshot_sha256,
    canonical_json_bytes,
    sha256_json,
)
from capability_snapshot_kit.models import (
    AgentSnapshotV3,
    BoundarySnapshotV3,
    CapabilityClaimV3,
    CapabilityProviderV3,
    CapabilityRequirementV3,
    ChainNodeV3,
    ChainSnapshotV3,
    EvidenceSnapshotV3,
    IntentSnapshotV3,
    ModuleSnapshotV3,
    ScopeSnapshotV3,
    SnapshotReferenceV3,
    SnapshotTypeV3,
    SnapshotV3,
    SupportStatusV3,
    ToolSnapshotV3,
    snapshot_schema_v3,
)
from capability_snapshot_kit.resolution import (
    CapabilitySelectionV3,
    ResolvedCapabilityGraphV3,
    ResolvedRequirementV3,
    resolve_capability_graph_v3,
)
from capability_snapshot_kit.spec_loader import (
    CapabilitySpecLoadErrorV3,
    load_capability_spec_pack_v3,
)
from capability_snapshot_kit.spec_models import CapabilitySpecPackV3
from capability_snapshot_kit.validation import (
    BundleValidationResultV3,
    CapabilityBundleValidationErrorV3,
    collect_snapshot_references_v3,
    load_capability_bundle_v3,
    validate_capability_bundle_v3,
)
from capability_snapshot_kit.versions import SNAPSHOT_FORMAT_VERSION_V3

SNAPSHOT_FORMAT_VERSION = SNAPSHOT_FORMAT_VERSION_V3
AgentFacts = AgentFactsV3
AgentSnapshot = AgentSnapshotV3
BoundarySnapshot = BoundarySnapshotV3
BundleDiff = BundleDiffV3
BundleValidationResult = BundleValidationResultV3
CapabilityAdapter = CapabilityAdapterV3
CapabilityBundle = CapabilityBundleV3
CapabilityBundleValidationError = CapabilityBundleValidationErrorV3
CapabilityCompilationError = CapabilityCompilationErrorV3
CapabilityClaim = CapabilityClaimV3
CapabilityProvider = CapabilityProviderV3
CapabilityRequirement = CapabilityRequirementV3
CapabilitySelection = CapabilitySelectionV3
CapabilitySpecLoadError = CapabilitySpecLoadErrorV3
CapabilitySpecPack = CapabilitySpecPackV3
ChainNode = ChainNodeV3
ChainSnapshot = ChainSnapshotV3
EvidenceFact = EvidenceFactV3
EvidenceSnapshot = EvidenceSnapshotV3
IntentFact = IntentFactV3
IntentSnapshot = IntentSnapshotV3
ModuleFact = ModuleFactV3
ModuleSnapshot = ModuleSnapshotV3
ResolvedCapabilityGraph = ResolvedCapabilityGraphV3
ResolvedRequirement = ResolvedRequirementV3
ScopeSnapshot = ScopeSnapshotV3
Snapshot = SnapshotV3
SnapshotReference = SnapshotReferenceV3
SnapshotType = SnapshotTypeV3
SupportStatus = SupportStatusV3
ToolFact = ToolFactV3
ToolSnapshot = ToolSnapshotV3
calculate_capability_bundle_sha256 = calculate_capability_bundle_sha256_v3
collect_snapshot_references = collect_snapshot_references_v3
compile_capability_bundle = compile_capability_bundle_v3
compile_capability_snapshot = compile_capability_snapshot_v3
diff_capability_bundles = diff_capability_bundles_v3
export_capability_bundle = export_capability_bundle_v3
load_capability_bundle = load_capability_bundle_v3
load_capability_spec_pack = load_capability_spec_pack_v3
reference_for_snapshot = reference_for_snapshot_v3
resolve_capability_graph = resolve_capability_graph_v3
schema_artifacts = schema_artifacts_v3
snapshot_schema = snapshot_schema_v3
validate_capability_bundle = validate_capability_bundle_v3

__all__ = [
    "SNAPSHOT_FORMAT_VERSION",
    "SNAPSHOT_FORMAT_VERSION_V3",
    "AgentFacts",
    "AgentFactsV3",
    "AgentSnapshot",
    "AgentSnapshotV3",
    "BoundarySnapshot",
    "BoundarySnapshotV3",
    "BundleDiff",
    "BundleDiffV3",
    "BundleValidationResult",
    "BundleValidationResultV3",
    "CapabilityAdapter",
    "CapabilityBundle",
    "CapabilityBundleValidationError",
    "CapabilityCompilationError",
    "CapabilityClaim",
    "CapabilityProvider",
    "CapabilityRequirement",
    "CapabilitySelection",
    "CapabilitySpecLoadError",
    "CapabilitySpecPack",
    "CapabilityBundleV3",
    "CapabilityCompilationErrorV3",
    "CapabilityBundleValidationErrorV3",
    "CapabilityAdapterV3",
    "CapabilityClaimV3",
    "CapabilityProviderV3",
    "CapabilityRequirementV3",
    "CapabilitySelectionV3",
    "CapabilitySpecLoadErrorV3",
    "CapabilitySpecPackV3",
    "ChainNode",
    "ChainNodeV3",
    "ChainSnapshot",
    "ChainSnapshotV3",
    "EvidenceFact",
    "EvidenceSnapshot",
    "EvidenceSnapshotV3",
    "EvidenceFactV3",
    "IntentFact",
    "IntentSnapshot",
    "IntentSnapshotV3",
    "IntentFactV3",
    "ModuleFact",
    "ModuleSnapshot",
    "ModuleSnapshotV3",
    "ModuleFactV3",
    "ResolvedCapabilityGraph",
    "ResolvedRequirement",
    "ScopeSnapshot",
    "ScopeSnapshotV3",
    "ResolvedCapabilityGraphV3",
    "ResolvedRequirementV3",
    "Snapshot",
    "SnapshotReference",
    "SnapshotType",
    "SupportStatus",
    "SnapshotReferenceV3",
    "SnapshotTypeV3",
    "SnapshotV3",
    "SupportStatusV3",
    "ToolFact",
    "ToolSnapshot",
    "ToolSnapshotV3",
    "ToolFactV3",
    "calculate_capability_bundle_sha256",
    "calculate_capability_bundle_sha256_v3",
    "calculate_snapshot_sha256",
    "canonical_json_bytes",
    "compile_capability_bundle_v3",
    "compile_capability_snapshot_v3",
    "collect_snapshot_references",
    "collect_snapshot_references_v3",
    "export_capability_bundle_v3",
    "diff_capability_bundles",
    "diff_capability_bundles_v3",
    "load_capability_bundle_v3",
    "reference_for_snapshot",
    "reference_for_snapshot_v3",
    "resolve_capability_graph_v3",
    "schema_artifacts",
    "schema_artifacts_v3",
    "sha256_json",
    "snapshot_schema",
    "snapshot_schema_v3",
    "validate_capability_bundle_v3",
    "compile_capability_bundle",
    "compile_capability_snapshot",
    "export_capability_bundle",
    "load_capability_bundle",
    "load_capability_spec_pack",
    "resolve_capability_graph",
    "validate_capability_bundle",
    "load_capability_spec_pack_v3",
]

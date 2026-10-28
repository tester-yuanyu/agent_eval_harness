"""In-memory bundles and deterministic artifact references."""

from __future__ import annotations

from dataclasses import dataclass

from capability_snapshot_kit.hashing import sha256_json
from capability_snapshot_kit.models import (
    AgentSnapshotV3,
    BoundarySnapshotV3,
    ChainSnapshotV3,
    EvidenceSnapshotV3,
    IntentSnapshotV3,
    ModuleSnapshotV3,
    ScopeSnapshotV3,
    SnapshotReferenceV3,
    SnapshotTypeV3,
    SnapshotV3,
    ToolSnapshotV3,
    snapshot_schema_v3,
)
from capability_snapshot_kit.versions import SNAPSHOT_FORMAT_VERSION_V3


@dataclass(frozen=True)
class CapabilityBundleV3:
    agent: AgentSnapshotV3
    modules: dict[str, ModuleSnapshotV3]
    intents: dict[str, IntentSnapshotV3]
    tools: dict[str, ToolSnapshotV3]
    scopes: dict[str, ScopeSnapshotV3]
    chains: dict[str, ChainSnapshotV3]
    evidence: dict[str, EvidenceSnapshotV3]
    boundaries: dict[str, BoundarySnapshotV3]

    @property
    def child_snapshots(self) -> tuple[SnapshotV3, ...]:
        children: list[SnapshotV3] = [
            *self.modules.values(),
            *self.intents.values(),
            *self.tools.values(),
            *self.scopes.values(),
            *self.chains.values(),
            *self.evidence.values(),
            *self.boundaries.values(),
        ]
        return tuple(sorted(children, key=lambda item: item.snapshot_id))

    @property
    def child_references(self) -> tuple[SnapshotReferenceV3, ...]:
        return tuple(reference_for_snapshot_v3(item) for item in self.child_snapshots)


_DIRECTORY_BY_TYPE = {
    SnapshotTypeV3.MODULE: "modules",
    SnapshotTypeV3.INTENT: "intents",
    SnapshotTypeV3.TOOL: "tools",
    SnapshotTypeV3.SCOPE: "scopes",
    SnapshotTypeV3.CHAIN: "chains",
    SnapshotTypeV3.EVIDENCE: "evidence",
    SnapshotTypeV3.BOUNDARY: "boundaries",
}


def reference_for_snapshot_v3(snapshot: SnapshotV3) -> SnapshotReferenceV3:
    if snapshot.snapshot_type == SnapshotTypeV3.AGENT:
        raise ValueError("Agent snapshots cannot be referenced as children")
    directory = _DIRECTORY_BY_TYPE[snapshot.snapshot_type]
    local_id = snapshot.snapshot_id.split(".", 1)[1]
    if snapshot.snapshot_type == SnapshotTypeV3.CHAIN:
        category = "end_to_end" if local_id == "end_to_end" else "critical"
        directory = f"{directory}/{category}"
    return SnapshotReferenceV3(
        snapshot_id=snapshot.snapshot_id,
        snapshot_type=snapshot.snapshot_type,
        snapshot_format_version=SNAPSHOT_FORMAT_VERSION_V3,
        contract_version=snapshot.contract_version,
        snapshot_sha256=snapshot.snapshot_sha256,
        path=f"{directory}/{local_id}.json",
    )


def calculate_capability_bundle_sha256_v3(
    references: tuple[SnapshotReferenceV3, ...] | list[SnapshotReferenceV3],
) -> str:
    ids = [reference.snapshot_id for reference in references]
    if len(ids) != len(set(ids)):
        raise ValueError("capability bundle contains duplicate snapshot IDs")
    return sha256_json(
        [
            reference.model_dump(mode="json")
            for reference in sorted(references, key=lambda item: item.snapshot_id)
        ]
    )


def schema_artifacts_v3() -> dict[str, dict[str, object]]:
    return {
        "agent.schema.json": snapshot_schema_v3(SnapshotTypeV3.AGENT),
        "module.schema.json": snapshot_schema_v3(SnapshotTypeV3.MODULE),
        "intent.schema.json": snapshot_schema_v3(SnapshotTypeV3.INTENT),
        "tool.schema.json": snapshot_schema_v3(SnapshotTypeV3.TOOL),
        "scope.schema.json": snapshot_schema_v3(SnapshotTypeV3.SCOPE),
        "chain.schema.json": snapshot_schema_v3(SnapshotTypeV3.CHAIN),
        "evidence.schema.json": snapshot_schema_v3(SnapshotTypeV3.EVIDENCE),
        "boundary.schema.json": snapshot_schema_v3(SnapshotTypeV3.BOUNDARY),
        "snapshot-reference.schema.json": SnapshotReferenceV3.model_json_schema(),
    }

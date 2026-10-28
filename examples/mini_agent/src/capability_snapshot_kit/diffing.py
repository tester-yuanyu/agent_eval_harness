"""Read-only bundle diffing with an in-memory reverse dependency index."""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

from capability_snapshot_kit.base import ProtocolModel
from capability_snapshot_kit.bundle import CapabilityBundleV3
from capability_snapshot_kit.models import ChainSnapshotV3, ScopeSnapshotV3
from capability_snapshot_kit.validation import (
    collect_snapshot_references_v3,
    load_capability_bundle_v3,
)


class BundleDiffV3(ProtocolModel):
    added_ids: list[str]
    removed_ids: list[str]
    changed_ids: list[str]
    affected_selection_roots: list[str]


def _snapshots(bundle: CapabilityBundleV3):
    return {
        bundle.agent.snapshot_id: bundle.agent,
        **{snapshot.snapshot_id: snapshot for snapshot in bundle.child_snapshots},
    }


def _reverse_index(bundle: CapabilityBundleV3) -> dict[str, set[str]]:
    snapshots = _snapshots(bundle)
    reverse: dict[str, set[str]] = defaultdict(set)
    for source_id, snapshot in snapshots.items():
        for reference in collect_snapshot_references_v3(snapshot):
            reverse[reference.snapshot_id].add(source_id)
        if not isinstance(snapshot, (ScopeSnapshotV3, ChainSnapshotV3)):
            continue
        for requirement in snapshot.requirements:
            if requirement.provider.role == "snapshot":
                provider_id = requirement.provider.snapshot_id
                if provider_id is not None:
                    reverse[provider_id].add(source_id)
            elif requirement.provider.role == "selected_intent":
                for intent_id in bundle.intents:
                    reverse[intent_id].add(source_id)
            elif requirement.provider.role == "selected_tool":
                for tool_id in bundle.tools:
                    reverse[tool_id].add(source_id)
            for evidence_id in requirement.evidence_ids:
                reverse[evidence_id].add(source_id)
    return reverse


def diff_capability_bundles_v3(
    old_root: str | Path,
    new_root: str | Path,
) -> BundleDiffV3:
    """Compare validated artifacts without mutating either bundle."""

    old_bundle = load_capability_bundle_v3(old_root)
    new_bundle = load_capability_bundle_v3(new_root)
    old = _snapshots(old_bundle)
    new = _snapshots(new_bundle)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(
        snapshot_id
        for snapshot_id in set(old) & set(new)
        if old[snapshot_id].snapshot_sha256 != new[snapshot_id].snapshot_sha256
    )

    reverse: dict[str, set[str]] = defaultdict(set)
    for index in (_reverse_index(old_bundle), _reverse_index(new_bundle)):
        for target_id, consumer_ids in index.items():
            reverse[target_id].update(consumer_ids)

    affected: set[str] = set()
    visited: set[str] = set()
    pending = deque([*added, *removed, *changed])
    while pending:
        snapshot_id = pending.popleft()
        if snapshot_id in visited:
            continue
        visited.add(snapshot_id)
        if snapshot_id.startswith(("scope.", "chain.", "intent.")):
            affected.add(snapshot_id)
        pending.extend(sorted(reverse.get(snapshot_id, ())))

    return BundleDiffV3(
        added_ids=added,
        removed_ids=removed,
        changed_ids=changed,
        affected_selection_roots=sorted(affected),
    )

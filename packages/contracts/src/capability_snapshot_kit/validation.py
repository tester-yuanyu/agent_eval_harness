"""Standalone validation and typed loading for Capability Protocol v3."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from capability_snapshot_kit.base import ProtocolModel
from capability_snapshot_kit.bundle import (
    CapabilityBundleV3,
    calculate_capability_bundle_sha256_v3,
    reference_for_snapshot_v3,
    schema_artifacts_v3,
)
from capability_snapshot_kit.hashing import calculate_snapshot_sha256, sha256_json
from capability_snapshot_kit.models import (
    AgentSnapshotV3,
    BoundarySnapshotV3,
    ChainSnapshotV3,
    EvidenceSnapshotV3,
    IntentSnapshotV3,
    ModuleSnapshotV3,
    ScopeSnapshotV3,
    SnapshotReferenceV3,
    SnapshotV3,
    SupportStatusV3,
    ToolSnapshotV3,
)


class CapabilityBundleValidationErrorV3(ValueError):
    def __init__(self, diagnostics: list[str]) -> None:
        self.diagnostics = tuple(sorted(set(diagnostics)))
        super().__init__("; ".join(self.diagnostics))


class BundleValidationResultV3(ProtocolModel):
    valid: bool = True
    snapshot_counts: dict[str, int]
    capability_bundle_sha256: str
    agent_snapshot_sha256: str


_MODEL_BY_DIRECTORY = {
    "modules": ModuleSnapshotV3,
    "intents": IntentSnapshotV3,
    "tools": ToolSnapshotV3,
    "scopes": ScopeSnapshotV3,
    "chains": ChainSnapshotV3,
    "evidence": EvidenceSnapshotV3,
    "boundaries": BoundarySnapshotV3,
}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON document must be an object")
    return value


def collect_snapshot_references_v3(
    snapshot: SnapshotV3,
) -> tuple[SnapshotReferenceV3, ...]:
    if isinstance(snapshot, AgentSnapshotV3):
        values = [
            *snapshot.module_refs,
            *snapshot.intent_refs,
            *snapshot.tool_refs,
            *snapshot.scope_refs,
            *snapshot.chain_refs,
            *snapshot.evidence_refs,
            *snapshot.boundary_refs,
        ]
    elif isinstance(snapshot, ModuleSnapshotV3):
        values = [
            *snapshot.module_refs,
            *snapshot.intent_refs,
            *snapshot.tool_refs,
        ]
    elif isinstance(snapshot, IntentSnapshotV3):
        values = list(snapshot.tool_refs)
    elif isinstance(snapshot, (ScopeSnapshotV3, ChainSnapshotV3)):
        values = [
            *snapshot.module_refs,
            *snapshot.evidence_refs,
            *snapshot.boundary_refs,
        ]
    else:
        values = []
    return tuple(values)


def _parse_artifacts(
    root: Path,
) -> tuple[AgentSnapshotV3, dict[str, SnapshotV3], dict[str, Path], list[str]]:
    diagnostics: list[str] = []
    agent_path = root / "agent.json"
    try:
        agent = AgentSnapshotV3.model_validate(_load_json(agent_path))
    except (ValueError, ValidationError) as exc:
        raise CapabilityBundleValidationErrorV3([f"agent.json: {exc}"]) from exc

    snapshots: dict[str, SnapshotV3] = {agent.snapshot_id: agent}
    paths_by_id = {agent.snapshot_id: agent_path}
    for directory, model in _MODEL_BY_DIRECTORY.items():
        folder = root / directory
        if not folder.is_dir():
            diagnostics.append(f"missing directory: {directory}")
            continue
        for path in sorted(folder.rglob("*.json")):
            relative = path.relative_to(root)
            try:
                snapshot = model.model_validate(_load_json(path))
            except (ValueError, ValidationError) as exc:
                diagnostics.append(f"{relative}: {exc}")
                continue
            if snapshot.snapshot_id in snapshots:
                diagnostics.append(f"duplicate snapshot_id: {snapshot.snapshot_id}")
                continue
            snapshots[snapshot.snapshot_id] = snapshot
            paths_by_id[snapshot.snapshot_id] = path
    return agent, snapshots, paths_by_id, diagnostics


def _validate_snapshot_hashes(
    snapshots: dict[str, SnapshotV3], diagnostics: list[str]
) -> None:
    for snapshot in snapshots.values():
        expected = calculate_snapshot_sha256(snapshot.model_dump(mode="json"))
        if snapshot.snapshot_sha256 != expected:
            diagnostics.append(f"{snapshot.snapshot_id}: snapshot_sha256 mismatch")


def _validate_paths(
    root: Path,
    snapshots: dict[str, SnapshotV3],
    paths_by_id: dict[str, Path],
    diagnostics: list[str],
) -> None:
    for snapshot_id, snapshot in snapshots.items():
        if isinstance(snapshot, AgentSnapshotV3):
            continue
        expected = root / reference_for_snapshot_v3(snapshot).path
        if paths_by_id[snapshot_id].resolve() != expected.resolve():
            diagnostics.append(f"{snapshot_id}: artifact path mismatch")


def _validate_references(
    root: Path,
    snapshots: dict[str, SnapshotV3],
    paths_by_id: dict[str, Path],
    diagnostics: list[str],
) -> None:
    resolved_root = root.resolve()
    for source in snapshots.values():
        for reference in collect_snapshot_references_v3(source):
            target = snapshots.get(reference.snapshot_id)
            referenced_path = (root / reference.path).resolve()
            if not referenced_path.is_relative_to(resolved_root):
                diagnostics.append(
                    f"{source.snapshot_id}: reference escapes bundle root"
                )
                continue
            if target is None or not referenced_path.is_file():
                diagnostics.append(
                    f"{reference.snapshot_id}: missing referenced file "
                    f"{reference.path}"
                )
                continue
            actual_path = paths_by_id.get(reference.snapshot_id)
            if actual_path is None or actual_path.resolve() != referenced_path:
                diagnostics.append(f"{reference.snapshot_id}: reference path mismatch")
            for field_name in (
                "snapshot_type",
                "snapshot_format_version",
                "contract_version",
                "snapshot_sha256",
            ):
                if getattr(reference, field_name) != getattr(target, field_name):
                    diagnostics.append(
                        f"{source.snapshot_id} -> {reference.snapshot_id}: "
                        f"reference {field_name} mismatch"
                    )


def _validate_root_scope(
    agent: AgentSnapshotV3,
    snapshots: dict[str, SnapshotV3],
    diagnostics: list[str],
) -> None:
    root_ids = {
        reference.snapshot_id for reference in collect_snapshot_references_v3(agent)
    }
    child_ids = set(snapshots) - {agent.snapshot_id}
    outside = child_ids - root_ids
    missing = root_ids - child_ids
    if outside:
        diagnostics.append(
            "snapshots outside Agent scope: " + ", ".join(sorted(outside))
        )
    if missing:
        diagnostics.append(
            "Agent references absent snapshots: " + ", ".join(sorted(missing))
        )


def _validate_cycles(
    snapshots: dict[str, SnapshotV3], diagnostics: list[str]
) -> None:
    graph = {
        snapshot_id: sorted(
            reference.snapshot_id
            for reference in collect_snapshot_references_v3(snapshot)
            if reference.snapshot_id in snapshots
        )
        for snapshot_id, snapshot in snapshots.items()
    }
    visited: set[str] = set()
    active: list[str] = []
    active_set: set[str] = set()

    def visit(snapshot_id: str) -> None:
        if snapshot_id in active_set:
            start = active.index(snapshot_id)
            diagnostics.append(
                "reference cycle: " + " -> ".join([*active[start:], snapshot_id])
            )
            return
        if snapshot_id in visited:
            return
        active.append(snapshot_id)
        active_set.add(snapshot_id)
        for target_id in graph.get(snapshot_id, []):
            visit(target_id)
        active.pop()
        active_set.remove(snapshot_id)
        visited.add(snapshot_id)

    for snapshot_id in sorted(graph):
        visit(snapshot_id)


def _claims(snapshot: SnapshotV3) -> list:
    if isinstance(
        snapshot,
        (AgentSnapshotV3, ModuleSnapshotV3, IntentSnapshotV3, ToolSnapshotV3),
    ):
        return list(snapshot.capabilities)
    if isinstance(snapshot, EvidenceSnapshotV3):
        return [snapshot.availability]
    return []


def _validate_semantics(
    snapshots: dict[str, SnapshotV3], diagnostics: list[str]
) -> None:
    evidence = {
        snapshot_id: snapshot
        for snapshot_id, snapshot in snapshots.items()
        if isinstance(snapshot, EvidenceSnapshotV3)
    }
    modules = {
        snapshot_id: snapshot
        for snapshot_id, snapshot in snapshots.items()
        if isinstance(snapshot, ModuleSnapshotV3)
    }
    boundaries = {
        snapshot_id: snapshot
        for snapshot_id, snapshot in snapshots.items()
        if isinstance(snapshot, BoundarySnapshotV3)
    }
    for snapshot in snapshots.values():
        for claim in _claims(snapshot):
            if claim.support_status != SupportStatusV3.SUPPORTED:
                continue
            unknown = set(claim.evidence_ids) - set(evidence)
            if unknown:
                diagnostics.append(
                    f"{snapshot.snapshot_id}: supported claim "
                    f"{claim.capability_key} has unknown Evidence {sorted(unknown)}"
                )
            unavailable = [
                evidence_id
                for evidence_id in claim.evidence_ids
                if evidence_id in evidence
                and evidence[evidence_id].availability.support_status
                != SupportStatusV3.SUPPORTED
            ]
            if unavailable:
                diagnostics.append(
                    f"{snapshot.snapshot_id}: supported claim "
                    f"{claim.capability_key} uses unavailable Evidence "
                    f"{sorted(unavailable)}"
                )
        if isinstance(snapshot, ModuleSnapshotV3):
            unknown_boundaries = set(snapshot.execution_boundary_ids) - set(boundaries)
            if unknown_boundaries:
                diagnostics.append(
                    f"{snapshot.snapshot_id}: unknown Boundary "
                    f"{sorted(unknown_boundaries)}"
                )
        if isinstance(snapshot, EvidenceSnapshotV3):
            unknown_modules = set(snapshot.producer_module_ids) - set(modules)
            if unknown_modules:
                diagnostics.append(
                    f"{snapshot.snapshot_id}: unknown producer Module "
                    f"{sorted(unknown_modules)}"
                )
        if isinstance(snapshot, BoundarySnapshotV3):
            unknown_modules = (
                set(snapshot.allowed_module_ids) | set(snapshot.prohibited_module_ids)
            ) - set(modules)
            unknown_evidence = set(snapshot.evidence_ids) - set(evidence)
            if unknown_modules:
                diagnostics.append(
                    f"{snapshot.snapshot_id}: unknown Module {sorted(unknown_modules)}"
                )
            if unknown_evidence:
                diagnostics.append(
                    f"{snapshot.snapshot_id}: unknown Evidence "
                    f"{sorted(unknown_evidence)}"
                )
        if isinstance(snapshot, (ScopeSnapshotV3, ChainSnapshotV3)):
            for requirement in snapshot.requirements:
                unknown_evidence = set(requirement.evidence_ids) - set(evidence)
                if unknown_evidence:
                    diagnostics.append(
                        f"{snapshot.snapshot_id}: requirement "
                        f"{requirement.requirement_id} has unknown Evidence "
                        f"{sorted(unknown_evidence)}"
                    )
                provider_id = requirement.provider.snapshot_id
                if (
                    requirement.provider.role == "snapshot"
                    and provider_id not in snapshots
                ):
                    diagnostics.append(
                        f"{snapshot.snapshot_id}: requirement "
                        f"{requirement.requirement_id} has unknown provider "
                        f"{provider_id}"
                    )

    agent = next(
        (
            snapshot
            for snapshot in snapshots.values()
            if isinstance(snapshot, AgentSnapshotV3)
        ),
        None,
    )
    if agent is not None:
        expected = sha256_json(
            [item.model_dump(mode="json") for item in agent.capabilities]
        )
        if agent.source_hashes.get("capabilities_sha256") != expected:
            diagnostics.append("Agent capability summary mismatch")


def _validate_bundle_hash(
    agent: AgentSnapshotV3,
    snapshots: dict[str, SnapshotV3],
    diagnostics: list[str],
) -> None:
    children = [
        reference_for_snapshot_v3(snapshot)
        for snapshot_id, snapshot in snapshots.items()
        if snapshot_id != agent.snapshot_id
    ]
    try:
        expected = calculate_capability_bundle_sha256_v3(children)
    except ValueError as exc:
        diagnostics.append(str(exc))
        return
    if agent.capability_bundle_sha256 != expected:
        diagnostics.append("Bundle hash mismatch")


def _validate_schemas(root: Path, diagnostics: list[str]) -> set[Path]:
    paths: set[Path] = set()
    for name, expected in schema_artifacts_v3().items():
        path = root / "schemas" / name
        paths.add(path)
        if not path.is_file():
            diagnostics.append(f"missing Schema artifact: schemas/{name}")
            continue
        try:
            actual = _load_json(path)
        except ValueError as exc:
            diagnostics.append(f"schemas/{name}: {exc}")
            continue
        if actual != expected:
            diagnostics.append(f"Schema artifact mismatch: schemas/{name}")
    return paths


def validate_capability_bundle_v3(
    input_root: str | Path,
) -> BundleValidationResultV3:
    root = Path(input_root)
    agent, snapshots, paths_by_id, diagnostics = _parse_artifacts(root)
    _validate_snapshot_hashes(snapshots, diagnostics)
    _validate_paths(root, snapshots, paths_by_id, diagnostics)
    _validate_references(root, snapshots, paths_by_id, diagnostics)
    _validate_root_scope(agent, snapshots, diagnostics)
    _validate_cycles(snapshots, diagnostics)
    _validate_semantics(snapshots, diagnostics)
    _validate_bundle_hash(agent, snapshots, diagnostics)
    schema_paths = _validate_schemas(root, diagnostics)
    known_json_paths = {*paths_by_id.values(), *schema_paths}
    unexpected = {
        path.relative_to(root)
        for path in root.rglob("*.json")
        if path not in known_json_paths
    }
    if unexpected:
        diagnostics.append(
            "unexpected JSON artifacts: "
            + ", ".join(str(path) for path in sorted(unexpected))
        )
    if diagnostics:
        raise CapabilityBundleValidationErrorV3(diagnostics)
    counts = {
        "agent": 1,
        "module": 0,
        "intent": 0,
        "tool": 0,
        "scope": 0,
        "chain": 0,
        "evidence": 0,
        "boundary": 0,
    }
    for snapshot_id in set(snapshots) - {agent.snapshot_id}:
        counts[snapshot_id.split(".", 1)[0]] += 1
    return BundleValidationResultV3(
        snapshot_counts=counts,
        capability_bundle_sha256=agent.capability_bundle_sha256,
        agent_snapshot_sha256=agent.snapshot_sha256,
    )


def load_capability_bundle_v3(input_root: str | Path) -> CapabilityBundleV3:
    root = Path(input_root)
    validate_capability_bundle_v3(root)
    agent, snapshots, _, diagnostics = _parse_artifacts(root)
    if diagnostics:
        raise CapabilityBundleValidationErrorV3(diagnostics)

    def select(model: type) -> dict:
        return {
            snapshot_id: snapshot
            for snapshot_id, snapshot in snapshots.items()
            if isinstance(snapshot, model)
        }

    return CapabilityBundleV3(
        agent=agent,
        modules=select(ModuleSnapshotV3),
        intents=select(IntentSnapshotV3),
        tools=select(ToolSnapshotV3),
        scopes=select(ScopeSnapshotV3),
        chains=select(ChainSnapshotV3),
        evidence=select(EvidenceSnapshotV3),
        boundaries=select(BoundarySnapshotV3),
    )

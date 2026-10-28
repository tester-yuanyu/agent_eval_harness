"""Provider-neutral validation for immutable capability bundles."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator

from .capability_profiles import (
    LoadedProtocolProfile,
    TrustedSchemaBinding,
    canonical_json_bytes,
    verify_bundle_schemas,
)

REFERENCE_PROJECTION_FIELDS = (
    "snapshot_id",
    "snapshot_type",
    "snapshot_format_version",
    "contract_version",
    "path",
    "snapshot_sha256",
)


class CapabilityBundleError(ValueError):
    """Raised when an untrusted or internally inconsistent bundle is found."""

    def __init__(self, diagnostics: Iterable[str]) -> None:
        self.diagnostics = tuple(sorted(set(diagnostics)))
        super().__init__("; ".join(self.diagnostics))


@dataclass(frozen=True)
class BundleArtifact:
    path: Path
    relative_path: str
    payload: Mapping[str, Any]
    snapshot_id: str
    snapshot_type: str
    snapshot_format_version: str
    contract_version: str
    snapshot_sha256: str


@dataclass(frozen=True)
class ValidatedCapabilityBundle:
    root_path: Path
    profile: LoadedProtocolProfile
    root: BundleArtifact
    artifacts: tuple[BundleArtifact, ...]
    artifacts_by_id: Mapping[str, BundleArtifact]
    artifacts_by_path: Mapping[str, BundleArtifact]
    reference_graph: Mapping[str, tuple[str, ...]]
    schema_bindings: tuple[TrustedSchemaBinding, ...]
    capability_bundle_sha256: str
    snapshot_counts: Mapping[str, int]

    @property
    def validated_files(self) -> tuple[tuple[str, Path], ...]:
        """Return only snapshots and trusted schemas that define the Bundle."""
        relative_paths = {
            artifact.relative_path for artifact in self.artifacts
        } | {binding.relative_path for binding in self.schema_bindings}
        return tuple(
            (relative_path, self.root_path / relative_path)
            for relative_path in sorted(relative_paths)
        )

    def reference_closure(
        self, starting_snapshot_ids: Iterable[str]
    ) -> tuple[BundleArtifact, ...]:
        """Return a deterministic transitive closure for selected artifacts."""
        pending = deque(sorted(set(starting_snapshot_ids)))
        visited: set[str] = set()
        while pending:
            snapshot_id = pending.popleft()
            if snapshot_id in visited:
                continue
            artifact = self.artifacts_by_id.get(snapshot_id)
            if artifact is None:
                raise KeyError(snapshot_id)
            visited.add(snapshot_id)
            pending.extend(self.reference_graph.get(snapshot_id, ()))
        return tuple(self.artifacts_by_id[item] for item in sorted(visited))


def calculate_artifact_sha256(payload: Mapping[str, Any]) -> str:
    """Calculate the protocol hash, excluding its self-referential field."""
    projected = dict(payload)
    projected.pop("snapshot_sha256", None)
    return hashlib.sha256(canonical_json_bytes(projected)).hexdigest()


def _safe_relative_path(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or any(part in {"", "."} for part in candidate.parts)
    ):
        return None
    return value


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityBundleError([f"invalid_json:{path}:{exc}"]) from exc
    if not isinstance(value, dict):
        raise CapabilityBundleError([f"artifact_not_object:{path}"])
    return value


def _schema_errors(
    payload: Mapping[str, Any], schema: Mapping[str, Any], relative_path: str
) -> list[str]:
    result: list[str] = []
    for error in Draft202012Validator(schema).iter_errors(payload):
        location = "/".join(str(part) for part in error.absolute_path) or "$"
        result.append(
            f"schema_validation_failed:{relative_path}:{location}:{error.message}"
        )
    return result


def _all_references(
    artifact: BundleArtifact, profile: LoadedProtocolProfile
) -> list[Mapping[str, Any]]:
    definition = profile.profile.snapshot_types.get(artifact.snapshot_type)
    if definition is None:
        return []
    references: list[Mapping[str, Any]] = []
    for field in definition.reference_fields:
        value = artifact.payload.get(field, [])
        if isinstance(value, list):
            references.extend(item for item in value if isinstance(item, dict))
    return references


def _bundle_hash(references: Iterable[Mapping[str, Any]]) -> str:
    projection = [
        {field: reference.get(field) for field in REFERENCE_PROJECTION_FIELDS}
        for reference in references
    ]
    projection.sort(key=lambda item: str(item.get("snapshot_id", "")))
    return hashlib.sha256(canonical_json_bytes(projection)).hexdigest()


def _cycle_diagnostics(graph: Mapping[str, tuple[str, ...]]) -> list[str]:
    diagnostics: list[str] = []
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> None:
        status = state.get(node, 0)
        if status == 2:
            return
        if status == 1:
            start = stack.index(node)
            cycle = "->".join((*stack[start:], node))
            diagnostics.append(f"reference_cycle:{cycle}")
            return
        state[node] = 1
        stack.append(node)
        for target in graph.get(node, ()):
            if target in graph:
                visit(target)
        stack.pop()
        state[node] = 2

    for snapshot_id in sorted(graph):
        if state.get(snapshot_id, 0) == 0:
            visit(snapshot_id)
    return diagnostics


def load_validated_bundle(
    bundle_root: Path,
    profile: LoadedProtocolProfile,
) -> ValidatedCapabilityBundle:
    """Load and validate a complete capability bundle using a trusted profile."""
    root_path = bundle_root.resolve()
    if not root_path.is_dir():
        raise FileNotFoundError(root_path)
    schema_bindings = verify_bundle_schemas(profile, root_path)
    diagnostics: list[str] = []

    schema_by_type: dict[str, Mapping[str, Any]] = {}
    for snapshot_type, definition in profile.profile.snapshot_types.items():
        schema_by_type[snapshot_type] = _read_object(root_path / definition.schema_path)
    reference_schema_definition = profile.profile.supporting_schemas.get(
        "snapshot_reference"
    )
    reference_schema = (
        _read_object(root_path / reference_schema_definition.schema_path)
        if reference_schema_definition
        else None
    )

    artifacts: list[BundleArtifact] = []
    schemas_root = (root_path / "schemas").resolve()
    for path in sorted(root_path.rglob("*.json")):
        resolved = path.resolve()
        if resolved.is_relative_to(schemas_root):
            continue
        relative_path = resolved.relative_to(root_path).as_posix()
        if relative_path == "bundle_manifest.json":
            continue
        payload = _read_object(resolved)
        snapshot_type = payload.get("snapshot_type")
        if not isinstance(snapshot_type, str):
            diagnostics.append(f"missing_snapshot_type:{relative_path}")
            continue
        if snapshot_type not in profile.profile.snapshot_types:
            diagnostics.append(
                f"unsupported_snapshot_type:{relative_path}:{snapshot_type}"
            )
            continue
        diagnostics.extend(
            _schema_errors(payload, schema_by_type[snapshot_type], relative_path)
        )
        artifact = BundleArtifact(
            path=resolved,
            relative_path=relative_path,
            payload=MappingProxyType(payload),
            snapshot_id=str(payload.get("snapshot_id", "")),
            snapshot_type=snapshot_type,
            snapshot_format_version=str(payload.get("snapshot_format_version", "")),
            contract_version=str(payload.get("contract_version", "")),
            snapshot_sha256=str(payload.get("snapshot_sha256", "")),
        )
        artifacts.append(artifact)
        actual_hash = calculate_artifact_sha256(payload)
        if actual_hash != artifact.snapshot_sha256:
            diagnostics.append(
                "artifact_hash_mismatch:"
                f"{relative_path}:expected={artifact.snapshot_sha256}:actual={actual_hash}"
            )
        if artifact.snapshot_format_version != profile.profile.protocol_version:
            diagnostics.append(
                "mixed_protocol_version:"
                f"{relative_path}:{artifact.snapshot_format_version}"
            )

    by_id_lists: dict[str, list[BundleArtifact]] = {}
    by_path = {artifact.relative_path: artifact for artifact in artifacts}
    for artifact in artifacts:
        by_id_lists.setdefault(artifact.snapshot_id, []).append(artifact)
    for snapshot_id, matches in by_id_lists.items():
        if len(matches) > 1:
            diagnostics.append(f"duplicate_snapshot_id:{snapshot_id}")
    by_id = {key: value[0] for key, value in by_id_lists.items() if value}

    root_artifact = by_path.get(profile.profile.root_filename)
    if root_artifact is None:
        diagnostics.append(f"missing_root_artifact:{profile.profile.root_filename}")
    elif root_artifact.snapshot_type != profile.profile.root_snapshot_type:
        diagnostics.append(
            "root_snapshot_type_mismatch:"
            f"{root_artifact.snapshot_type}:{profile.profile.root_snapshot_type}"
        )

    graph: dict[str, tuple[str, ...]] = {}
    for artifact in artifacts:
        targets: list[str] = []
        for index, reference in enumerate(_all_references(artifact, profile)):
            if reference_schema is not None:
                diagnostics.extend(
                    _schema_errors(
                        reference,
                        reference_schema,
                        f"{artifact.relative_path}:reference[{index}]",
                    )
                )
            ref_id = reference.get("snapshot_id")
            if isinstance(ref_id, str):
                targets.append(ref_id)
            ref_path = _safe_relative_path(reference.get("path"))
            if ref_path is None:
                diagnostics.append(
                    f"unsafe_reference_path:{artifact.snapshot_id}:{reference.get('path')}"
                )
                continue
            target = by_path.get(ref_path)
            if target is None:
                diagnostics.append(
                    f"dangling_reference:{artifact.snapshot_id}:{ref_path}"
                )
                continue
            checks = (
                ("snapshot_id", target.snapshot_id, "reference_id_mismatch"),
                ("snapshot_type", target.snapshot_type, "reference_type_mismatch"),
                (
                    "snapshot_format_version",
                    target.snapshot_format_version,
                    "reference_version_mismatch",
                ),
                (
                    "contract_version",
                    target.contract_version,
                    "reference_contract_mismatch",
                ),
                ("snapshot_sha256", target.snapshot_sha256, "reference_hash_mismatch"),
            )
            for field, expected, code in checks:
                if reference.get(field) != expected:
                    diagnostics.append(
                        f"{code}:{artifact.snapshot_id}:{field}:"
                        f"expected={expected}:found={reference.get(field)}"
                    )
        graph[artifact.snapshot_id] = tuple(sorted(set(targets)))

    diagnostics.extend(_cycle_diagnostics(graph))

    if root_artifact is not None:
        reachable: set[str] = set()
        pending = deque([root_artifact.snapshot_id])
        while pending:
            current = pending.popleft()
            if current in reachable:
                continue
            reachable.add(current)
            pending.extend(graph.get(current, ()))
        for artifact in artifacts:
            if artifact.snapshot_id not in reachable:
                diagnostics.append(f"unreferenced_artifact:{artifact.snapshot_id}")

        root_references = _all_references(root_artifact, profile)
        calculated_bundle_hash = _bundle_hash(root_references)
        declared_bundle_hash = root_artifact.payload.get("capability_bundle_sha256")
        if declared_bundle_hash != calculated_bundle_hash:
            diagnostics.append(
                "bundle_hash_mismatch:"
                f"expected={declared_bundle_hash}:actual={calculated_bundle_hash}"
            )
    else:
        calculated_bundle_hash = ""

    if diagnostics:
        raise CapabilityBundleError(diagnostics)

    assert root_artifact is not None
    observed_counts = Counter(artifact.snapshot_type for artifact in artifacts)
    counts = {
        snapshot_type: observed_counts.get(snapshot_type, 0)
        for snapshot_type in sorted(profile.profile.snapshot_types)
    }
    frozen_graph = MappingProxyType(dict(sorted(graph.items())))
    return ValidatedCapabilityBundle(
        root_path=root_path,
        profile=profile,
        root=root_artifact,
        artifacts=tuple(sorted(artifacts, key=lambda item: item.snapshot_id)),
        artifacts_by_id=MappingProxyType(dict(sorted(by_id.items()))),
        artifacts_by_path=MappingProxyType(dict(sorted(by_path.items()))),
        reference_graph=frozen_graph,
        schema_bindings=schema_bindings,
        capability_bundle_sha256=calculated_bundle_hash,
        snapshot_counts=MappingProxyType(counts),
    )

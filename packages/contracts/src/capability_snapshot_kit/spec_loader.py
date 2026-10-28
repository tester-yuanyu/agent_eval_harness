"""Safe loading and structural validation for portable Capability Specs."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import ValidationError

from capability_snapshot_kit.spec_models import (
    BoundarySpecV3,
    CapabilitySpecPackV3,
    ChainSpecV3,
    EvidenceSpecV3,
    ProtocolSpecV3,
    ScopeSpecV3,
)

SpecModel = TypeVar(
    "SpecModel",
    ProtocolSpecV3,
    ScopeSpecV3,
    ChainSpecV3,
    EvidenceSpecV3,
    BoundarySpecV3,
)


class CapabilitySpecLoadErrorV3(ValueError):
    """One or more deterministic Spec diagnostics."""

    def __init__(self, diagnostics: Iterable[str]) -> None:
        self.diagnostics = tuple(sorted(set(diagnostics)))
        super().__init__("; ".join(self.diagnostics))


def _document(path: Path, model: type[SpecModel]) -> SpecModel:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CapabilitySpecLoadErrorV3([f"{path}: {exc}"]) from exc
    if not text.startswith("---\n"):
        raise CapabilitySpecLoadErrorV3([f"{path}: missing YAML Front Matter"])
    marker = "\n---\n"
    end = text.find(marker, 4)
    if end < 0:
        raise CapabilitySpecLoadErrorV3([f"{path}: missing YAML closing delimiter"])
    front_matter = text[4:end]
    documentation = text[end + len(marker) :].strip()
    if not documentation:
        raise CapabilitySpecLoadErrorV3([f"{path}: Markdown body is required"])
    try:
        payload = yaml.safe_load(front_matter)
    except yaml.YAMLError as exc:
        raise CapabilitySpecLoadErrorV3(
            [f"{path}: unsafe or invalid YAML: {exc}"]
        ) from exc
    if not isinstance(payload, dict):
        raise CapabilitySpecLoadErrorV3([f"{path}: Front Matter must be a mapping"])
    try:
        return model.model_validate({**payload, "documentation": documentation})
    except ValidationError as exc:
        raise CapabilitySpecLoadErrorV3([f"{path}: {exc}"]) from exc


def _catalog(
    root: Path,
    directory: str,
    model: type[SpecModel],
) -> dict[str, SpecModel]:
    result: dict[str, SpecModel] = {}
    for path in sorted((root / directory).rglob("*.md")):
        spec = _document(path, model)
        snapshot_id = spec.snapshot_id
        if snapshot_id in result:
            raise CapabilitySpecLoadErrorV3(
                [f"duplicate snapshot_id: {snapshot_id}"]
            )
        result[snapshot_id] = spec
    return result


def load_capability_spec_pack_v3(
    spec_root: str | Path,
) -> CapabilitySpecPackV3:
    root = Path(spec_root)
    protocol = _document(root / "protocol.md", ProtocolSpecV3)
    scopes = _catalog(root, "scopes", ScopeSpecV3)
    chains = _catalog(root, "chains", ChainSpecV3)
    evidence = _catalog(root, "evidence", EvidenceSpecV3)
    boundaries = _catalog(root, "boundaries", BoundarySpecV3)
    diagnostics: list[str] = []
    evidence_ids = set(evidence)
    boundary_ids = set(boundaries)
    for spec in [*scopes.values(), *chains.values()]:
        missing_evidence = set(spec.evidence_ids) - evidence_ids
        missing_boundary = {spec.boundary_id} - boundary_ids
        for requirement in spec.requirements:
            missing_evidence.update(set(requirement.evidence_ids) - evidence_ids)
        if missing_evidence:
            diagnostics.append(
                f"{spec.snapshot_id}: unknown Evidence {sorted(missing_evidence)}"
            )
        if missing_boundary:
            diagnostics.append(
                f"{spec.snapshot_id}: unknown Boundary {sorted(missing_boundary)}"
            )
    for spec in boundaries.values():
        missing_evidence = set(spec.evidence_ids) - evidence_ids
        if missing_evidence:
            diagnostics.append(
                f"{spec.snapshot_id}: unknown Evidence {sorted(missing_evidence)}"
            )
    if diagnostics:
        raise CapabilitySpecLoadErrorV3(diagnostics)
    return CapabilitySpecPackV3(
        protocol=protocol,
        scopes=scopes,
        chains=chains,
        evidence=evidence,
        boundaries=boundaries,
    )

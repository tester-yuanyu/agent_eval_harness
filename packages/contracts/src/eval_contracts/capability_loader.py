"""Load verified capability artifacts without changing source payloads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import (
    SchemaError,
    ValidationError,
    _WrappedReferencingError,
)
from referencing import Registry

from .capabilities import (
    CapabilityBundle,
    CapabilityBundleError,
    CapabilityDocument,
    canonical_json_bytes,
)

_REFERENCE_FIELDS = (
    "module_refs",
    "intent_refs",
    "tool_refs",
    "scope_refs",
    "chain_refs",
    "evidence_refs",
    "boundary_refs",
)
_REFERENCE_KEYS = (
    "snapshot_id",
    "snapshot_type",
    "snapshot_format_version",
    "contract_version",
    "path",
    "snapshot_sha256",
)


def load_capability_bundle(
    root: Path,
    *,
    expected_sha256: str | None = None,
) -> CapabilityBundle:
    """Load either the current agent.json protocol or a legacy frozen bundle."""

    resolved_root = root.resolve()
    if (resolved_root / "bundle_manifest.json").is_file():
        bundle = CapabilityBundle.load(resolved_root)
    else:
        bundle = _load_agent_json_bundle(resolved_root)
    if (
        expected_sha256 is not None
        and bundle.capability_bundle_sha256 != expected_sha256
    ):
        raise CapabilityBundleError(
            "capability bundle hash mismatch: "
            f"expected {expected_sha256}, "
            f"calculated {bundle.capability_bundle_sha256}"
        )
    return bundle


def _load_agent_json_bundle(root: Path) -> CapabilityBundle:
    agent = _read_json_object(_resolve_inside(root, "agent.json"), "agent.json")
    _validate_schema(root, "agent", agent, "agent.json")
    if agent.get("snapshot_type") != "agent":
        raise CapabilityBundleError("agent.json must be an agent snapshot")

    references = _agent_references(agent)
    snapshot_ids = [item["snapshot_id"] for item in references]
    if len(snapshot_ids) != len(set(snapshot_ids)):
        raise CapabilityBundleError("duplicate snapshot_id in agent references")

    children: list[CapabilityDocument] = []
    for reference in references:
        relative = reference["path"]
        path = _resolve_inside(root, relative)
        payload = _read_json_object(path, relative)
        snapshot_type = reference["snapshot_type"]
        _validate_schema(root, snapshot_type, payload, relative)
        _verify_reference(reference, payload)
        _verify_snapshot_hash(payload, relative)
        children.append(_document(payload))

    _verify_snapshot_hash(agent, "agent.json")
    declared_hash = agent.get("capability_bundle_sha256")
    calculated_hash = _sha256(
        canonical_json_bytes(
            sorted(references, key=lambda item: item["snapshot_id"])
        )
    )
    if declared_hash != calculated_hash:
        raise CapabilityBundleError(
            "capability bundle hash mismatch: "
            f"expected {declared_hash}, calculated {calculated_hash}"
        )

    provider_id = agent.get("agent_id")
    format_version = agent.get("snapshot_format_version")
    if not isinstance(provider_id, str) or not provider_id:
        raise CapabilityBundleError("agent.json agent_id is required")
    if not isinstance(format_version, str) or not format_version:
        raise CapabilityBundleError("agent.json snapshot_format_version is required")
    if not isinstance(declared_hash, str):
        raise CapabilityBundleError("agent.json capability_bundle_sha256 is required")
    documents = (_document(agent), *children)
    _validate_unique_documents(documents)
    return CapabilityBundle(
        root=str(root),
        provider_id=provider_id,
        bundle_format_version=format_version,
        capability_bundle_sha256=declared_hash,
        documents=documents,
    )


def _agent_references(agent: dict[str, Any]) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for field in _REFERENCE_FIELDS:
        value = agent.get(field)
        if not isinstance(value, list):
            raise CapabilityBundleError(f"agent.json {field} must be an array")
        for raw in value:
            if not isinstance(raw, dict) or not all(
                isinstance(raw.get(key), str) and raw[key] for key in _REFERENCE_KEYS
            ):
                raise CapabilityBundleError(
                    f"agent.json {field} contains an invalid snapshot reference"
                )
            references.append({key: raw[key] for key in _REFERENCE_KEYS})
    return references


def _resolve_inside(root: Path, relative: str) -> Path:
    candidate = PurePosixPath(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise CapabilityBundleError(f"bundle file is outside bundle: {relative}")
    try:
        path = (root / Path(*candidate.parts)).resolve(strict=True)
    except OSError as exc:
        raise CapabilityBundleError(f"cannot read bundle file: {relative}") from exc
    if not path.is_relative_to(root):
        raise CapabilityBundleError(f"bundle file is outside bundle: {relative}")
    return path


def _read_json_object(path: Path, relative: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityBundleError(f"cannot read bundle file: {relative}") from exc
    if not isinstance(value, dict):
        raise CapabilityBundleError(f"bundle file must contain an object: {relative}")
    return value


def _validate_schema(
    root: Path,
    snapshot_type: str,
    payload: dict[str, Any],
    relative: str,
) -> None:
    schema_relative = f"schemas/{snapshot_type}.schema.json"
    schema = _read_json_object(_resolve_inside(root, schema_relative), schema_relative)
    _reject_external_schema_references(schema, schema_relative)
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, registry=Registry()).validate(payload)
    except (SchemaError, ValidationError, _WrappedReferencingError) as exc:
        raise CapabilityBundleError(
            f"capability schema validation failed for {relative}: {exc}"
        ) from exc


def _reject_external_schema_references(value: object, relative: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"$ref", "$dynamicRef"} and (
                not isinstance(child, str) or not child.startswith("#")
            ):
                raise CapabilityBundleError(
                    f"external schema reference is forbidden in {relative}"
                )
            _reject_external_schema_references(child, relative)
    elif isinstance(value, list):
        for child in value:
            _reject_external_schema_references(child, relative)


def _verify_reference(
    reference: dict[str, str], payload: dict[str, Any]
) -> None:
    for field in (
        "snapshot_id",
        "snapshot_type",
        "snapshot_format_version",
        "contract_version",
        "snapshot_sha256",
    ):
        if payload.get(field) != reference[field]:
            raise CapabilityBundleError(
                f"snapshot reference {field} mismatch for "
                f"{reference['snapshot_id']}"
            )


def _verify_snapshot_hash(payload: dict[str, Any], relative: str) -> None:
    expected = payload.get("snapshot_sha256")
    unsigned = dict(payload)
    unsigned.pop("snapshot_sha256", None)
    calculated = _sha256(canonical_json_bytes(unsigned))
    if expected != calculated:
        raise CapabilityBundleError(
            f"snapshot hash mismatch for {relative}: "
            f"expected {expected}, calculated {calculated}"
        )


def _document(payload: dict[str, Any]) -> CapabilityDocument:
    return CapabilityDocument(
        snapshot_id=payload.get("snapshot_id", ""),
        snapshot_type=payload.get("snapshot_type", ""),
        snapshot_format_version=payload.get("snapshot_format_version", ""),
        contract_version=payload.get("contract_version", ""),
        snapshot_sha256=payload.get("snapshot_sha256", ""),
        module_id=payload.get("module_id"),
        capability_id=payload.get("capability_id"),
        payload=dict(payload),
    )


def _validate_unique_documents(
    documents: tuple[CapabilityDocument, ...],
) -> None:
    _reject_duplicate_values(
        (item.snapshot_id for item in documents),
        "snapshot_id",
    )
    _reject_duplicate_values(
        (
            item.module_id
            for item in documents
            if item.snapshot_type == "module" and item.module_id is not None
        ),
        "module_id",
    )
    _reject_duplicate_values(
        (
            item.capability_id
            for item in documents
            if item.capability_id is not None
        ),
        "capability_id",
    )
    _reject_duplicate_values(
        (
            item.payload["tool_name"]
            for item in documents
            if item.snapshot_type in {"tool", "tool_capability"}
            and isinstance(item.payload.get("tool_name"), str)
        ),
        "tool_name",
    )


def _reject_duplicate_values(values: Iterable[object], field: str) -> None:
    materialized = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise CapabilityBundleError(f"duplicate {field} in capability bundle")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

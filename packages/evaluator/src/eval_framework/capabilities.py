"""Frozen machine-readable capability bundle loading and lookup."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import Field

from .schemas import StrictModel


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class CapabilityBundleError(ValueError):
    """A frozen capability bundle is malformed or fails integrity checks."""

    def __init__(self, message: str, *, code: str = "CAPABILITY_BUNDLE_INVALID"):
        super().__init__(message)
        self.code = code


class CapabilityDocument(StrictModel):
    snapshot_id: str = Field(min_length=1)
    snapshot_type: str = Field(min_length=1)
    snapshot_format_version: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    module_id: str | None = None
    capability_id: str | None = None
    payload: dict[str, Any]


class CapabilityBundle(StrictModel):
    root: str
    provider_id: str = Field(min_length=1)
    bundle_format_version: str = Field(min_length=1)
    capability_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    documents: tuple[CapabilityDocument, ...]

    def get_document(self, snapshot_id: str) -> CapabilityDocument:
        for document in self.documents:
            if document.snapshot_id == snapshot_id:
                return document
        raise KeyError(f"unknown capability snapshot {snapshot_id!r}")

    @classmethod
    def load_v2_directory(
        cls,
        root: Path,
        *,
        provider_id: str = "mini_agent",
    ) -> CapabilityBundle:
        """Load a source-owned v2 directory without a freeze manifest."""

        resolved_root = root.resolve()
        agent = _load_live_v2_document(resolved_root, "agent.json")
        if agent.snapshot_type != "agent":
            raise CapabilityBundleError("v2 root agent.json must be an agent snapshot")
        documents = [agent]
        by_id = {agent.snapshot_id: agent}
        references_by_id: dict[str, dict[str, str]] = {}
        pending = list(_iter_snapshot_references(agent.payload))
        while pending:
            reference = pending.pop(0)
            snapshot_id = reference["snapshot_id"]
            if snapshot_id in by_id:
                existing = by_id[snapshot_id]
                if existing.snapshot_sha256 != reference["snapshot_sha256"]:
                    raise CapabilityBundleError(
                        f"conflicting v2 snapshot reference for {snapshot_id}"
                    )
                continue
            document = _load_live_v2_document(
                resolved_root,
                reference["path"],
            )
            _verify_v2_reference(reference, document)
            by_id[snapshot_id] = document
            references_by_id[snapshot_id] = reference
            documents.append(document)
            pending.extend(_iter_snapshot_references(document.payload))
        references = list(references_by_id.values())
        declared = agent.payload.get("capability_bundle_sha256")
        calculated = _v2_bundle_hash(references)
        if declared != calculated:
            raise CapabilityBundleError(
                "v2 capability bundle hash does not match child snapshot references"
            )
        result = cls(
            root=str(resolved_root),
            provider_id=provider_id,
            bundle_format_version="2.0",
            capability_bundle_sha256=declared,
            documents=tuple(documents),
        )
        _validate_unique_documents(result.documents)
        return result

    @classmethod
    def load(cls, root: Path) -> CapabilityBundle:
        resolved_root = root.resolve()
        manifest_path = resolved_root / "bundle_manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CapabilityBundleError(
                f"cannot read capability bundle manifest: {manifest_path}"
            ) from exc
        if not isinstance(manifest, dict):
            raise CapabilityBundleError("bundle manifest must be a JSON object")
        provider_id = manifest.get("provider_id")
        format_version = manifest.get("bundle_format_version")
        files = manifest.get("files")
        expected_bundle_hash = manifest.get("capability_bundle_sha256")
        if (
            not isinstance(provider_id, str)
            or not provider_id
            or not isinstance(format_version, str)
            or not format_version
            or not isinstance(files, list)
            or not isinstance(expected_bundle_hash, str)
        ):
            raise CapabilityBundleError("bundle manifest has invalid required fields")
        if format_version == "1.0":
            identity = {
                "provider_id": provider_id,
                "bundle_format_version": format_version,
                "files": files,
            }
            actual_bundle_hash = _sha256(canonical_json_bytes(identity))
            if actual_bundle_hash != expected_bundle_hash:
                raise CapabilityBundleError(
                    "capability bundle hash mismatch: "
                    f"expected {expected_bundle_hash}, "
                    f"calculated {actual_bundle_hash}"
                )
            documents = tuple(
                _load_document(resolved_root, entry) for entry in files
            )
        elif format_version == "2.0":
            documents = _load_v2_documents(
                resolved_root,
                files,
                manifest,
                expected_bundle_hash,
            )
        else:
            raise CapabilityBundleError(
                f"unsupported capability bundle format {format_version!r}"
            )
        _validate_unique_documents(documents)
        return cls(
            root=str(resolved_root),
            provider_id=provider_id,
            bundle_format_version=format_version,
            capability_bundle_sha256=expected_bundle_hash,
            documents=documents,
        )


class CapabilityRegistry:
    def __init__(self, bundle: CapabilityBundle):
        self.bundle = bundle
        self._modules = {
            item.module_id: item
            for item in bundle.documents
            if item.snapshot_type == "module" and item.module_id is not None
        }
        self._capabilities = {
            item.capability_id: item
            for item in bundle.documents
            if item.capability_id is not None
        }
        self._tools = {
            item.payload["tool_name"]: item
            for item in bundle.documents
            if item.snapshot_type in {"tool", "tool_capability"}
            and isinstance(item.payload.get("tool_name"), str)
        }

    def get_module(self, module_id: str) -> CapabilityDocument:
        try:
            return self._modules[module_id]
        except KeyError as exc:
            raise KeyError(f"unknown module capability {module_id!r}") from exc

    def get_capability(self, capability_id: str) -> CapabilityDocument:
        try:
            return self._capabilities[capability_id]
        except KeyError as exc:
            raise KeyError(f"unknown capability {capability_id!r}") from exc

    def get_tool(self, tool_name: str) -> CapabilityDocument:
        try:
            return self._tools[tool_name]
        except KeyError as exc:
            raise KeyError(f"unknown tool capability {tool_name!r}") from exc

    def parameter_schema(self, capability_id: str) -> dict[str, Any]:
        schema = self.get_capability(capability_id).payload.get("parameters_schema")
        if not isinstance(schema, dict):
            raise KeyError(f"capability {capability_id!r} has no parameters_schema")
        return schema

    def display_metadata(self, capability_id: str) -> dict[str, Any]:
        value = self.get_capability(capability_id).payload.get("display", {})
        return value if isinstance(value, dict) else {}


def _load_document(root: Path, entry: object) -> CapabilityDocument:
    if not isinstance(entry, dict):
        raise CapabilityBundleError("bundle file entry must be an object")
    relative = entry.get("path")
    expected_file_hash = entry.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected_file_hash, str):
        raise CapabilityBundleError("bundle file entry requires path and sha256")
    candidate = PurePosixPath(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise CapabilityBundleError(f"bundle file is outside bundle: {relative}")
    path = (root / Path(*candidate.parts)).resolve()
    if not path.is_relative_to(root):
        raise CapabilityBundleError(f"bundle file is outside bundle: {relative}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CapabilityBundleError(f"cannot read bundle file: {relative}") from exc
    actual_file_hash = _sha256(raw)
    if actual_file_hash != expected_file_hash:
        raise CapabilityBundleError(
            f"bundle file hash mismatch for {relative}: "
            f"expected {expected_file_hash}, calculated {actual_file_hash}"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CapabilityBundleError(
            f"bundle file has invalid JSON: {relative}"
        ) from exc
    if not isinstance(payload, dict):
        raise CapabilityBundleError(f"bundle file must contain an object: {relative}")
    snapshot_hash = payload.get("snapshot_sha256")
    unsigned = dict(payload)
    unsigned.pop("snapshot_sha256", None)
    actual_snapshot_hash = _sha256(canonical_json_bytes(unsigned))
    if snapshot_hash != actual_snapshot_hash:
        raise CapabilityBundleError(
            f"snapshot hash mismatch for {relative}: "
            f"expected {snapshot_hash}, calculated {actual_snapshot_hash}"
        )
    version_fields = [
        name
        for name in (
            "contract_version",
            "module_contract_version",
            "tool_contract_version",
            "catalog_version",
        )
        if isinstance(payload.get(name), str) and payload[name]
    ]
    if len(version_fields) != 1:
        raise CapabilityBundleError(
            f"{relative} must define exactly one public contract version"
        )
    return CapabilityDocument(
        snapshot_id=payload.get("snapshot_id", ""),
        snapshot_type=payload.get("snapshot_type", ""),
        snapshot_format_version=payload.get("snapshot_format_version", ""),
        contract_version=payload[version_fields[0]],
        snapshot_sha256=snapshot_hash,
        module_id=payload.get("module_id"),
        capability_id=payload.get("capability_id"),
        payload=payload,
    )


def _load_v2_documents(
    root: Path,
    entries: list[Any],
    manifest: dict[str, Any],
    expected_bundle_hash: str,
) -> tuple[CapabilityDocument, ...]:
    source_hash = manifest.get("source_capability_bundle_sha256")
    agent_hash = manifest.get("agent_snapshot_sha256")
    if source_hash != expected_bundle_hash:
        raise CapabilityBundleError(
            "v2 source capability bundle hash does not match bundle identity"
        )
    documents: list[CapabilityDocument] = []
    references: list[dict[str, str]] = []
    for entry in entries:
        relative, payload = _load_v2_file(root, entry)
        if relative.startswith("schemas/"):
            continue
        document = _document_from_payload(payload, relative)
        documents.append(document)
        if document.snapshot_type != "agent":
            references.append(_v2_reference(document, relative))
    agents = [item for item in documents if item.snapshot_type == "agent"]
    if len(agents) != 1:
        raise CapabilityBundleError("v2 bundle must contain exactly one agent snapshot")
    agent = agents[0]
    if agent.snapshot_sha256 != agent_hash:
        raise CapabilityBundleError("v2 agent snapshot hash does not match manifest")
    declared = agent.payload.get("capability_bundle_sha256")
    calculated = _v2_bundle_hash(references)
    if declared != expected_bundle_hash or calculated != expected_bundle_hash:
        raise CapabilityBundleError(
            "v2 capability bundle hash does not match child snapshot references"
        )
    return tuple(documents)


def _v2_reference(
    document: CapabilityDocument, relative: str
) -> dict[str, str]:
    return {
        "snapshot_id": document.snapshot_id,
        "snapshot_type": document.snapshot_type,
        "snapshot_format_version": document.snapshot_format_version,
        "contract_version": document.contract_version,
        "path": relative,
        "snapshot_sha256": document.snapshot_sha256,
    }


def _v2_bundle_hash(references: list[dict[str, str]]) -> str:
    ordered = sorted(references, key=lambda item: item["snapshot_id"])
    return _sha256(canonical_json_bytes(ordered))


def _iter_snapshot_references(value: object) -> list[dict[str, str]]:
    required = {
        "snapshot_id",
        "snapshot_type",
        "snapshot_format_version",
        "contract_version",
        "snapshot_sha256",
        "path",
    }
    found: list[dict[str, str]] = []

    def visit(item: object) -> None:
        if isinstance(item, dict):
            if required <= item.keys() and all(
                isinstance(item[key], str) for key in required
            ):
                found.append({key: item[key] for key in required})
                return
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found


def _load_live_v2_document(root: Path, relative: str) -> CapabilityDocument:
    candidate = PurePosixPath(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise CapabilityBundleError(f"bundle file is outside bundle: {relative}")
    path = (root / Path(*candidate.parts)).resolve()
    if not path.is_relative_to(root):
        raise CapabilityBundleError(f"bundle file is outside bundle: {relative}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityBundleError(
            f"cannot read v2 capability snapshot: {relative}"
        ) from exc
    if not isinstance(payload, dict):
        raise CapabilityBundleError(
            f"v2 capability snapshot must be an object: {relative}"
        )
    return _document_from_payload(payload, relative)


def _verify_v2_reference(
    reference: dict[str, str], document: CapabilityDocument
) -> None:
    actual = {
        "snapshot_id": document.snapshot_id,
        "snapshot_type": document.snapshot_type,
        "snapshot_format_version": document.snapshot_format_version,
        "contract_version": document.contract_version,
        "snapshot_sha256": document.snapshot_sha256,
    }
    mismatched = [key for key, value in actual.items() if reference[key] != value]
    if mismatched:
        raise CapabilityBundleError(
            f"v2 snapshot reference mismatch for {reference['snapshot_id']}: "
            + ", ".join(mismatched)
        )


def _load_v2_file(root: Path, entry: object) -> tuple[str, dict[str, Any]]:
    if not isinstance(entry, dict):
        raise CapabilityBundleError("bundle file entry must be an object")
    relative = entry.get("path")
    expected_file_hash = entry.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected_file_hash, str):
        raise CapabilityBundleError("bundle file entry requires path and sha256")
    candidate = PurePosixPath(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise CapabilityBundleError(f"bundle file is outside bundle: {relative}")
    path = (root / Path(*candidate.parts)).resolve()
    if not path.is_relative_to(root):
        raise CapabilityBundleError(f"bundle file is outside bundle: {relative}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CapabilityBundleError(f"cannot read bundle file: {relative}") from exc
    actual_file_hash = _sha256(raw)
    if actual_file_hash != expected_file_hash:
        raise CapabilityBundleError(
            f"bundle file hash mismatch for {relative}: "
            f"expected {expected_file_hash}, calculated {actual_file_hash}"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CapabilityBundleError(
            f"bundle file has invalid JSON: {relative}"
        ) from exc
    if not isinstance(payload, dict):
        raise CapabilityBundleError(f"bundle file must contain an object: {relative}")
    return relative, payload


def _document_from_payload(
    payload: dict[str, Any], relative: str
) -> CapabilityDocument:
    snapshot_hash = payload.get("snapshot_sha256")
    unsigned = dict(payload)
    unsigned.pop("snapshot_sha256", None)
    calculated = _sha256(canonical_json_bytes(unsigned))
    if snapshot_hash != calculated:
        raise CapabilityBundleError(
            f"snapshot hash mismatch for {relative}: "
            f"expected {snapshot_hash}, calculated {calculated}"
        )
    contract_version = payload.get("contract_version")
    if not isinstance(contract_version, str) or not contract_version:
        raise CapabilityBundleError(
            f"{relative} must define exactly one public contract version"
        )
    return CapabilityDocument(
        snapshot_id=payload.get("snapshot_id", ""),
        snapshot_type=payload.get("snapshot_type", ""),
        snapshot_format_version=payload.get("snapshot_format_version", ""),
        contract_version=contract_version,
        snapshot_sha256=snapshot_hash,
        module_id=payload.get("module_id"),
        capability_id=payload.get("capability_id"),
        payload=payload,
    )


def _validate_unique_documents(
    documents: tuple[CapabilityDocument, ...],
) -> None:
    snapshot_ids = [item.snapshot_id for item in documents]
    if len(snapshot_ids) != len(set(snapshot_ids)):
        raise CapabilityBundleError("duplicate snapshot_id in capability bundle")
    capability_ids = [
        item.capability_id for item in documents if item.capability_id is not None
    ]
    if len(capability_ids) != len(set(capability_ids)):
        raise CapabilityBundleError("duplicate capability_id in capability bundle")

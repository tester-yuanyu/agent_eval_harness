"""Immutable source inventory backed by the existing trusted bundle kernel."""

import hashlib
import json
from pathlib import Path
from typing import Any

from ..capability_bundle import load_validated_bundle
from ..capability_profiles import load_trusted_profile
from .models import FullInventory, SourceRef

ROOT = Path(__file__).resolve().parents[3]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pointer_value(value: Any, pointer: str) -> Any:
    if not pointer:
        return value
    if not pointer.startswith("/"):
        raise ValueError("invalid JSON pointer")
    try:
        for part in pointer[1:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
        return value
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        raise ValueError(f"unresolved source pointer: {pointer}") from exc


def escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def load_inventory(
    bundle: Path, delivery_root: Path, expected_hash: str
) -> FullInventory:
    bundle, delivery_root = bundle.resolve(), delivery_root.resolve()
    manifest_path = delivery_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    bindings = {"manifest.json": digest(manifest_path)}
    for name, expected in manifest["files_sha256"].items():
        path = (delivery_root / name).resolve()
        if not path.is_relative_to(delivery_root) or not path.is_file():
            raise ValueError(f"unsafe or missing delivery path: {name}")
        actual = digest(path)
        if actual != expected:
            raise ValueError(f"delivery hash mismatch: {name}")
        bindings[name] = actual
    if bundle != (delivery_root / manifest["bundle_path"]).resolve():
        raise ValueError("bundle path differs from delivery manifest")
    if "capability_contract_gaps.json" not in bindings:
        raise ValueError("gap report must be hash-bound")
    profile = load_trusted_profile(
        "capability-snapshot", "3.0", ROOT / "protocol_profiles/trust_store.json"
    )
    validated = load_validated_bundle(bundle, profile)
    if validated.capability_bundle_sha256 != expected_hash:
        raise ValueError("expected bundle hash mismatch")
    if manifest["capability_bundle_sha256"] != expected_hash:
        raise ValueError("manifest bundle binding mismatch")
    gaps = json.loads((delivery_root / "capability_contract_gaps.json").read_text())
    if gaps["capability_bundle_sha256"] != expected_hash:
        raise ValueError("gaps bundle binding mismatch")
    artifacts = {}
    for item in validated.artifacts:
        relative = item.path.relative_to(delivery_root).as_posix()
        if relative not in bindings:
            raise ValueError(f"unbound source: {relative}")
        artifacts[item.snapshot_id] = {
            "relative_path": item.relative_path,
            "snapshot_sha256": item.snapshot_sha256,
            "payload": dict(item.payload),
        }
    targets = [
        {"snapshot_id": k, "snapshot_type": v["payload"]["snapshot_type"]}
        for k, v in artifacts.items()
        if v["payload"]["snapshot_type"] in {"module", "intent", "tool", "chain"}
    ]
    return FullInventory(
        bundle_sha256=expected_hash,
        bundle_path=str(bundle),
        delivery_root=str(delivery_root),
        targets=targets,
        artifacts=artifacts,
        external_bindings=bindings,
        gaps=gaps["gaps"],
    )


def source_ref(inv: FullInventory, snapshot_id: str, pointer: str) -> SourceRef:
    try:
        artifact = inv.artifacts[snapshot_id]
    except KeyError as exc:
        raise ValueError(f"unknown source: {snapshot_id}") from exc
    pointer_value(artifact["payload"], pointer)
    return SourceRef(
        snapshot_id=snapshot_id,
        relative_path=artifact["relative_path"],
        snapshot_sha256=artifact["snapshot_sha256"],
        pointer=pointer,
    )


def verify_sources(inv: FullInventory) -> None:
    for relative, expected in inv.external_bindings.items():
        path = Path(inv.delivery_root) / relative
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"source changed during generation: {relative}")

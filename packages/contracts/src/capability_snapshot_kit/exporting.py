"""Deterministic serialization and atomic replacement for v3 Bundles."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from capability_snapshot_kit.adapter import CapabilityAdapterV3
from capability_snapshot_kit.bundle import (
    CapabilityBundleV3,
    reference_for_snapshot_v3,
    schema_artifacts_v3,
)
from capability_snapshot_kit.compiler import compile_capability_bundle_v3
from capability_snapshot_kit.spec_models import CapabilitySpecPackV3
from capability_snapshot_kit.validation import validate_capability_bundle_v3


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_capability_bundle_v3(
    output_root: Path,
    bundle: CapabilityBundleV3,
) -> list[Path]:
    if output_root.exists():
        raise FileExistsError(f"v3 output root already exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    for directory in (
        "modules",
        "intents",
        "tools",
        "scopes",
        "chains",
        "evidence",
        "boundaries",
        "schemas",
    ):
        (output_root / directory).mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, schema in sorted(schema_artifacts_v3().items()):
        path = output_root / "schemas" / name
        _write_json(path, schema)
        written.append(path)
    for snapshot in bundle.child_snapshots:
        path = output_root / reference_for_snapshot_v3(snapshot).path
        _write_json(path, snapshot.model_dump(mode="json"))
        written.append(path)
    if not bundle.tools:
        marker = output_root / "tools" / ".gitkeep"
        marker.write_text("", encoding="utf-8")
        written.append(marker)
    agent_path = output_root / "agent.json"
    _write_json(agent_path, bundle.agent.model_dump(mode="json"))
    written.append(agent_path)
    return written


def export_capability_bundle_v3(
    output_root: str | Path,
    specs: CapabilitySpecPackV3,
    adapter: CapabilityAdapterV3,
) -> list[Path]:
    root = Path(output_root)
    root.parent.mkdir(parents=True, exist_ok=True)
    bundle = compile_capability_bundle_v3(specs, adapter)
    with tempfile.TemporaryDirectory(prefix=f".{root.name}-", dir=root.parent) as temp:
        staging = Path(temp) / root.name
        _write_capability_bundle_v3(staging, bundle)
        validate_capability_bundle_v3(staging)
        backup = root.parent / f".{root.name}-backup-{uuid4().hex}"
        if root.exists():
            os.replace(root, backup)
        try:
            os.replace(staging, root)
        except Exception:
            if backup.exists():
                os.replace(backup, root)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    return sorted(path for path in root.rglob("*") if path.is_file())
